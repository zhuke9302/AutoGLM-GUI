from __future__ import annotations

import asyncio
import logging
import platform
import socket
from typing import TYPE_CHECKING

from AutoGLM_GUI.sync.client import ServerClient
from AutoGLM_GUI.sync.schemas import (
    ClientHeartbeatRequest,
    ClientHeartbeatResponse,
    ClientRegisterRequest,
    ClientRegisterResponse,
)

if TYPE_CHECKING:
    from AutoGLM_GUI.device_manager import DeviceManager
    from AutoGLM_GUI.task_manager import TaskManager

logger = logging.getLogger(__name__)


class SyncRegistration:
    """Manages client registration and heartbeat with the server."""

    def __init__(
        self,
        client: ServerClient,
        device_manager: DeviceManager,
        task_manager: TaskManager,
        heartbeat_interval: float = 30.0,
    ):
        self._client = client
        self._device_manager = device_manager
        self._task_manager = task_manager
        self._heartbeat_interval = heartbeat_interval
        self._heartbeat_task: asyncio.Task | None = None
        self._registered = False

    @property
    def is_registered(self) -> bool:
        return self._registered

    async def register(self) -> ClientRegisterResponse | None:
        """Register this client with the server.

        Collects system info (hostname, IP, OS, version),
        then calls the server register endpoint.
        """
        try:
            # Collect system info
            hostname = socket.gethostname()
            # Get primary IP (non-loopback)
            ip = self._get_primary_ip()
            os_info = f"{platform.system()} {platform.release()}"
            version = self._get_version()

            req = ClientRegisterRequest(
                hostname=hostname,
                ip=ip,
                os=os_info,
                version=version,
            )

            resp = await self._client.register(req)
            self._registered = True
            logger.info(
                "Registered with server: client_id=%s, heartbeat_interval=%ds",
                resp.client_id,
                resp.heartbeat_interval_seconds,
            )
            # Update heartbeat interval from server response
            self._heartbeat_interval = resp.heartbeat_interval_seconds
            return resp
        except Exception as e:
            logger.error("Failed to register with server: %s", e)
            self._registered = False
            return None

    async def start_heartbeat(self) -> None:
        """Start the periodic heartbeat task."""
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def stop_heartbeat(self) -> None:
        """Stop the heartbeat task."""
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

    async def send_heartbeat(self) -> ClientHeartbeatResponse | None:
        """Send a single heartbeat to the server."""
        if not self._client.is_registered:
            return None
        try:
            # Collect current status
            device_count = len(self._device_manager.get_devices())
            running_task_count = self._task_manager.get_running_task_count()

            req = ClientHeartbeatRequest(
                timestamp=self._now_iso(),
                device_count=device_count,
                running_task_count=running_task_count,
                status="healthy",
            )

            resp = await self._client.heartbeat(req)
            logger.debug(
                "Heartbeat ack=%s config_changes=%s task_changes=%s",
                resp.ack,
                resp.config_changes,
                resp.task_changes,
            )
            return resp
        except Exception as e:
            logger.warning("Heartbeat failed: %s", e)
            return None

    async def _heartbeat_loop(self) -> None:
        """Periodic heartbeat loop."""
        while True:
            try:
                await asyncio.sleep(self._heartbeat_interval)
                await self.send_heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Heartbeat loop error: %s", e)

    @staticmethod
    def _get_primary_ip() -> str:
        """Get the primary non-loopback IP address."""
        try:
            # Connect to a public DNS to determine outbound IP
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"

    @staticmethod
    def _get_version() -> str:
        """Get the application version."""
        try:
            from importlib.metadata import version as pkg_version

            return pkg_version("autoglm-gui")
        except Exception:
            return "0.0.0"

    @staticmethod
    def _now_iso() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()
