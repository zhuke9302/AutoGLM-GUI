from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, Callable

from AutoGLM_GUI.sync.schemas import (
    SSEConfigChanged,
    SSEEventType,
    SSEScheduledTaskChanged,
    SSETaskCancel,
    SSETaskDispatch,
    SSEWorkflowChanged,
)

if TYPE_CHECKING:
    from AutoGLM_GUI.sync.client import ServerClient
    from AutoGLM_GUI.sync.sync_pull import SyncPull
    from AutoGLM_GUI.task_manager import TaskManager

logger = logging.getLogger(__name__)


class PushChannel:
    """Subscribes to server SSE stream and dispatches push events."""

    def __init__(
        self,
        client: ServerClient,
        sync_pull: SyncPull,
        task_manager: TaskManager,
        reconnect_max_delay: float = 30.0,
        on_reconnect: Callable[[], Any] | None = None,
    ):
        self._client = client
        self._sync_pull = sync_pull
        self._task_manager = task_manager
        self._reconnect_max_delay = reconnect_max_delay
        self._on_reconnect = on_reconnect
        self._stream_task: asyncio.Task | None = None
        self._connected = False
        self._reconnect_delay: float = 1.0
        # fire_id 去重集合，防止同一个 TASK_DISPATCH 事件被重复执行
        self._processed_fire_ids: set[str] = set()

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def start(self) -> None:
        """Start the SSE stream subscription."""
        if self._stream_task is None or self._stream_task.done():
            self._stream_task = asyncio.create_task(self._stream_loop())

    async def stop(self) -> None:
        """Stop the SSE stream subscription."""
        if self._stream_task and not self._stream_task.done():
            self._stream_task.cancel()
            try:
                await self._stream_task
            except asyncio.CancelledError:
                pass
            self._connected = False

    async def _stream_loop(self) -> None:
        """Main loop: connect to SSE stream, handle events, reconnect on failure."""
        while True:
            try:
                if not self._client.is_registered:
                    await asyncio.sleep(5)
                    continue

                async for event_type, data_str in self._client.events_stream():
                    self._connected = True
                    self._reconnect_delay = 1.0  # Reset on successful connection
                    await self._handle_event(event_type, data_str)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._connected = False
                logger.warning("SSE stream disconnected: %s", e)
                # Exponential backoff reconnect
                logger.info("Reconnecting in %.1fs...", self._reconnect_delay)
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, self._reconnect_max_delay
                )
                # After reconnect, trigger full sync
                try:
                    await self._sync_pull.full_sync()
                except Exception as sync_err:
                    logger.error("Full sync after reconnect failed: %s", sync_err)
                # Notify reconnect callback (e.g., replay offline queue)
                if self._on_reconnect:
                    try:
                        await self._on_reconnect()
                    except Exception as cb_err:
                        logger.error("Reconnect callback failed: %s", cb_err)

    async def _handle_event(self, event_type: str, data_str: str) -> None:
        """Dispatch a single SSE event to the appropriate handler."""
        try:
            data = json.loads(data_str) if data_str else {}
        except json.JSONDecodeError:
            logger.warning("Invalid SSE data JSON: %s", data_str)
            return

        handler = self._get_handler(event_type)
        if handler:
            try:
                await handler(data)
            except Exception as e:
                logger.error("Error handling SSE event %s: %s", event_type, e)
        elif event_type != "ping":
            logger.debug("Unhandled SSE event type: %s", event_type)

    def _get_handler(self, event_type: str) -> Callable[[dict[str, Any]], Any] | None:
        """Map event type to handler method."""
        handlers = {
            SSEEventType.SCHEDULED_TASK_CHANGED: self._on_scheduled_task_changed,
            SSEEventType.WORKFLOW_CHANGED: self._on_workflow_changed,
            SSEEventType.CONFIG_CHANGED: self._on_config_changed,
            SSEEventType.TASK_CANCEL: self._on_task_cancel,
            SSEEventType.TASK_DISPATCH: self._on_task_dispatch,
            SSEEventType.PING: self._on_ping,
        }
        return handlers.get(event_type)

    async def _on_scheduled_task_changed(self, data: dict) -> None:
        """Handle scheduled_task.changed — trigger incremental sync."""
        evt = SSEScheduledTaskChanged.model_validate(data)
        logger.info("SSE: scheduled_task.changed action=%s id=%s", evt.action, evt.id)
        await self._sync_pull.sync_scheduled_tasks(full=False)

    async def _on_workflow_changed(self, data: dict) -> None:
        """Handle workflow.changed — trigger incremental sync."""
        evt = SSEWorkflowChanged.model_validate(data)
        logger.info("SSE: workflow.changed action=%s uuid=%s", evt.action, evt.uuid)
        await self._sync_pull.sync_workflows(full=False)

    async def _on_config_changed(self, data: dict) -> None:
        """Handle config.changed — trigger config sync."""
        evt = SSEConfigChanged.model_validate(data)
        logger.info("SSE: config.changed updated_at=%s", evt.updated_at)
        await self._sync_pull.sync_config()

    async def _on_task_cancel(self, data: dict) -> None:
        """Handle task.cancel — cancel the specified task."""
        evt = SSETaskCancel.model_validate(data)
        logger.info("SSE: task.cancel task_run_id=%s", evt.task_run_id)
        try:
            await self._task_manager.cancel_task(evt.task_run_id)
        except Exception as e:
            logger.error("Failed to cancel task %s: %s", evt.task_run_id, e)

    async def _on_task_dispatch(self, data: dict) -> None:
        """Handle task.dispatch — execute an immediate inspection task."""
        evt = SSETaskDispatch.model_validate(data)

        # fire_id 去重：同一个 TASK_DISPATCH 事件只执行一次
        if evt.fire_id in self._processed_fire_ids:
            logger.info(
                "SSE: task.dispatch duplicate fire_id=%s, skipping",
                evt.fire_id,
            )
            return
        self._processed_fire_ids.add(evt.fire_id)
        # 防止集合无限增长，保留最近 500 条
        if len(self._processed_fire_ids) > 500:
            self._processed_fire_ids = set(
                list(self._processed_fire_ids)[-500:]
            )

        logger.info(
            "SSE: task.dispatch scheduled_task_id=%s fire_id=%s devices=%s",
            evt.scheduled_task_id,
            evt.fire_id,
            evt.device_serialnos,
        )
        try:
            from AutoGLM_GUI.scheduler_manager import scheduler_manager

            task = scheduler_manager.get_task(evt.scheduled_task_id)
            if not task:
                logger.error(
                    "Scheduled task %s not found for dispatch", evt.scheduled_task_id
                )
                return

            from AutoGLM_GUI.workflow_manager import workflow_manager

            workflow = workflow_manager.get_workflow(task.workflow_uuid)
            if not workflow:
                logger.error("Workflow %s not found for dispatch", task.workflow_uuid)
                return

            executor_key = (
                "scheduled_layered_workflow"
                if task.execution_mode == "layered"
                else "scheduled_workflow"
            )

            from AutoGLM_GUI.device_manager import DeviceManager

            device_manager = DeviceManager.get_instance()
            online_devices = {
                dev.serial: dev
                for dev in device_manager.get_devices()
                if dev.state.value == "online"
            }

            for serial in evt.device_serialnos:
                device = online_devices.get(serial)
                if device is None:
                    logger.warning("Device %s offline, skipping dispatch", serial)
                    continue
                await self._task_manager.enqueue_scheduled_task(
                    scheduled_task_id=evt.scheduled_task_id,
                    workflow_uuid=task.workflow_uuid,
                    device_id=device.primary_device_id,
                    device_serial=serial,
                    input_text=workflow["text"],
                    schedule_fire_id=evt.fire_id,
                    executor_key=executor_key,
                )
                logger.info("Dispatched task for device %s", serial)
        except Exception as e:
            logger.error("Failed to dispatch task: %s", e)

    async def _on_ping(self, data: dict) -> None:
        """Handle ping — keep-alive, no action needed."""
        logger.debug("SSE: ping")
