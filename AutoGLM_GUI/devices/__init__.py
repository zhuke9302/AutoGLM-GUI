"""Device implementations for the DeviceProtocol interface.

This package provides concrete implementations of DeviceProtocol:
- ADBDevice: Local ADB subprocess calls
- MockDevice: State machine driven mock for testing
- RemoteDevice: HTTP client for remote device agents
- WebDevice: Browser device via midscene-service HTTP API

Example:
    >>> from AutoGLM_GUI.devices import ADBDevice, RemoteDevice, WebDevice
    >>>
    >>> # Local ADB device
    >>> device = ADBDevice("emulator-5554")
    >>> device.tap(100, 200)
    >>>
    >>> # Remote device via HTTP
    >>> remote = RemoteDevice("phone_001", "http://device-agent:8001")
    >>> remote.tap(100, 200)
    >>>
    >>> # Browser device via midscene-service
    >>> web = WebDevice("web-browser", "http://localhost:39000")
    >>> web.navigate("https://example.com")
    >>> web.tap(100, 200)
"""

from AutoGLM_GUI.devices.adb_device import (
    ADBDevice,
    ADBDeviceManager,
    AsyncADBDevice,
    AsyncADBDeviceManager,
)
from AutoGLM_GUI.devices.async_adapter import AsyncDeviceAdapter
from AutoGLM_GUI.devices.mock_device import MockDevice
from AutoGLM_GUI.devices.remote_device import RemoteDevice, RemoteDeviceManager
from AutoGLM_GUI.devices.web_device import WebDevice

__all__ = [
    "ADBDevice",
    "ADBDeviceManager",
    "AsyncADBDevice",
    "AsyncADBDeviceManager",
    "AsyncDeviceAdapter",
    "MockDevice",
    "RemoteDevice",
    "RemoteDeviceManager",
    "WebDevice",
]
