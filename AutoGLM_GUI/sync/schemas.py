from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Group 1: Client Registration & Heartbeat
# ---------------------------------------------------------------------------


class ClientRegisterRequest(BaseModel):
    model_config = ConfigDict()

    hostname: str
    ip: str
    os: str
    version: str


class ClientRegisterResponse(BaseModel):
    model_config = ConfigDict()

    client_id: str
    token: str
    heartbeat_interval_seconds: int = 30


class ClientHeartbeatRequest(BaseModel):
    model_config = ConfigDict()

    timestamp: str
    device_count: int
    running_task_count: int
    status: Literal["healthy", "degraded", "error"]
    error_message: str | None = None


class ClientHeartbeatResponse(BaseModel):
    model_config = ConfigDict()

    ack: bool
    config_changes: bool
    task_changes: bool


# ---------------------------------------------------------------------------
# Group 2: Device Status Report
# ---------------------------------------------------------------------------


class DeviceReportItem(BaseModel):
    model_config = ConfigDict()

    serial: str
    model: str
    connection_type: Literal["usb", "wifi", "remote"]
    status: Literal["online", "offline"]
    display_name: str | None = None
    group_id: str | None = None
    agent_state: str
    agent_model_name: str | None = None


class DeviceReportRequest(BaseModel):
    model_config = ConfigDict()

    timestamp: str
    devices: list[DeviceReportItem]


class DeviceReportResponse(BaseModel):
    model_config = ConfigDict()

    ack: bool


# ---------------------------------------------------------------------------
# Group 3: Scheduled Task Sync
# ---------------------------------------------------------------------------


class ScheduledTaskSyncItem(BaseModel):
    model_config = ConfigDict()

    id: str
    name: str
    workflow_uuid: str
    device_serialnos: list[str]
    device_group_id: str | None = None
    cron_expression: str
    enabled: bool
    execution_mode: Literal["classic", "layered"]
    updated_at: str


class ScheduledTaskSyncResponse(BaseModel):
    model_config = ConfigDict()

    tasks: list[ScheduledTaskSyncItem]
    deleted_ids: list[str]
    server_time: str


class ExecutionReportRequest(BaseModel):
    model_config = ConfigDict()

    fire_id: str
    timestamp: str
    device_serial: str
    task_run_id: str
    status: Literal["succeeded", "failed", "cancelled", "interrupted"]
    error_message: str | None = None
    step_count: int
    duration_ms: int


class ExecutionReportResponse(BaseModel):
    model_config = ConfigDict()

    ack: bool


# ---------------------------------------------------------------------------
# Group 4: Workflow Sync
# ---------------------------------------------------------------------------


class WorkflowSyncItem(BaseModel):
    model_config = ConfigDict()

    uuid: str
    name: str
    text: str
    updated_at: str


class WorkflowSyncResponse(BaseModel):
    model_config = ConfigDict()

    workflows: list[WorkflowSyncItem]
    deleted_uuids: list[str]
    server_time: str


# ---------------------------------------------------------------------------
# Group 5: Model Config Sync
# ---------------------------------------------------------------------------


class ServerConfigResponse(BaseModel):
    model_config = ConfigDict()

    base_url: str | None = None
    model_name: str | None = None
    api_key: str | None = None
    agent_type: str | None = None
    default_max_steps: int | None = None
    updated_at: str


# ---------------------------------------------------------------------------
# Group 6: Task Run Report
# ---------------------------------------------------------------------------


class TaskRunReportRequest(BaseModel):
    model_config = ConfigDict()

    task_run_id: str
    source: Literal["chat", "scheduled"]
    session_id: str | None = None
    scheduled_task_id: str | None = None
    workflow_uuid: str | None = None
    device_serial: str
    status: Literal["succeeded", "failed", "cancelled", "interrupted"]
    input_text: str
    final_message: str | None = None
    error_message: str | None = None
    stop_reason: str | None = None
    trace_id: str | None = None
    step_count: int
    started_at: str
    finished_at: str
    duration_ms: int


class TaskRunReportResponse(BaseModel):
    model_config = ConfigDict()

    ack: bool


class TaskEventBatchItem(BaseModel):
    model_config = ConfigDict()

    seq: int
    event_type: str
    role: str | None = None
    payload: dict
    created_at: str


class TaskEventBatchRequest(BaseModel):
    model_config = ConfigDict()

    events: list[TaskEventBatchItem]


class TaskEventBatchResponse(BaseModel):
    model_config = ConfigDict()

    ack: bool
    last_seq: int


class UploadResponse(BaseModel):
    model_config = ConfigDict()

    url: str
    file_id: str


# ---------------------------------------------------------------------------
# Group 7: SSE Push Events
# ---------------------------------------------------------------------------


class SSEEventType(StrEnum):
    SCHEDULED_TASK_CHANGED = "SCHEDULED_TASK_CHANGED"
    WORKFLOW_CHANGED = "WORKFLOW_CHANGED"
    CONFIG_CHANGED = "CONFIG_CHANGED"
    TASK_CANCEL = "TASK_CANCEL"
    TASK_DISPATCH = "TASK_DISPATCH"
    PING = "PING"


SSEAction = Literal["created", "updated", "deleted"]


class SSEScheduledTaskChanged(BaseModel):
    model_config = ConfigDict()

    action: SSEAction
    id: str
    updated_at: str


class SSEWorkflowChanged(BaseModel):
    model_config = ConfigDict()

    action: SSEAction
    uuid: str
    updated_at: str


class SSEConfigChanged(BaseModel):
    model_config = ConfigDict()

    updated_at: str


class SSETaskCancel(BaseModel):
    model_config = ConfigDict()

    task_run_id: str


class SSETaskDispatch(BaseModel):
    model_config = ConfigDict()

    scheduled_task_id: str
    fire_id: str
    device_serialnos: list[str]


# ---------------------------------------------------------------------------
# Group 8: Task Control
# ---------------------------------------------------------------------------


class TaskRunListItem(BaseModel):
    model_config = ConfigDict()

    task_run_id: str
    device_serial: str
    status: str
    input_text: str
    started_at: str
    step_count: int


class TaskRunListResponse(BaseModel):
    model_config = ConfigDict()

    task_runs: list[TaskRunListItem]


# ---------------------------------------------------------------------------
# Client-side Configuration
# ---------------------------------------------------------------------------


class SyncConfig(BaseModel):
    model_config = ConfigDict()

    server_url: str | None = None
    heartbeat_interval_seconds: int = 30
    offline_queue_capacity: int = 1000
    offline_queue_expire_hours: int = 72
    sse_reconnect_max_delay: float = 30.0
    upload_timeout_seconds: int = 60
    batch_event_size: int = 50
