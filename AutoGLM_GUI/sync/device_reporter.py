from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from AutoGLM_GUI.sync.client import ServerClient, ServerUnavailableError
from AutoGLM_GUI.sync.schemas import (
    DeviceReportItem,
    DeviceReportRequest,
    DeviceReportResponse,
)

if TYPE_CHECKING:
    from AutoGLM_GUI.device_manager import DeviceManager
    from AutoGLM_GUI.sync.offline_queue import OfflineQueue

logger = logging.getLogger(__name__)


class DeviceReporter:
    """Reports device status changes to the server."""

    def __init__(
        self,
        client: ServerClient,
        device_manager: DeviceManager,
        offline_queue: OfflineQueue | None = None,
    ):
        self._client = client
        self._device_manager = device_manager
        self._offline_queue = offline_queue
        self._last_reported_serials: set[str] = set()
        self._poll_task: asyncio.Task | None = None
        self._poll_interval: float = (
            60.0  # Fallback poll interval (primary is event-driven)
        )
        self._event_loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        """Start monitoring device changes."""
        self._event_loop = asyncio.get_running_loop()
        # Register event-driven callback on DeviceManager
        self._device_manager.register_device_change_callback(
            self._on_device_change_callback
        )
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = asyncio.create_task(self._poll_loop())

    def _on_device_change_callback(self) -> None:
        """Synchronous callback invoked by DeviceManager polling thread."""
        if self._event_loop is None or self._event_loop.is_closed():
            return
        try:
            self._event_loop.call_soon_threadsafe(self._schedule_report_if_changed)
        except RuntimeError:
            pass

    def _schedule_report_if_changed(self) -> None:
        """Schedule a device report if the device set has changed."""
        current_serials = {dev.serial for dev in self._device_manager.get_devices()}
        if current_serials != self._last_reported_serials:
            asyncio.ensure_future(self.report_all_devices())

    async def stop(self) -> None:
        """Stop monitoring."""
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

    async def report_all_devices(self) -> DeviceReportResponse | None:
        """Report all current device statuses to the server."""
        if not self._client.is_registered:
            return None
        try:
            devices = self._device_manager.get_devices()
            items = []
            for dev in devices:
                item = DeviceReportItem(
                    serial=dev.serial,
                    model=dev.model or "",
                    connection_type=self._map_connection_type(dev),
                    status=self._map_device_status(dev),
                    display_name=dev.display_name,
                    group_id=None,
                    agent_state=self._get_agent_state(dev),
                    agent_model_name=self._get_agent_model_name(dev),
                )
                items.append(item)

            if not items:
                return None

            req = DeviceReportRequest(
                timestamp=datetime.now(timezone.utc).isoformat(),
                devices=items,
            )
            resp = await self._client.report_devices(req)
            self._last_reported_serials = {dev.serial for dev in devices}
            logger.debug("Reported %d devices to server", len(items))
            return resp
        except ServerUnavailableError:
            logger.warning("Server unavailable, queuing device report for later")
            if self._offline_queue:
                self._offline_queue.push("device_report", req.model_dump())
            return None
        except Exception as e:
            logger.error("Failed to report devices: %s", e)
            return None

    async def _poll_loop(self) -> None:
        """Periodically check for device changes and report."""
        while True:
            try:
                await asyncio.sleep(self._poll_interval)
                # Check if devices have changed
                current_serials = {
                    dev.serial for dev in self._device_manager.get_devices()
                }
                if current_serials != self._last_reported_serials:
                    await self.report_all_devices()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Device poll error: %s", e)

    @staticmethod
    def _map_connection_type(dev) -> str:
        """Map device connection type to protocol string."""
        ct = dev.connection_type  # DeviceConnectionType property
        if ct and ct.value in ("usb", "wifi", "remote"):
            return ct.value
        return "usb"

    @staticmethod
    def _map_device_status(dev) -> str:
        """Map ManagedDevice.state to online/offline string."""
        # DeviceState values: online, offline, disconnected, available
        if dev.state.value in ("online", "available"):
            return "online"
        return "offline"

    @staticmethod
    def _get_agent_state(dev) -> str:
        """Get agent state for a device via PhoneAgentManager."""
        try:
            from AutoGLM_GUI.phone_agent_manager import PhoneAgentManager

            manager = PhoneAgentManager.get_instance()
            metadata = manager.get_metadata(dev.primary_device_id)
            if metadata and metadata.state:
                return metadata.state.value
        except Exception:
            pass
        return "idle"

    @staticmethod
    def _get_agent_model_name(dev) -> str | None:
        """Get agent model name for a device via PhoneAgentManager."""
        try:
            from AutoGLM_GUI.phone_agent_manager import PhoneAgentManager

            manager = PhoneAgentManager.get_instance()
            metadata = manager.get_metadata(dev.primary_device_id)
            if metadata and metadata.model_config:
                return metadata.model_config.model_name
        except Exception:
            pass
        return None
