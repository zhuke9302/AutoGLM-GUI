from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from AutoGLM_GUI.sync.client import ServerClient, ServerUnavailableError
from AutoGLM_GUI.sync.schemas import (
    ScheduledTaskSyncItem,
    ServerConfigResponse,
    WorkflowSyncItem,
)

if TYPE_CHECKING:
    from AutoGLM_GUI.scheduler_manager import SchedulerManager
    from AutoGLM_GUI.workflow_manager import WorkflowManager

from AutoGLM_GUI.config_manager import UnifiedConfigManager
from AutoGLM_GUI.models.scheduled_task import ScheduledTask

logger = logging.getLogger(__name__)


class SyncPull:
    """Pulls data from the server and merges into local managers."""

    def __init__(
        self,
        client: ServerClient,
        scheduler_manager: SchedulerManager,
        workflow_manager: WorkflowManager,
        config_manager: UnifiedConfigManager,
    ):
        self._client = client
        self._scheduler = scheduler_manager
        self._workflows = workflow_manager
        self._config = config_manager
        # Track last sync timestamps for incremental sync
        self._last_scheduled_tasks_sync: str | None = None
        self._last_workflows_sync: str | None = None

    async def full_sync(self) -> None:
        """Perform full sync of all data from server (after registration or SSE reconnect)."""
        logger.info("Starting full sync from server")
        await self.sync_scheduled_tasks(full=True)
        await self.sync_workflows(full=True)
        await self.sync_config()
        logger.info("Full sync completed")

    async def sync_scheduled_tasks(self, full: bool = False) -> None:
        """Pull and merge scheduled tasks from server.

        If full=True, pull all tasks (since=None).
        Otherwise, pull only tasks updated since last sync.
        """
        if not self._client.is_registered:
            return
        try:
            since = None if full else self._last_scheduled_tasks_sync
            resp = await self._client.pull_scheduled_tasks(since=since)

            # Merge updated/created tasks
            for task_item in resp.tasks:
                self._merge_scheduled_task(task_item)

            # Delete removed tasks
            for deleted_id in resp.deleted_ids:
                try:
                    self._scheduler.delete_task(deleted_id)
                    logger.info(
                        "Deleted scheduled task %s (server deletion)", deleted_id
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to delete scheduled task %s: %s", deleted_id, e
                    )

            # Update sync timestamp
            self._last_scheduled_tasks_sync = resp.server_time
            logger.info(
                "Synced %d scheduled tasks, deleted %d",
                len(resp.tasks),
                len(resp.deleted_ids),
            )
        except ServerUnavailableError:
            logger.warning("Server unavailable, skipping scheduled tasks sync")
        except Exception as e:
            logger.error("Failed to sync scheduled tasks: %s", e)

    async def sync_workflows(self, full: bool = False) -> None:
        """Pull and merge workflows from server."""
        if not self._client.is_registered:
            return
        try:
            since = None if full else self._last_workflows_sync
            resp = await self._client.pull_workflows(since=since)

            for wf_item in resp.workflows:
                self._merge_workflow(wf_item)

            for deleted_uuid in resp.deleted_uuids:
                try:
                    self._workflows.delete_workflow(deleted_uuid)
                    logger.info("Deleted workflow %s (server deletion)", deleted_uuid)
                except Exception as e:
                    logger.warning("Failed to delete workflow %s: %s", deleted_uuid, e)

            self._last_workflows_sync = resp.server_time
            logger.info(
                "Synced %d workflows, deleted %d",
                len(resp.workflows),
                len(resp.deleted_uuids),
            )
        except ServerUnavailableError:
            logger.warning("Server unavailable, skipping workflows sync")
        except Exception as e:
            logger.error("Failed to sync workflows: %s", e)

    async def sync_config(self) -> None:
        """Pull model config from server and apply as a new config layer."""
        if not self._client.is_registered:
            return
        try:
            resp = await self._client.pull_config()
            self._apply_server_config(resp)
            logger.info("Synced server config")
        except ServerUnavailableError:
            logger.warning("Server unavailable, skipping config sync")
        except Exception as e:
            logger.error("Failed to sync config: %s", e)

    def _merge_scheduled_task(self, item: ScheduledTaskSyncItem) -> None:
        """Merge a single scheduled task from server into local SchedulerManager."""
        try:
            existing = self._scheduler.get_task(item.id)
            if existing:
                # Update existing task — update_task uses **kwargs and only
                # applies non-None values, so it is safe to pass all fields.
                self._scheduler.update_task(
                    item.id,
                    name=item.name,
                    workflow_uuid=item.workflow_uuid,
                    device_serialnos=item.device_serialnos,
                    device_group_id=item.device_group_id,
                    cron_expression=item.cron_expression,
                    enabled=item.enabled,
                    execution_mode=item.execution_mode,
                )
                logger.debug("Updated scheduled task %s", item.id)
            else:
                # Create new task with the server's ID.
                # SchedulerManager.create_task() auto-generates an ID, so we
                # construct a ScheduledTask directly and insert it.
                task = ScheduledTask(
                    id=item.id,
                    name=item.name,
                    workflow_uuid=item.workflow_uuid,
                    device_serialnos=item.device_serialnos,
                    device_group_id=item.device_group_id,
                    cron_expression=item.cron_expression,
                    enabled=item.enabled,
                    execution_mode=item.execution_mode,
                )
                self._scheduler._tasks[task.id] = task  # noqa: SLF001
                self._scheduler._save_tasks()  # noqa: SLF001
                if task.enabled:
                    self._scheduler._add_job(task)  # noqa: SLF001
                logger.debug("Created scheduled task %s from server", item.id)
        except Exception as e:
            logger.error("Failed to merge scheduled task %s: %s", item.id, e)

    def _merge_workflow(self, item: WorkflowSyncItem) -> None:
        """Merge a single workflow from server into local WorkflowManager."""
        try:
            existing = self._workflows.get_workflow(item.uuid)
            if existing:
                self._workflows.update_workflow(
                    item.uuid, name=item.name, text=item.text
                )
                logger.debug("Updated workflow %s", item.uuid)
            else:
                # WorkflowManager.create_workflow() auto-generates a UUID, so
                # we directly construct the record and persist it.
                workflows = self._workflows._load_workflows()  # noqa: SLF001
                new_workflow = {"uuid": item.uuid, "name": item.name, "text": item.text}
                workflows.append(new_workflow)
                self._workflows._save_workflows(workflows)  # noqa: SLF001
                logger.debug("Created workflow %s from server", item.uuid)
        except Exception as e:
            logger.error("Failed to merge workflow %s: %s", item.uuid, e)

    def _apply_server_config(self, config: ServerConfigResponse) -> None:
        """Apply server config as a new priority layer in UnifiedConfigManager.

        Priority: CLI > ENV > Server > Local file > Default
        """
        try:
            # Build a dict of non-None config values from server
            server_values: dict[str, object] = {}
            if config.base_url is not None:
                server_values["base_url"] = config.base_url
            if config.model_name is not None:
                server_values["model_name"] = config.model_name
            if config.api_key is not None:
                server_values["api_key"] = config.api_key
            if config.agent_type is not None:
                server_values["agent_type"] = config.agent_type
            if config.default_max_steps is not None:
                server_values["default_max_steps"] = config.default_max_steps

            if server_values:
                self._config.set_server_config(server_values)
                logger.debug("Applied server config: %s", list(server_values.keys()))
        except Exception as e:
            logger.error("Failed to apply server config: %s", e)
