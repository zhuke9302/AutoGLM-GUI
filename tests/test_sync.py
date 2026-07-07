"""Unit tests for the sync module (schemas, offline_queue, client, push_channel)."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from AutoGLM_GUI.sync.client import ServerClient, ServerUnavailableError
from AutoGLM_GUI.sync.offline_queue import OfflineQueue, QueuedItem
from AutoGLM_GUI.sync.push_channel import PushChannel
from AutoGLM_GUI.sync.schemas import (
    ClientHeartbeatRequest,
    ClientHeartbeatResponse,
    ClientRegisterRequest,
    ClientRegisterResponse,
    DeviceReportItem,
    DeviceReportRequest,
    DeviceReportResponse,
    ExecutionReportRequest,
    ExecutionReportResponse,
    ScheduledTaskSyncItem,
    ScheduledTaskSyncResponse,
    ServerConfigResponse,
    SSEConfigChanged,
    SSEEventType,
    SSEScheduledTaskChanged,
    SSETaskCancel,
    SSETaskDispatch,
    SSEWorkflowChanged,
    SyncConfig,
    TaskEventBatchItem,
    TaskEventBatchRequest,
    TaskEventBatchResponse,
    TaskRunListItem,
    TaskRunListResponse,
    TaskRunReportRequest,
    TaskRunReportResponse,
    UploadResponse,
    WorkflowSyncItem,
    WorkflowSyncResponse,
)


# ============================================================================
# 1. Schema tests
# ============================================================================


class TestSchemas:
    """Tests for Pydantic schema models."""

    def test_client_register_request_valid(self) -> None:
        req = ClientRegisterRequest(
            hostname="myhost",
            ip="10.0.0.1",
            os="linux",
            version="1.0.0",
        )
        assert req.hostname == "myhost"
        assert req.ip == "10.0.0.1"

    def test_client_register_request_missing_fields(self) -> None:
        with pytest.raises(ValidationError):
            ClientRegisterRequest()  # type: ignore[call-arg]

    def test_client_register_request_missing_hostname(self) -> None:
        with pytest.raises(ValidationError):
            ClientRegisterRequest(
                ip="10.0.0.1",
                os="linux",
                version="1.0.0",
            )  # type: ignore[call-arg]

    def test_client_heartbeat_request_valid_statuses(self) -> None:
        for status in ("healthy", "degraded", "error"):
            req = ClientHeartbeatRequest(
                timestamp="2025-01-01T00:00:00Z",
                device_count=1,
                running_task_count=0,
                status=status,
            )
            assert req.status == status

    def test_client_heartbeat_request_invalid_status(self) -> None:
        with pytest.raises(ValidationError):
            ClientHeartbeatRequest(
                timestamp="2025-01-01T00:00:00Z",
                device_count=1,
                running_task_count=0,
                status="unknown",
            )

    def test_client_heartbeat_request_optional_error_message(self) -> None:
        req = ClientHeartbeatRequest(
            timestamp="2025-01-01T00:00:00Z",
            device_count=0,
            running_task_count=0,
            status="healthy",
        )
        assert req.error_message is None

        req2 = ClientHeartbeatRequest(
            timestamp="2025-01-01T00:00:00Z",
            device_count=0,
            running_task_count=0,
            status="error",
            error_message="something broke",
        )
        assert req2.error_message == "something broke"

    def test_sync_config_defaults(self) -> None:
        cfg = SyncConfig()
        assert cfg.server_url is None
        assert cfg.heartbeat_interval_seconds == 30
        assert cfg.offline_queue_capacity == 1000
        assert cfg.offline_queue_expire_hours == 72
        assert cfg.sse_reconnect_max_delay == 30.0
        assert cfg.upload_timeout_seconds == 60
        assert cfg.batch_event_size == 50

    def test_sse_event_type_values(self) -> None:
        assert SSEEventType.SCHEDULED_TASK_CHANGED == "SCHEDULED_TASK_CHANGED"
        assert SSEEventType.WORKFLOW_CHANGED == "WORKFLOW_CHANGED"
        assert SSEEventType.CONFIG_CHANGED == "CONFIG_CHANGED"
        assert SSEEventType.TASK_CANCEL == "TASK_CANCEL"
        assert SSEEventType.TASK_DISPATCH == "TASK_DISPATCH"
        assert SSEEventType.PING == "PING"
        assert len(SSEEventType) == 6

    def test_all_models_instantiate_with_valid_data(self) -> None:
        """Smoke test: every Pydantic model in schemas can be instantiated."""
        ClientRegisterResponse(
            client_id="c1", token="t1", heartbeat_interval_seconds=30
        )
        ClientHeartbeatResponse(
            ack=True, config_changes=False, task_changes=False
        )
        DeviceReportItem(
            serial="s1", model="Pixel", connection_type="usb", status="online", agent_state="idle"
        )
        DeviceReportRequest(timestamp="2025-01-01T00:00:00Z", devices=[])
        DeviceReportResponse(ack=True)
        ScheduledTaskSyncItem(
            id="st1",
            name="task",
            workflow_uuid="w1",
            device_serialnos=["s1"],
            cron_expression="0 * * * *",
            enabled=True,
            execution_mode="classic",
            updated_at="2025-01-01T00:00:00Z",
        )
        ScheduledTaskSyncResponse(tasks=[], deleted_ids=[], server_time="2025-01-01T00:00:00Z")
        ExecutionReportRequest(
            fire_id="f1",
            timestamp="2025-01-01T00:00:00Z",
            device_serial="s1",
            task_run_id="tr1",
            status="succeeded",
            step_count=1,
            duration_ms=100,
        )
        ExecutionReportResponse(ack=True)
        WorkflowSyncItem(uuid="w1", name="wf", text="do stuff", updated_at="2025-01-01T00:00:00Z")
        WorkflowSyncResponse(workflows=[], deleted_uuids=[], server_time="2025-01-01T00:00:00Z")
        ServerConfigResponse(updated_at="2025-01-01T00:00:00Z")
        TaskRunReportRequest(
            task_run_id="tr1",
            source="chat",
            device_serial="s1",
            status="succeeded",
            input_text="hello",
            step_count=1,
            started_at="2025-01-01T00:00:00Z",
            finished_at="2025-01-01T00:01:00Z",
            duration_ms=60000,
        )
        TaskRunReportResponse(ack=True)
        TaskEventBatchItem(seq=1, event_type="step", payload={}, created_at="2025-01-01T00:00:00Z")
        TaskEventBatchRequest(events=[])
        TaskEventBatchResponse(ack=True, last_seq=0)
        UploadResponse(url="https://example.com/f", file_id="f1")
        SSEScheduledTaskChanged(action="created", id="st1", updated_at="2025-01-01T00:00:00Z")
        SSEWorkflowChanged(action="updated", uuid="w1", updated_at="2025-01-01T00:00:00Z")
        SSEConfigChanged(updated_at="2025-01-01T00:00:00Z")
        SSETaskCancel(task_run_id="tr1")
        SSETaskDispatch(
            scheduled_task_id="st1", fire_id="f1", device_serialnos=["s1"]
        )
        TaskRunListItem(
            task_run_id="tr1",
            device_serial="s1",
            status="running",
            input_text="hello",
            started_at="2025-01-01T00:00:00Z",
            step_count=1,
        )
        TaskRunListResponse(task_runs=[])


# ============================================================================
# 2. OfflineQueue tests
# ============================================================================


class TestOfflineQueue:
    """Tests for the SQLite-backed offline queue."""

    def test_push_adds_and_returns_id(self, tmp_path: Path) -> None:
        q = OfflineQueue(db_path=tmp_path / "q.db", capacity=10, expire_hours=72)
        item_id = q.push("task_run", {"key": "value"})
        assert item_id is not None
        assert item_id == 1

    def test_peek_returns_items_in_order(self, tmp_path: Path) -> None:
        q = OfflineQueue(db_path=tmp_path / "q.db", capacity=10, expire_hours=72)
        q.push("task_run", {"order": 1})
        q.push("task_run", {"order": 2})
        items = q.peek(limit=10)
        assert len(items) == 2
        assert json.loads(items[0].payload)["order"] == 1
        assert json.loads(items[1].payload)["order"] == 2

    def test_pop_removes_item(self, tmp_path: Path) -> None:
        q = OfflineQueue(db_path=tmp_path / "q.db", capacity=10, expire_hours=72)
        item_id = q.push("task_run", {"key": "val"})
        assert q.size() == 1
        result = q.pop(item_id)  # type: ignore[arg-type]
        assert result is True
        assert q.size() == 0

    def test_size_returns_correct_count(self, tmp_path: Path) -> None:
        q = OfflineQueue(db_path=tmp_path / "q.db", capacity=10, expire_hours=72)
        assert q.size() == 0
        q.push("task_run", {"a": 1})
        assert q.size() == 1
        q.push("task_run", {"b": 2})
        assert q.size() == 2

    def test_capacity_limit_returns_none(self, tmp_path: Path) -> None:
        q = OfflineQueue(db_path=tmp_path / "q.db", capacity=2, expire_hours=72)
        assert q.push("task_run", {"a": 1}) is not None
        assert q.push("task_run", {"b": 2}) is not None
        # At capacity — next push should return None
        assert q.push("task_run", {"c": 3}) is None

    def test_cleanup_expired_removes_old_items(self, tmp_path: Path) -> None:
        q = OfflineQueue(db_path=tmp_path / "q.db", capacity=100, expire_hours=1)
        # Insert an item with an old timestamp directly into the DB
        conn = q._get_conn()
        try:
            old_time = time.time() - 7200  # 2 hours ago
            conn.execute(
                "INSERT INTO queue (item_type, payload, created_at, retry_count) VALUES (?, ?, ?, 0)",
                ("task_run", '{"old": true}', old_time),
            )
            conn.commit()
        finally:
            conn.close()

        # Insert a fresh item via the public API
        q.push("task_run", {"fresh": True})

        assert q.size() == 2
        removed = q.cleanup_expired()
        assert removed == 1
        assert q.size() == 1
        items = q.peek(limit=10)
        assert json.loads(items[0].payload) == {"fresh": True}

    def test_clear_removes_all_items(self, tmp_path: Path) -> None:
        q = OfflineQueue(db_path=tmp_path / "q.db", capacity=10, expire_hours=72)
        q.push("task_run", {"a": 1})
        q.push("task_run", {"b": 2})
        assert q.size() == 2
        q.clear()
        assert q.size() == 0


# ============================================================================
# 3. ServerClient tests (mock HTTP)
# ============================================================================


class TestServerClient:
    """Tests for the ServerClient HTTP client using mocked httpx."""

    def _make_client(self) -> ServerClient:
        return ServerClient(server_url="http://localhost:9999", max_retries=2, retry_delay=0.01)

    def test_register_sends_correct_request_and_stores_credentials(self) -> None:
        async def scenario() -> None:
            client = self._make_client()
            await client.start()

            mock_response = MagicMock()
            mock_response.json.return_value = {
                "client_id": "c-123",
                "token": "tok-abc",
                "heartbeat_interval_seconds": 15,
            }
            mock_response.raise_for_status = MagicMock()

            with patch.object(client._client, "request", return_value=mock_response) as mock_req:
                req = ClientRegisterRequest(
                    hostname="h", ip="1.2.3.4", os="linux", version="1.0"
                )
                result = await client.register(req)

                mock_req.assert_called_once()
                call_kwargs = mock_req.call_args
                assert call_kwargs[0][0] == "POST"
                assert call_kwargs[0][1] == "/api/v1/clients/register"

                # _request converts `json=` to `content=` (with optional gzip),
                # so inspect the raw body bytes instead.
                body_bytes = call_kwargs[1]["content"]
                import json as _json

                body = _json.loads(body_bytes)
                assert body["hostname"] == "h"
                assert body["ip"] == "1.2.3.4"
                assert "capabilities" not in body

            assert result.client_id == "c-123"
            assert result.token == "tok-abc"
            assert client.client_id == "c-123"
            assert client.is_registered
            assert client._token == "tok-abc"

            await client.stop()

        asyncio.run(scenario())

    def test_heartbeat_sends_correct_request_with_auth(self) -> None:
        async def scenario() -> None:
            client = self._make_client()
            await client.start()
            # Simulate registration
            client._client_id = "c-123"
            client._set_auth("tok-abc")

            mock_response = MagicMock()
            mock_response.json.return_value = {
                "ack": True,
                "config_changes": False,
                "task_changes": False,
            }
            mock_response.raise_for_status = MagicMock()

            with patch.object(client._client, "request", return_value=mock_response) as mock_req:
                req = ClientHeartbeatRequest(
                    timestamp="2025-01-01T00:00:00Z",
                    device_count=2,
                    running_task_count=1,
                    status="healthy",
                )
                result = await client.heartbeat(req)

                mock_req.assert_called_once()
                call_kwargs = mock_req.call_args
                assert call_kwargs[0][0] == "POST"
                assert call_kwargs[0][1] == "/api/v1/clients/c-123/heartbeat"

            assert result.ack is True
            await client.stop()

        asyncio.run(scenario())

    def test_request_retries_on_connection_error(self) -> None:
        async def scenario() -> None:
            import httpx

            client = self._make_client()
            client._max_retries = 2
            client._retry_delay = 0.01
            await client.start()

            call_count = 0

            async def failing_request(*args: object, **kwargs: object) -> None:
                nonlocal call_count
                call_count += 1
                raise httpx.ConnectError("connection refused")

            with patch.object(client._client, "request", side_effect=failing_request):
                with pytest.raises(ServerUnavailableError):
                    await client._request("GET", "/test")

            assert call_count == 2  # max_retries=2
            await client.stop()

        asyncio.run(scenario())

    def test_require_registered_raises_when_not_registered(self) -> None:
        client = self._make_client()
        assert not client.is_registered
        with pytest.raises(RuntimeError, match="not registered"):
            client._require_registered()


# ============================================================================
# 4. PushChannel tests
# ============================================================================


class TestPushChannel:
    """Tests for the PushChannel SSE event dispatcher."""

    def _make_channel(self) -> tuple[PushChannel, MagicMock, MagicMock, MagicMock]:
        mock_client = MagicMock(spec=ServerClient)
        mock_sync_pull = MagicMock()
        mock_sync_pull.sync_scheduled_tasks = AsyncMock()
        mock_sync_pull.sync_workflows = AsyncMock()
        mock_sync_pull.sync_config = AsyncMock()
        mock_sync_pull.full_sync = AsyncMock()
        mock_task_manager = MagicMock()
        mock_task_manager.cancel_task = AsyncMock()
        ch = PushChannel(
            client=mock_client,
            sync_pull=mock_sync_pull,
            task_manager=mock_task_manager,
        )
        return ch, mock_sync_pull, mock_task_manager, mock_client

    def test_handle_event_dispatches_scheduled_task_changed(self) -> None:
        async def scenario() -> None:
            ch, mock_sync_pull, _, _ = self._make_channel()
            data = json.dumps({
                "action": "updated",
                "id": "st-1",
                "updated_at": "2025-01-01T00:00:00Z",
            })
            await ch._handle_event(SSEEventType.SCHEDULED_TASK_CHANGED, data)
            mock_sync_pull.sync_scheduled_tasks.assert_awaited_once_with(full=False)

        asyncio.run(scenario())

    def test_handle_event_dispatches_workflow_changed(self) -> None:
        async def scenario() -> None:
            ch, mock_sync_pull, _, _ = self._make_channel()
            data = json.dumps({
                "action": "created",
                "uuid": "w-1",
                "updated_at": "2025-01-01T00:00:00Z",
            })
            await ch._handle_event(SSEEventType.WORKFLOW_CHANGED, data)
            mock_sync_pull.sync_workflows.assert_awaited_once_with(full=False)

        asyncio.run(scenario())

    def test_handle_event_dispatches_config_changed(self) -> None:
        async def scenario() -> None:
            ch, mock_sync_pull, _, _ = self._make_channel()
            data = json.dumps({"updated_at": "2025-01-01T00:00:00Z"})
            await ch._handle_event(SSEEventType.CONFIG_CHANGED, data)
            mock_sync_pull.sync_config.assert_awaited_once()

        asyncio.run(scenario())

    def test_on_scheduled_task_changed_calls_sync_pull(self) -> None:
        async def scenario() -> None:
            ch, mock_sync_pull, _, _ = self._make_channel()
            await ch._on_scheduled_task_changed({
                "action": "updated",
                "id": "st-1",
                "updated_at": "2025-01-01T00:00:00Z",
            })
            mock_sync_pull.sync_scheduled_tasks.assert_awaited_once_with(full=False)

        asyncio.run(scenario())

    def test_on_task_cancel_calls_task_manager(self) -> None:
        async def scenario() -> None:
            ch, _, mock_task_manager, _ = self._make_channel()
            await ch._on_task_cancel({"task_run_id": "tr-1"})
            mock_task_manager.cancel_task.assert_awaited_once_with("tr-1")

        asyncio.run(scenario())

    def test_on_ping_does_nothing(self) -> None:
        async def scenario() -> None:
            ch, mock_sync_pull, mock_task_manager, _ = self._make_channel()
            await ch._on_ping({})
            mock_sync_pull.sync_scheduled_tasks.assert_not_awaited()
            mock_sync_pull.sync_workflows.assert_not_awaited()
            mock_sync_pull.sync_config.assert_not_awaited()
            mock_task_manager.cancel_task.assert_not_awaited()

        asyncio.run(scenario())

    def test_handle_event_with_invalid_json_is_ignored(self) -> None:
        async def scenario() -> None:
            ch, mock_sync_pull, _, _ = self._make_channel()
            # Should not raise, just log a warning
            await ch._handle_event(SSEEventType.SCHEDULED_TASK_CHANGED, "not-json")
            mock_sync_pull.sync_scheduled_tasks.assert_not_awaited()

        asyncio.run(scenario())

    def test_handle_event_with_unknown_type_does_nothing(self) -> None:
        async def scenario() -> None:
            ch, mock_sync_pull, _, _ = self._make_channel()
            await ch._handle_event("UNKNOWN_EVENT", "{}")
            mock_sync_pull.sync_scheduled_tasks.assert_not_awaited()

        asyncio.run(scenario())

    def test_get_handler_returns_correct_mappings(self) -> None:
        ch, _, _, _ = self._make_channel()
        # Bound methods create new objects on each attribute access, so compare __func__
        handler = ch._get_handler(SSEEventType.SCHEDULED_TASK_CHANGED)
        assert handler is not None
        assert handler.__func__ is ch._on_scheduled_task_changed.__func__

        handler = ch._get_handler(SSEEventType.WORKFLOW_CHANGED)
        assert handler is not None
        assert handler.__func__ is ch._on_workflow_changed.__func__

        handler = ch._get_handler(SSEEventType.CONFIG_CHANGED)
        assert handler is not None
        assert handler.__func__ is ch._on_config_changed.__func__

        handler = ch._get_handler(SSEEventType.TASK_CANCEL)
        assert handler is not None
        assert handler.__func__ is ch._on_task_cancel.__func__

        handler = ch._get_handler(SSEEventType.TASK_DISPATCH)
        assert handler is not None
        assert handler.__func__ is ch._on_task_dispatch.__func__

        handler = ch._get_handler(SSEEventType.PING)
        assert handler is not None
        assert handler.__func__ is ch._on_ping.__func__

        assert ch._get_handler("NONEXISTENT") is None
