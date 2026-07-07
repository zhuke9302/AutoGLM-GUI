from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from AutoGLM_GUI.sync.client import ServerClient, ServerUnavailableError
from AutoGLM_GUI.sync.schemas import (
    TaskEventBatchItem,
    TaskEventBatchRequest,
    TaskRunReportRequest,
)

if TYPE_CHECKING:
    from AutoGLM_GUI.sync.offline_queue import OfflineQueue
    from AutoGLM_GUI.task_manager import TaskManager
    from AutoGLM_GUI.task_store import TaskStore

logger = logging.getLogger(__name__)

# Maximum events per batch request
DEFAULT_BATCH_SIZE = 50

TERMINAL_STATUSES = frozenset({"SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED"})


class TaskReporter:
    """Reports task execution results and events to the server."""

    def __init__(
        self,
        client: ServerClient,
        task_store: TaskStore,
        task_manager: TaskManager,
        batch_size: int = DEFAULT_BATCH_SIZE,
        offline_queue: OfflineQueue | None = None,
    ):
        self._client = client
        self._task_store = task_store
        self._task_manager = task_manager
        self._batch_size = batch_size
        self._offline_queue = offline_queue
        self._reported_tasks: set[str] = set()
        self._poll_task: asyncio.Task | None = None
        self._poll_interval: float = 5.0

    async def start(self) -> None:
        """Start monitoring task completions."""
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        """Stop monitoring."""
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

    async def report_task_run(self, task_id: str) -> bool:
        """Report a completed task run to the server.

        Returns True if report was successful.
        """
        if not self._client.is_registered:
            return False
        try:
            task_run = await asyncio.to_thread(self._task_store.get_task, task_id)
            if not task_run:
                logger.warning("Task run %s not found in local store", task_id)
                return False

            status = task_run["status"]
            if status not in TERMINAL_STATUSES:
                return False

            source = task_run["source"]
            if source not in ("chat", "scheduled"):
                source = "chat"

            req = TaskRunReportRequest(
                task_run_id=task_run["id"],
                source=source,
                session_id=task_run.get("session_id"),
                scheduled_task_id=task_run.get("scheduled_task_id"),
                workflow_uuid=task_run.get("workflow_uuid"),
                device_serial=task_run.get("device_serial", ""),
                status=status.lower(),
                input_text=task_run.get("input_text", ""),
                final_message=task_run.get("final_message"),
                error_message=task_run.get("error_message"),
                stop_reason=task_run.get("stop_reason"),
                trace_id=task_run.get("trace_id"),
                step_count=task_run.get("step_count", 0) or 0,
                started_at=task_run.get("started_at", ""),
                finished_at=task_run.get("finished_at", ""),
                duration_ms=self._calc_duration_ms(task_run),
            )

            await self._client.report_task_run(req)
            self._reported_tasks.add(task_id)
            logger.info("Reported task run %s (status=%s)", task_id, status)
            return True
        except ServerUnavailableError:
            logger.warning("Server unavailable, queuing task run report for later")
            if self._offline_queue:
                self._offline_queue.push("task_run", req.model_dump())
            return False
        except Exception as e:
            logger.error("Failed to report task run %s: %s", task_id, e)
            return False

    async def report_task_events(self, task_id: str) -> bool:
        """Report all events for a task run in batches.

        Returns True if all events were reported successfully.
        """
        if not self._client.is_registered:
            return False
        try:
            events = await asyncio.to_thread(self._task_store.list_task_events, task_id)
            if not events:
                return True

            all_success = True
            for i in range(0, len(events), self._batch_size):
                batch = events[i : i + self._batch_size]
                items = []
                for evt in batch:
                    item = TaskEventBatchItem(
                        seq=evt["seq"],
                        event_type=evt["event_type"],
                        role=evt.get("role"),
                        payload=evt["payload"]
                        if isinstance(evt.get("payload"), dict)
                        else {},
                        created_at=evt.get("created_at", ""),
                    )
                    items.append(item)

                req = TaskEventBatchRequest(events=items)
                try:
                    resp = await self._client.report_task_events_batch(task_id, req)
                    logger.debug(
                        "Reported batch of %d events for task %s (last_seq=%d)",
                        len(items),
                        task_id,
                        resp.last_seq,
                    )
                except ServerUnavailableError:
                    logger.warning(
                        "Server unavailable, queuing events report for later"
                    )
                    if self._offline_queue:
                        self._offline_queue.push("task_events", req.model_dump())
                    all_success = False
                    break
                except Exception as e:
                    logger.error(
                        "Failed to report events batch for task %s: %s", task_id, e
                    )
                    all_success = False
                    break

            return all_success
        except Exception as e:
            logger.error("Failed to report events for task %s: %s", task_id, e)
            return False

    async def upload_screenshot(
        self, image_data: bytes, task_id: str, filename: str = "screenshot.png"
    ) -> str | None:
        """Upload a screenshot to the server and return the URL.

        Returns the URL if successful, None otherwise.
        """
        if not self._client.is_registered:
            return None
        try:
            resp = await self._client.upload_file(
                file_data=image_data,
                filename=filename,
                task_run_id=task_id,
                category="screenshot",
                mime_type="image/png",
            )
            logger.debug("Uploaded screenshot for task %s: %s", task_id, resp.url)
            return resp.url
        except ServerUnavailableError:
            logger.warning("Server unavailable, cannot upload screenshot")
            return None
        except Exception as e:
            logger.error("Failed to upload screenshot for task %s: %s", task_id, e)
            return None

    async def _poll_loop(self) -> None:
        """Periodically check for completed tasks and report them."""
        while True:
            try:
                await asyncio.sleep(self._poll_interval)
                await self._check_and_report_completed_tasks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Task reporter poll error: %s", e)

    async def _check_and_report_completed_tasks(self) -> None:
        """Find recently completed tasks and report them."""
        if not self._client.is_registered:
            return
        try:
            recent_tasks = await asyncio.to_thread(
                self._task_store.list_recent_terminal_tasks, limit=10
            )
            for task_run in recent_tasks:
                task_id = task_run["id"]
                if task_id not in self._reported_tasks:
                    success = await self.report_task_run(task_id)
                    if success:
                        await self.report_task_events(task_id)
        except Exception as e:
            logger.error("Error checking completed tasks: %s", e)

    @staticmethod
    def _calc_duration_ms(task_run: dict) -> int:
        """Calculate task duration in milliseconds from ISO string timestamps."""
        started_at = task_run.get("started_at")
        finished_at = task_run.get("finished_at")
        if started_at and finished_at:
            try:
                start = datetime.fromisoformat(started_at)
                finish = datetime.fromisoformat(finished_at)
                return int((finish - start).total_seconds() * 1000)
            except (ValueError, TypeError):
                return 0
        return 0
