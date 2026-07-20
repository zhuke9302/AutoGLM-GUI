from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel


class SyncBaseModel(BaseModel):
    """Base model with camelCase alias support for server compatibility.

    Field names use snake_case (Python convention), but the server uses
    camelCase (Java/Jackson convention). This base model configures
    ``alias_generator=to_camel`` and ``populate_by_name=True`` so that
    both snake_case and camelCase keys are accepted on input, and
    ``model_dump(by_alias=True)`` produces camelCase for server requests.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ---------------------------------------------------------------------------
# Group 1: Client Registration & Heartbeat
# ---------------------------------------------------------------------------


class ClientRegisterRequest(SyncBaseModel):
    hostname: str
    ip: str
    os: str
    version: str


class ClientRegisterResponse(SyncBaseModel):
    client_id: str
    token: str
    heartbeat_interval_seconds: int = 30


class ClientHeartbeatRequest(SyncBaseModel):
    timestamp: str
    device_count: int
    running_task_count: int
    status: Literal["healthy", "degraded", "error"]
    error_message: str | None = None


class ClientHeartbeatResponse(SyncBaseModel):
    ack: bool
    config_changes: bool
    task_changes: bool


# ---------------------------------------------------------------------------
# Group 2: Device Status Report
# ---------------------------------------------------------------------------


class DeviceReportItem(SyncBaseModel):
    serial: str
    model: str
    connection_type: Literal["usb", "wifi", "remote"]
    status: Literal["online", "offline"]
    display_name: str | None = None
    group_id: str | None = None
    agent_state: str
    agent_model_name: str | None = None


class DeviceReportRequest(SyncBaseModel):
    timestamp: str
    devices: list[DeviceReportItem]


class DeviceReportResponse(SyncBaseModel):
    ack: bool


# ---------------------------------------------------------------------------
# Group 3: Scheduled Task Sync
# ---------------------------------------------------------------------------


class ScheduledTaskSyncItem(SyncBaseModel):
    id: str
    name: str
    workflow_uuid: str
    device_serialnos: list[str]
    device_group_id: str | None = None
    cron_expression: str
    enabled: bool
    execution_mode: Literal["classic", "layered"]
    updated_at: str


class ScheduledTaskSyncResponse(SyncBaseModel):
    tasks: list[ScheduledTaskSyncItem]
    deleted_ids: list[str]
    server_time: str


class ExecutionReportRequest(SyncBaseModel):
    fire_id: str
    timestamp: str
    device_serial: str
    task_run_id: str
    status: Literal["succeeded", "failed", "cancelled", "interrupted"]
    error_message: str | None = None
    step_count: int
    duration_ms: int


class ExecutionReportResponse(SyncBaseModel):
    ack: bool


# ---------------------------------------------------------------------------
# Group 4: Workflow Sync
# ---------------------------------------------------------------------------


class WorkflowStepSyncItem(SyncBaseModel):
    step_order: int
    # 旧 workflow 步骤可能未设置 step_type（数据库字段为 NULL），
    # 默认按 action 处理，避免反序列化失败导致整个 workflow 同步中断。
    step_type: Literal["action", "assertion"] = "action"
    step_name: str

    @field_validator("step_type", mode="before")
    @classmethod
    def _normalize_step_type(cls, v):
        # 后端对历史数据可能返回 null/空字符串，统一降级为 action
        if v is None or v == "":
            return "action"
        return v


class WorkflowSyncItem(SyncBaseModel):
    uuid: str
    name: str
    text: str
    steps: list[WorkflowStepSyncItem] = Field(default_factory=list)
    updated_at: str


class WorkflowSyncResponse(SyncBaseModel):
    workflows: list[WorkflowSyncItem]
    deleted_uuids: list[str]
    server_time: str


# ---------------------------------------------------------------------------
# Group 5: Model Config Sync
# ---------------------------------------------------------------------------


class ServerConfigResponse(SyncBaseModel):
    base_url: str | None = None
    model_name: str | None = None
    api_key: str | None = None
    agent_type: str | None = None
    default_max_steps: int | None = None
    updated_at: str | None = None
    # 决策模型
    decision_base_url: str | None = None
    decision_model_name: str | None = None
    decision_api_key: str | None = None


# ---------------------------------------------------------------------------
# Group 6: Task Run Report
# ---------------------------------------------------------------------------


class TaskRunReportRequest(SyncBaseModel):
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
    business_status: Literal["ok", "abnormal"] | None = None


class TaskRunReportResponse(SyncBaseModel):
    ack: bool


class TaskEventBatchItem(SyncBaseModel):
    seq: int
    event_type: str
    role: str | None = None
    payload: dict
    created_at: str


class TaskEventBatchRequest(SyncBaseModel):
    events: list[TaskEventBatchItem]


class TaskEventBatchResponse(SyncBaseModel):
    ack: bool
    last_seq: int


class UploadResponse(SyncBaseModel):
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


class SSEScheduledTaskChanged(SyncBaseModel):
    action: SSEAction
    id: str
    updated_at: str


class SSEWorkflowChanged(SyncBaseModel):
    action: SSEAction
    uuid: str
    updated_at: str


class SSEConfigChanged(SyncBaseModel):
    updated_at: str


class SSETaskCancel(SyncBaseModel):
    task_run_id: str


class SSETaskDispatch(SyncBaseModel):
    scheduled_task_id: str
    fire_id: str
    device_serialnos: list[str]


# ---------------------------------------------------------------------------
# Group 8: Task Control
# ---------------------------------------------------------------------------


class TaskRunListItem(SyncBaseModel):
    task_run_id: str
    device_serial: str
    status: str
    input_text: str
    started_at: str
    step_count: int


class TaskRunListResponse(SyncBaseModel):
    task_runs: list[TaskRunListItem]


# ---------------------------------------------------------------------------
# Client-side Configuration
# ---------------------------------------------------------------------------


class SyncConfig(SyncBaseModel):
    server_url: str | None = None
    heartbeat_interval_seconds: int = 30
    offline_queue_capacity: int = 1000
    offline_queue_expire_hours: int = 72
    sse_reconnect_max_delay: float = 30.0
    upload_timeout_seconds: int = 60
    batch_event_size: int = 50
