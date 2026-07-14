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


class ServerAPIError(Exception):
    """Raised when the server returns a non-success Result code."""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"Server API error: code={code}, message={message}")


class ServerClient:
    """Async HTTP client for server-side management system API."""

    def __init__(
        self,
        server_url: str,
        sse_url: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        self._server_url = server_url.rstrip("/")
        self._sse_url = sse_url.rstrip("/") if sse_url else None
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._client_id: str | None = None
        self._token: str | None = None
        self._client: httpx.AsyncClient | None = None
        self._sse_client: httpx.AsyncClient | None = None

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
        if self._sse_client:
            self._sse_client.headers["Authorization"] = f"Bearer {token}"

    def _require_registered(self) -> None:
        """Raise RuntimeError if the client is not registered."""
        if not self.is_registered:
            raise RuntimeError("Client is not registered. Call register() first.")

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Make an HTTP request with retry logic and exponential backoff."""
        if self._client is None:
            raise RuntimeError("Client is not started. Call start() first.")

        # 对大于 1KB 的 JSON body 进行 gzip 压缩。
        # 服务端必须配置 GzipRequestFilter 解压请求体（按 Content-Encoding: gzip 头判断）。
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

    async def _request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        """Make an HTTP request and unwrap the Result envelope.

        The server wraps all responses in ``Result<T>`` with fields
        ``{code, message, data, timestamp}``. This method extracts the
        inner ``data`` field and raises ``ServerAPIError`` if the code
        is non-zero.
        """
        response = await self._request(method, path, **kwargs)
        body = response.json()
        # Unwrap Result envelope: {code, message, data, timestamp}
        if isinstance(body, dict) and "code" in body and "data" in body:
            code = body.get("code")
            if code != 0:
                msg = body.get("message", "Unknown error")
                raise ServerAPIError(code, msg)
            return body.get("data")
        # If not wrapped in Result, return as-is
        return body

    # --- Group 1: Registration & Heartbeat ---

    async def register(self, req: ClientRegisterRequest) -> ClientRegisterResponse:
        """POST /api/v1/clients/register"""
        if self._client is None:
            raise RuntimeError("Client is not started. Call start() first.")

        data = await self._request_json(
            "POST", "/api/v1/clients/register", json=req.model_dump(by_alias=True)
        )
        result = ClientRegisterResponse.model_validate(data)
        self._client_id = result.client_id
        self._set_auth(result.token)
        return result

    async def heartbeat(self, req: ClientHeartbeatRequest) -> ClientHeartbeatResponse:
        """POST /api/v1/clients/{client_id}/heartbeat"""
        self._require_registered()
        data = await self._request_json(
            "POST",
            f"/api/v1/clients/{self._client_id}/heartbeat",
            json=req.model_dump(by_alias=True),
        )
        return ClientHeartbeatResponse.model_validate(data)

    # --- Group 2: Device Report ---

    async def report_devices(self, req: DeviceReportRequest) -> DeviceReportResponse:
        """POST /api/v1/clients/{client_id}/devices/report"""
        self._require_registered()
        data = await self._request_json(
            "POST",
            f"/api/v1/clients/{self._client_id}/devices/report",
            json=req.model_dump(by_alias=True),
        )
        return DeviceReportResponse.model_validate(data)

    # --- Group 3: Scheduled Task Sync ---

    async def pull_scheduled_tasks(
        self, since: str | None = None
    ) -> ScheduledTaskSyncResponse:
        """GET /api/v1/clients/{client_id}/scheduled-tasks?since={since}"""
        self._require_registered()
        params: dict[str, Any] = {}
        if since is not None:
            params["since"] = since
        data = await self._request_json(
            "GET",
            f"/api/v1/clients/{self._client_id}/scheduled-tasks",
            params=params,
        )
        return ScheduledTaskSyncResponse.model_validate(data)

    async def report_execution(
        self, task_id: str, req: ExecutionReportRequest
    ) -> ExecutionReportResponse:
        """POST /api/v1/clients/{client_id}/scheduled-tasks/{task_id}/execution-report"""
        self._require_registered()
        data = await self._request_json(
            "POST",
            f"/api/v1/clients/{self._client_id}/scheduled-tasks/{task_id}/execution-report",
            json=req.model_dump(by_alias=True),
        )
        return ExecutionReportResponse.model_validate(data)

    # --- Group 4: Workflow Sync ---

    async def pull_workflows(self, since: str | None = None) -> WorkflowSyncResponse:
        """GET /api/v1/clients/{client_id}/workflows?since={since}"""
        self._require_registered()
        params: dict[str, Any] = {}
        if since is not None:
            params["since"] = since
        data = await self._request_json(
            "GET",
            f"/api/v1/clients/{self._client_id}/workflows",
            params=params,
        )
        return WorkflowSyncResponse.model_validate(data)

    # --- Group 5: Config Sync ---

    async def pull_config(self) -> ServerConfigResponse:
        """GET /api/v1/clients/{client_id}/config"""
        self._require_registered()
        data = await self._request_json(
            "GET",
            f"/api/v1/clients/{self._client_id}/config",
        )
        return ServerConfigResponse.model_validate(data)

    # --- Group 6: Task Run Report ---

    async def report_task_run(self, req: TaskRunReportRequest) -> TaskRunReportResponse:
        """POST /api/v1/clients/{client_id}/task-runs/report"""
        self._require_registered()
        data = await self._request_json(
            "POST",
            f"/api/v1/clients/{self._client_id}/task-runs/report",
            json=req.model_dump(by_alias=True),
        )
        return TaskRunReportResponse.model_validate(data)

    async def report_task_events_batch(
        self, task_run_id: str, req: TaskEventBatchRequest
    ) -> TaskEventBatchResponse:
        """POST /api/v1/clients/{client_id}/task-runs/{task_run_id}/events/batch"""
        self._require_registered()
        data = await self._request_json(
            "POST",
            f"/api/v1/clients/{self._client_id}/task-runs/{task_run_id}/events/batch",
            json=req.model_dump(by_alias=True),
        )
        return TaskEventBatchResponse.model_validate(data)

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
        body = response.json()
        # Unwrap Result envelope
        if isinstance(body, dict) and "code" in body and "data" in body:
            if body.get("code") != 0:
                raise ServerAPIError(body.get("code", -1), body.get("message", ""))
            body = body.get("data")
        return UploadResponse.model_validate(body)

    async def upload_screenshot_to_s3(
        self,
        image_data: bytes,
        task_run_id: str,
        seq: int,
        filename: str = "screenshot.png",
    ) -> str | None:
        """POST /api/v1/clients/{client_id}/screenshots/upload (multipart)

        Upload a screenshot to S3 via the gateway, returning the S3 URL.
        This bypasses the WebSocket tunnel, avoiding buffer overflow.
        """
        self._require_registered()
        if self._client is None:
            raise RuntimeError("Client is not started. Call start() first.")

        files = {"file": (filename, image_data, "image/png")}
        data = {"task_run_id": task_run_id, "seq": str(seq)}

        # 临时移除客户端默认的 Content-Type: application/json，
        # 让 httpx 自动设置 multipart/form-data; boundary=...
        default_ct = self._client.headers.pop("Content-Type", None)
        try:
            response = await self._request(
                "POST",
                f"/api/v1/clients/{self._client_id}/screenshots/upload",
                files=files,
                data=data,
            )
        finally:
            if default_ct is not None:
                self._client.headers["Content-Type"] = default_ct
        body = response.json()
        if isinstance(body, dict) and "url" in body:
            return body["url"]
        return None

    # --- Group 8: Task Control ---

    async def list_task_runs(
        self, status: str | None = None, limit: int = 20
    ) -> TaskRunListResponse:
        """GET /api/v1/clients/{client_id}/task-runs"""
        self._require_registered()
        params: dict[str, Any] = {"limit": limit}
        if status is not None:
            params["status"] = status
        data = await self._request_json(
            "GET",
            f"/api/v1/clients/{self._client_id}/task-runs",
            params=params,
        )
        return TaskRunListResponse.model_validate(data)

    async def cancel_task_run(self, task_run_id: str) -> dict:
        """POST /api/v1/clients/{client_id}/task-runs/{task_run_id}/cancel"""
        self._require_registered()
        return await self._request_json(
            "POST",
            f"/api/v1/clients/{self._client_id}/task-runs/{task_run_id}/cancel",
        )

    # --- SSE Stream ---

    async def events_stream(self) -> AsyncGenerator[tuple[str, str], None]:
        """GET /api/v1/clients/{client_id}/events/stream (SSE)

        Returns an async generator yielding (event_type, data) tuples.

        Note: SSE uses a long-lived connection with no read timeout. The
        server sends a ``ping`` event every heartbeat interval (default
        30s) to keep the connection alive. The default client timeout
        must not be applied to the read phase, otherwise the stream
        would be closed on the first idle 30s.
        """
        self._require_registered()
        if self._client is None:
            raise RuntimeError("Client is not started. Call start() first.")

        # SSE needs a long-lived connection: disable read timeout, keep
        # connect/write timeouts bounded so connection issues are still
        # surfaced quickly.
        sse_timeout = httpx.Timeout(
            connect=self._timeout,
            write=self._timeout,
            read=None,  # never time out waiting for server-sent events
            pool=self._timeout,
        )
        async with self._client.stream(
            "GET",
            f"/api/v1/clients/{self._client_id}/events/stream",
            headers={"Accept": "text/event-stream"},
            timeout=sse_timeout,
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
