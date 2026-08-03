"""Midscene Web Agent - PC Web inspection via midscene-service."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any
import httpx

from AutoGLM_GUI.config import AgentConfig, ModelConfig, StepResult
from AutoGLM_GUI.device_protocol import DeviceProtocol
from AutoGLM_GUI.logger import logger


# URL 提取正则：匹配 http(s):// 或 www. 开头的 URL
_URL_PATTERN = re.compile(
    r"https?://[^\s]+|www\.[^\s]+\.[^\s]+",
    re.IGNORECASE,
)


def _extract_url(text: str) -> str | None:
    """从文本中提取第一个 URL。"""
    match = _URL_PATTERN.search(text)
    if match:
        url = match.group(0)
        if url.startswith("www."):
            url = "https://" + url
        return url
    return None


class MidsceneWebAgent:
    """Agent for PC Web inspection via midscene-service SSE API."""

    def __init__(
        self,
        model_config: ModelConfig,
        agent_config: AgentConfig,
        device: DeviceProtocol,
        service_url: str = "http://localhost:39000",
        takeover_callback: Any = None,
        confirmation_callback: Any = None,
    ) -> None:
        self.model_config = model_config
        self.agent_config = agent_config
        self._device = device
        self._service_url = service_url.rstrip("/")
        self._step_count = 0
        self._is_running = False
        self._cancel_event = asyncio.Event()
        self._context: list[dict[str, Any]] = []

    async def run(self, task: str) -> str:
        """Run task and return final message."""
        result = ""
        async for event in self.stream(task):
            if event["type"] == "done":
                result = event["data"].get("message", "")
            elif event["type"] == "error":
                raise RuntimeError(event["data"]["message"])
        return result

    def stream(
        self, task: str, *, continue_with: str | None = None,
        env_url: str = "", execute_account: str = "", execute_password: str = "",
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream execution events from midscene-service."""
        return self._stream_impl(task, env_url=env_url,
                                 execute_account=execute_account,
                                 execute_password=execute_password)

    async def _stream_impl(
        self, task: str, *,
        env_url: str = "", execute_account: str = "", execute_password: str = "",
    ) -> AsyncIterator[dict[str, Any]]:
        """Internal implementation of stream."""
        self._is_running = True
        self._step_count = 0

        if self._cancel_event.is_set():
            yield {"type": "cancelled", "data": {"message": "Cancelled by user"}}
            return

        self._cancel_event.clear()

        # 优先使用 env_url（从服务端同步的环境URL），否则从 task 文本提取
        target_url = env_url or getattr(self._device, "_target_url", None)
        if not target_url:
            target_url = _extract_url(task)

        try:
            logger.info(f"[MidsceneWeb] 连接到 midscene-service: {self._service_url}")
            async with httpx.AsyncClient(
                base_url=self._service_url, timeout=300.0
            ) as client:
                # 先导航到目标 URL
                if target_url:
                    try:
                        logger.info(f"[MidsceneWeb] 发送导航请求: {target_url}")
                        resp = await client.post(
                            "/navigate", json={"url": target_url}
                        )
                        resp.raise_for_status()
                        logger.info(f"[MidsceneWeb] 导航响应: {resp.status_code}")
                        yield {
                            "type": "thinking",
                            "data": {"chunk": f"正在导航到 {target_url} …"},
                        }
                    except Exception as e:
                        logger.warning(f"导航失败: {e}")

                # 如果提供了登录账号和密码，先执行登录
                if execute_account and execute_password and target_url:
                    try:
                        logger.info(f"[MidsceneWeb] 执行登录: account={execute_account}, url={target_url}")
                        login_resp = await client.post(
                            "/login",
                            json={
                                "url": target_url,
                                "account": execute_account,
                                "password": execute_password,
                            },
                            timeout=120.0,
                        )
                        login_resp.raise_for_status()
                        login_result = login_resp.json()
                        logger.info(f"[MidsceneWeb] 登录结果: {login_result}")
                        yield {
                            "type": "thinking",
                            "data": {"chunk": f"已使用账号 {execute_account} 登录环境 …"},
                        }
                    except Exception as e:
                        logger.warning(f"登录失败: {e}")
                        yield {
                            "type": "thinking",
                            "data": {"chunk": f"登录环境失败: {e}，继续执行巡检任务 …"},
                        }

                # 如果已经通过 /navigate 和 /login 完成了导航和登录，
                # 则 /execute 不需要再导航（避免覆盖登录状态）
                navigated = bool(target_url) and (execute_account and execute_password)
                execute_body: dict[str, Any] = {"prompt": task}
                if navigated:
                    execute_body["skipNavigate"] = True
                    execute_body["url"] = target_url  # 仍传 URL 用于日志
                else:
                    execute_body["url"] = target_url or "about:blank"

                logger.info(f"[MidsceneWeb] 发送执行请求: url={execute_body.get('url')}, skipNavigate={navigated}, task={task[:50]}")
                async with client.stream(
                    "POST",
                    "/execute",
                    json=execute_body,
                ) as response:
                    async for line in response.aiter_lines():
                        if self._cancel_event.is_set():
                            yield {
                                "type": "cancelled",
                                "data": {"message": "Cancelled by user"},
                            }
                            return

                        if not line.startswith("data: "):
                            continue

                        data = line[6:]  # Remove "data: " prefix
                        try:
                            event = json.loads(data)
                            event_type = event.get("type")
                            event_data = event.get("data", {})

                            if event_type == "step":
                                self._step_count += 1
                                event_data["step"] = self._step_count
                                self._context.append(event)

                            yield {"type": event_type, "data": event_data}

                            if event_type in ("done", "error", "cancelled"):
                                return

                        except json.JSONDecodeError:
                            logger.warning(f"Failed to parse SSE event: {data}")

        except httpx.HTTPError as e:
            yield {"type": "error", "data": {"message": f"HTTP error: {e}"}}
        except Exception as e:
            yield {"type": "error", "data": {"message": str(e)}}
        finally:
            self._is_running = False

    async def cancel(self) -> None:
        """Cancel current execution."""
        self._cancel_event.set()
        try:
            async with httpx.AsyncClient(
                base_url=self._service_url, timeout=10.0
            ) as client:
                await client.post("/cancel", json={})
        except Exception as e:
            logger.warning(f"Failed to send cancel request: {e}")

    def reset(self) -> None:
        """Reset agent state."""
        self._step_count = 0
        self._context.clear()
        self._cancel_event.clear()

    def step(self, task: str | None = None) -> StepResult:
        """Execute single step (not supported for async agent)."""
        raise NotImplementedError("Use stream() for async execution")

    @property
    def step_count(self) -> int:
        return self._step_count

    @property
    def context(self) -> list[dict[str, Any]]:
        return self._context

    @property
    def is_running(self) -> bool:
        return self._is_running