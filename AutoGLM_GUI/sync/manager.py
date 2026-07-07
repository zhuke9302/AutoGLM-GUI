from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from AutoGLM_GUI.sync.client import ServerClient, ServerUnavailableError
from AutoGLM_GUI.sync.schemas import SyncConfig
from AutoGLM_GUI.sync.registration import SyncRegistration
from AutoGLM_GUI.sync.push_channel import PushChannel
from AutoGLM_GUI.sync.device_reporter import DeviceReporter
from AutoGLM_GUI.sync.sync_pull import SyncPull
from AutoGLM_GUI.sync.task_reporter import TaskReporter
from AutoGLM_GUI.sync.offline_queue import OfflineQueue

if TYPE_CHECKING:
    from AutoGLM_GUI.device_manager import DeviceManager
    from AutoGLM_GUI.task_manager import TaskManager
    from AutoGLM_GUI.scheduler_manager import SchedulerManager
    from AutoGLM_GUI.workflow_manager import WorkflowManager
    from AutoGLM_GUI.config_manager import UnifiedConfigManager

logger = logging.getLogger(__name__)


class SyncManager:
    """Top-level manager for the server sync subsystem.

    Orchestrates all sync components: registration, heartbeat, SSE push channel,
    device reporting, data pull, task reporting, and offline queue.
    """

    def __init__(self, config: SyncConfig | None = None):
        self._config = config or SyncConfig()
        self._client: ServerClient | None = None
        self._registration: SyncRegistration | None = None
        self._push_channel: PushChannel | None = None
        self._device_reporter: DeviceReporter | None = None
        self._sync_pull: SyncPull | None = None
        self._task_reporter: TaskReporter | None = None
        self._offline_queue: OfflineQueue | None = None
        self._started = False
        self._replay_task: asyncio.Task | None = None
        self._replay_interval: float = 60.0

    @property
    def is_active(self) -> bool:
        """Whether sync is active (server URL configured and started)."""
        return self._started and self._config.server_url is not None

    @property
    def is_connected(self) -> bool:
        """Whether currently connected to the server."""
        if self._push_channel:
            return self._push_channel.is_connected
        return False

    @property
    def offline_queue_size(self) -> int:
        """Number of items in the offline queue."""
        if self._offline_queue:
            return self._offline_queue.size()
        return 0

    async def start(
        self,
        device_manager: DeviceManager,
        task_manager: TaskManager,
        scheduler_manager: SchedulerManager,
        workflow_manager: WorkflowManager,
        config_manager: UnifiedConfigManager,
    ) -> None:
        """Start the sync subsystem.

        If server_url is not configured, this is a no-op (standalone mode).
        """
        if not self._config.server_url:
            logger.info("Server URL not configured, running in standalone mode")
            return

        logger.info("Starting sync subsystem, server_url=%s", self._config.server_url)

        # Initialize HTTP client
        self._client = ServerClient(
            server_url=self._config.server_url,
            timeout=30.0,
            max_retries=3,
        )
        await self._client.start()

        # Initialize offline queue
        self._offline_queue = OfflineQueue(
            capacity=self._config.offline_queue_capacity,
            expire_hours=self._config.offline_queue_expire_hours,
        )

        # Initialize registration
        self._registration = SyncRegistration(
            client=self._client,
            device_manager=device_manager,
            task_manager=task_manager,
            heartbeat_interval=self._config.heartbeat_interval_seconds,
        )

        # Initialize sync pull
        self._sync_pull = SyncPull(
            client=self._client,
            scheduler_manager=scheduler_manager,
            workflow_manager=workflow_manager,
            config_manager=config_manager,
        )

        # Initialize push channel
        self._push_channel = PushChannel(
            client=self._client,
            sync_pull=self._sync_pull,
            task_manager=task_manager,
            reconnect_max_delay=self._config.sse_reconnect_max_delay,
            on_reconnect=self._replay_offline_queue,
        )

        # Initialize device reporter
        self._device_reporter = DeviceReporter(
            client=self._client,
            device_manager=device_manager,
            offline_queue=self._offline_queue,
        )

        # Initialize task reporter
        self._task_reporter = TaskReporter(
            client=self._client,
            task_store=task_manager.store,
            task_manager=task_manager,
            batch_size=self._config.batch_event_size,
            offline_queue=self._offline_queue,
        )

        # Register with server
        resp = await self._registration.register()
        if resp:
            # Start all components
            await self._registration.start_heartbeat()
            await self._push_channel.start()
            await self._device_reporter.start()
            await self._task_reporter.start()
            # Initial full sync
            await self._sync_pull.full_sync()
            # Report current devices
            await self._device_reporter.report_all_devices()
            # Start offline queue replay loop
            if self._replay_task is None or self._replay_task.done():
                self._replay_task = asyncio.create_task(self._replay_loop())
            # Replay any queued items now that we're connected
            await self._replay_offline_queue()
            self._started = True
            logger.info("Sync subsystem started successfully")
        else:
            logger.warning("Failed to register with server, sync subsystem not started")

    async def stop(self) -> None:
        """Stop the sync subsystem."""
        if not self._started:
            return
        logger.info("Stopping sync subsystem")

        # Stop replay task
        if self._replay_task and not self._replay_task.done():
            self._replay_task.cancel()
            try:
                await self._replay_task
            except asyncio.CancelledError:
                pass

        # Stop components in reverse order
        if self._task_reporter:
            await self._task_reporter.stop()
        if self._device_reporter:
            await self._device_reporter.stop()
        if self._push_channel:
            await self._push_channel.stop()
        if self._registration:
            await self._registration.stop_heartbeat()
        if self._client:
            await self._client.stop()

        self._started = False
        logger.info("Sync subsystem stopped")

    async def _replay_loop(self) -> None:
        """Periodically replay queued offline items."""
        while True:
            try:
                await asyncio.sleep(self._replay_interval)
                await self._replay_offline_queue()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Offline queue replay error: %s", e)

    async def _replay_offline_queue(self) -> None:
        """Peek at queued items, replay them, and pop on success."""
        if (
            not self._offline_queue
            or not self._client
            or not self._client.is_registered
        ):
            return

        items = self._offline_queue.peek(limit=10)
        for item in items:
            try:
                payload = json.loads(item.payload)
                if item.item_type == "task_run":
                    from AutoGLM_GUI.sync.schemas import TaskRunReportRequest

                    req = TaskRunReportRequest.model_validate(payload)
                    await self._client.report_task_run(req)
                elif item.item_type == "task_events":
                    from AutoGLM_GUI.sync.schemas import TaskEventBatchRequest

                    req = TaskEventBatchRequest.model_validate(payload)
                    # task_events need a task_run_id; extract from payload
                    task_run_id = payload.get("task_run_id", "")
                    await self._client.report_task_events_batch(task_run_id, req)
                elif item.item_type == "device_report":
                    from AutoGLM_GUI.sync.schemas import DeviceReportRequest

                    req = DeviceReportRequest.model_validate(payload)
                    await self._client.report_devices(req)
                else:
                    logger.warning(
                        "Unknown offline queue item type: %s", item.item_type
                    )
                    self._offline_queue.pop(item.id)
                    continue

                self._offline_queue.pop(item.id)
                logger.debug(
                    "Replayed offline queue item #%d (%s)", item.id, item.item_type
                )
            except ServerUnavailableError:
                logger.debug("Server unavailable during replay, will retry later")
                break
            except Exception as e:
                logger.error("Failed to replay offline queue item #%d: %s", item.id, e)
                self._offline_queue.increment_retry(item.id)

    def get_status(self) -> dict:
        """Get current sync status for frontend display."""
        return {
            "active": self.is_active,
            "connected": self.is_connected,
            "server_url": self._config.server_url,
            "client_id": self._client.client_id if self._client else None,
            "offline_queue_size": self.offline_queue_size,
        }


# Global singleton
sync_manager = SyncManager()
