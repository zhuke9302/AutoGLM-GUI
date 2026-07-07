from __future__ import annotations

import asyncio
import gzip
import json
import logging
from typing import Any, AsyncGenerator

import httpx

from AutoGLM_GUI.sync.schemas import (
    ClientHeartbeatRequest,
    ClientHeartbeatResponse,
    ClientRegisterRequest,
    ClientRegisterResponse,
    DeviceReportRequest,
    DeviceReportResponse,
    ExecutionReportRequest,
    ExecutionReportResponse,
    ScheduledTaskSyncResponse,
    ServerConfigResponse,
    TaskEventBatchRequest,
    TaskEventBatchResponse,
    TaskRunListResponse,
    TaskRunReportRequest,
    TaskRunReportResponse,
    UploadResponse,
    WorkflowSyncResponse,
)

logger = logging.getLogger(__name__)


class ServerUnavailableError(Exception):
    """Raised when the server is unreachable after all retries."""

    pass


class ServerClient:
    """Async HTTP client for server-side management system API."""

    def __init__(
        self,
        server_url: str,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        self._server_url = server_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._client_id: str | None = None
        self._token: str | None = None
        self._client: httpx.AsyncClient | None = None

    @property
    def client_id(self) -> str | None:
        return self._client_id

    @property
    def is_registered(self) -> bool:
        return self._client_id is not None and self._token is not None

    async def start(self) -> None:
        """Initialize the HTTP client."""
        self._client = httpx.AsyncClient(
            base_url=self._server_url,
            timeout=httpx.Timeout(self._timeout),
            headers={"Content-Type": "application/json"},
        )

    async def stop(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _set_auth(self, token: str) -> None:
        """Set authorization header after registration."""
        self._token = token
        if self._client:
            self._client.headers["Authorization"] = f"Bearer {token}"

    def _require_registered(self) -> None:
        """Raise RuntimeError if the client is not registered."""
        if not self.is_registered:
            raise RuntimeError("Client is not registered. Call register() first.")

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Make an HTTP request with retry logic and exponential backoff."""
        if self._client is None:
            raise RuntimeError("Client is not started. Call start() first.")

        # Gzip compress large JSON bodies for POST/PUT requests
        json_body = kwargs.pop("json", None)
        if json_body is not None:
            body_bytes = json.dumps(json_body).encode("utf-8")
            headers = dict(kwargs.get("headers", {}))
            if len(body_bytes) > 1024:
                body_bytes = gzip.compress(body_bytes)
                headers["Content-Encoding"] = "gzip"
                headers["Content-Type"] = "application/json"
            else:
                headers["Content-Type"] = "application/json"
            kwargs["content"] = body_bytes
            kwargs["headers"] = headers

        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                response = await self._client.request(method, path, **kwargs)
                response.raise_for_status()
                return response
            except httpx.ConnectError as exc:
                last_exc = exc
                delay = self._retry_delay * (2**attempt)
                logger.warning(
                    "Connection error on %s %s (attempt %d/%d), retrying in %.1fs: %s",
                    method,
                    path,
                    attempt + 1,
                    self._max_retries,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
            except httpx.ReadTimeout as exc:
                last_exc = exc
                delay = self._retry_delay * (2**attempt)
                logger.warning(
                    "Read timeout on %s %s (attempt %d/%d), retrying in %.1fs: %s",
                    method,
                    path,
                    attempt + 1,
                    self._max_retries,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
            except httpx.WriteTimeout as exc:
                last_exc = exc
                delay = self._retry_delay * (2**attempt)
                logger.warning(
                    "Write timeout on %s %s (attempt %d/%d), retrying in %.1fs: %s",
                    method,
                    path,
                    attempt + 1,
                    self._max_retries,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)

        raise ServerUnavailableError(
            f"Server unavailable after {self._max_retries} retries: {last_exc}"
        )

    # --- Group 1: Registration & Heartbeat ---

    async def register(self, req: ClientRegisterRequest) -> ClientRegisterResponse:
        """POST /api/v1/clients/register"""
        if self._client is None:
            raise RuntimeError("Client is not started. Call start() first.")

        response = await self._request(
            "POST", "/api/v1/clients/register", json=req.model_dump()
        )
        data = response.json()
        result = ClientRegisterResponse.model_validate(data)
        self._client_id = result.client_id
        self._set_auth(result.token)
        return result

    async def heartbeat(self, req: ClientHeartbeatRequest) -> ClientHeartbeatResponse:
        """POST /api/v1/clients/{client_id}/heartbeat"""
        self._require_registered()
        response = await self._request(
            "POST",
            f"/api/v1/clients/{self._client_id}/heartbeat",
            json=req.model_dump(),
        )
        return ClientHeartbeatResponse.model_validate(response.json())

    # --- Group 2: Device Report ---

    async def report_devices(self, req: DeviceReportRequest) -> DeviceReportResponse:
        """POST /api/v1/clients/{client_id}/devices/report"""
        self._require_registered()
        response = await self._request(
            "POST",
            f"/api/v1/clients/{self._client_id}/devices/report",
            json=req.model_dump(),
        )
        return DeviceReportResponse.model_validate(response.json())

    # --- Group 3: Scheduled Task Sync ---

    async def pull_scheduled_tasks(
        self, since: str | None = None
    ) -> ScheduledTaskSyncResponse:
        """GET /api/v1/clients/{client_id}/scheduled-tasks?since={since}"""
        self._require_registered()
        params: dict[str, Any] = {}
        if since is not None:
            params["since"] = since
        response = await self._request(
            "GET",
            f"/api/v1/clients/{self._client_id}/scheduled-tasks",
            params=params,
        )
        return ScheduledTaskSyncResponse.model_validate(response.json())

    async def report_execution(
        self, task_id: str, req: ExecutionReportRequest
    ) -> ExecutionReportResponse:
        """POST /api/v1/clients/{client_id}/scheduled-tasks/{task_id}/execution-report"""
        self._require_registered()
        response = await self._request(
            "POST",
            f"/api/v1/clients/{self._client_id}/scheduled-tasks/{task_id}/execution-report",
            json=req.model_dump(),
        )
        return ExecutionReportResponse.model_validate(response.json())

    # --- Group 4: Workflow Sync ---

    async def pull_workflows(self, since: str | None = None) -> WorkflowSyncResponse:
        """GET /api/v1/clients/{client_id}/workflows?since={since}"""
        self._require_registered()
        params: dict[str, Any] = {}
        if since is not None:
            params["since"] = since
        response = await self._request(
            "GET",
            f"/api/v1/clients/{self._client_id}/workflows",
            params=params,
        )
        return WorkflowSyncResponse.model_validate(response.json())

    # --- Group 5: Config Sync ---

    async def pull_config(self) -> ServerConfigResponse:
        """GET /api/v1/clients/{client_id}/config"""
        self._require_registered()
        response = await self._request(
            "GET",
            f"/api/v1/clients/{self._client_id}/config",
        )
        return ServerConfigResponse.model_validate(response.json())

    # --- Group 6: Task Run Report ---

    async def report_task_run(self, req: TaskRunReportRequest) -> TaskRunReportResponse:
        """POST /api/v1/clients/{client_id}/task-runs/report"""
        self._require_registered()
        response = await self._request(
            "POST",
            f"/api/v1/clients/{self._client_id}/task-runs/report",
            json=req.model_dump(),
        )
        return TaskRunReportResponse.model_validate(response.json())

    async def report_task_events_batch(
        self, task_run_id: str, req: TaskEventBatchRequest
    ) -> TaskEventBatchResponse:
        """POST /api/v1/clients/{client_id}/task-runs/{task_run_id}/events/batch"""
        self._require_registered()
        response = await self._request(
            "POST",
            f"/api/v1/clients/{self._client_id}/task-runs/{task_run_id}/events/batch",
            json=req.model_dump(),
        )
        return TaskEventBatchResponse.model_validate(response.json())

    async def upload_file(
        self,
        file_data: bytes,
        filename: str,
        task_run_id: str,
        category: str = "screenshot",
        mime_type: str = "image/png",
    ) -> UploadResponse:
        """POST /api/v1/clients/{client_id}/uploads (multipart/form-data)"""
        self._require_registered()
        if self._client is None:
            raise RuntimeError("Client is not started. Call start() first.")

        files = {"file": (filename, file_data, mime_type)}
        data = {
            "task_run_id": task_run_id,
            "category": category,
        }
        # Remove Content-Type header so httpx can set multipart boundary
        headers = dict(self._client.headers)
        headers.pop("Content-Type", None)

        response = await self._request(
            "POST",
            f"/api/v1/clients/{self._client_id}/uploads",
            files=files,
            data=data,
            headers=headers,
        )
        return UploadResponse.model_validate(response.json())

    # --- Group 8: Task Control ---

    async def list_task_runs(
        self, status: str | None = None, limit: int = 20
    ) -> TaskRunListResponse:
        """GET /api/v1/clients/{client_id}/task-runs"""
        self._require_registered()
        params: dict[str, Any] = {"limit": limit}
        if status is not None:
            params["status"] = status
        response = await self._request(
            "GET",
            f"/api/v1/clients/{self._client_id}/task-runs",
            params=params,
        )
        return TaskRunListResponse.model_validate(response.json())

    async def cancel_task_run(self, task_run_id: str) -> dict:
        """POST /api/v1/clients/{client_id}/task-runs/{task_run_id}/cancel"""
        self._require_registered()
        response = await self._request(
            "POST",
            f"/api/v1/clients/{self._client_id}/task-runs/{task_run_id}/cancel",
        )
        return response.json()

    # --- SSE Stream ---

    async def events_stream(self) -> AsyncGenerator[tuple[str, str], None]:
        """GET /api/v1/clients/{client_id}/events/stream (SSE)

        Returns an async generator yielding (event_type, data) tuples.
        """
        self._require_registered()
        if self._client is None:
            raise RuntimeError("Client is not started. Call start() first.")

        async with self._client.stream(
            "GET",
            f"/api/v1/clients/{self._client_id}/events/stream",
            headers={"Accept": "text/event-stream"},
        ) as response:
            response.raise_for_status()
            event_type = "message"
            data_lines: list[str] = []

            async for line in response.aiter_lines():
                # SSE lines: "event: <type>", "data: <data>", or empty line (event boundary)
                if line.startswith("event:"):
                    event_type = line[len("event:") :].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[len("data:") :].strip())
                elif line == "":
                    # Empty line signals end of an event
                    if data_lines:
                        data = "\n".join(data_lines)
                        yield (event_type, data)
                        event_type = "message"
                        data_lines = []
