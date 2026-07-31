"""Web Device - Browser-based device implementation via midscene-service."""

from __future__ import annotations

import httpx
from AutoGLM_GUI.device_protocol import DeviceProtocol, Screenshot
from AutoGLM_GUI.logger import logger
from AutoGLM_GUI.trace import trace_span


class WebDevice:
    """Browser device controlled via midscene-service HTTP API.

    This implementation maps browser operations to standard device operations
    via HTTP calls to midscene-service running on port 39000.

    Example:
        >>> device = WebDevice("web-browser", "http://localhost:39000")
        >>> screenshot = device.get_screenshot()
        >>> device.tap(100, 200)
        >>> device.navigate("https://example.com")
    """

    def __init__(
        self,
        device_id: str = "web-browser",
        service_url: str = "http://localhost:39000",
    ):
        """
        Initialize Web device.

        Args:
            device_id: Unique identifier for this browser instance.
            service_url: URL of the midscene-service HTTP API.
        """
        self._device_id = device_id
        self._service_url = service_url.rstrip("/")
        self._client = httpx.Client(base_url=self._service_url, timeout=30.0)

    @property
    def device_id(self) -> str:
        """Unique device identifier."""
        return self._device_id

    # === Screenshot ===
    def get_screenshot(self, timeout: int = 10) -> Screenshot:
        """Capture current browser screen."""
        with trace_span(
            "device.get_screenshot",
            attrs={
                "device_id": self._device_id,
                "device_impl": "web",
                "timeout": timeout,
            },
        ) as span:
            resp = self._client.post("/screenshot", timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            result = Screenshot(
                base64_data=data["screenshot"],
                width=data["width"],
                height=data["height"],
            )
            span.set_attributes({"width": result.width, "height": result.height})
            return result

    # === Input Operations ===
    def tap(self, x: int, y: int, delay: float | None = None) -> None:
        """Tap at specified coordinates."""
        with trace_span(
            "device.tap",
            attrs={"device_id": self._device_id, "device_impl": "web", "x": x, "y": y},
        ):
            resp = self._client.post("/tap", json={"x": x, "y": y})
            resp.raise_for_status()

    def double_tap(self, x: int, y: int, delay: float | None = None) -> None:
        """Double tap at specified coordinates.

        Web doesn't have native double_tap, simulated with two taps.
        """
        with trace_span(
            "device.double_tap",
            attrs={"device_id": self._device_id, "device_impl": "web", "x": x, "y": y},
        ):
            self.tap(x, y, delay)
            self.tap(x, y, delay)

    def long_press(
        self, x: int, y: int, duration_ms: int = 3000, delay: float | None = None
    ) -> None:
        """Long press at specified coordinates.

        Not fully supported for Web devices.
        """
        with trace_span(
            "device.long_press",
            attrs={
                "device_id": self._device_id,
                "device_impl": "web",
                "x": x,
                "y": y,
                "duration_ms": duration_ms,
            },
        ):
            logger.warning("long_press not fully supported for WebDevice")

    def swipe(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration_ms: int | None = None,
        delay: float | None = None,
    ) -> None:
        """Swipe from start to end coordinates.

        Not fully supported for Web devices.
        """
        with trace_span(
            "device.swipe",
            attrs={
                "device_id": self._device_id,
                "device_impl": "web",
                "start_x": start_x,
                "start_y": start_y,
                "end_x": end_x,
                "end_y": end_y,
                "duration_ms": duration_ms,
            },
        ):
            logger.warning("swipe not fully supported for WebDevice")

    def type_text(self, text: str) -> None:
        """Type text into the currently focused input field."""
        with trace_span(
            "device.type_text",
            attrs={
                "device_id": self._device_id,
                "device_impl": "web",
                "text_length": len(text),
            },
        ):
            resp = self._client.post("/type", json={"text": text})
            resp.raise_for_status()

    def clear_text(self) -> None:
        """Clear text in the currently focused input field."""
        with trace_span(
            "device.clear_text",
            attrs={"device_id": self._device_id, "device_impl": "web"},
        ):
            self.type_text("")

    # === Navigation ===
    def back(self, delay: float | None = None) -> None:
        """Press the back button.

        Not applicable for Web devices.
        """
        with trace_span(
            "device.back",
            attrs={"device_id": self._device_id, "device_impl": "web"},
        ):
            logger.warning("back not applicable for WebDevice")

    def home(self, delay: float | None = None) -> None:
        """Press the home button.

        Not applicable for Web devices.
        """
        with trace_span(
            "device.home",
            attrs={"device_id": self._device_id, "device_impl": "web"},
        ):
            logger.warning("home not applicable for WebDevice")

    def launch_app(self, app_name: str, delay: float | None = None) -> bool:
        """Launch an app by name.

        Not applicable for Web devices.
        """
        with trace_span(
            "device.launch_app",
            attrs={
                "device_id": self._device_id,
                "device_impl": "web",
                "app_name": app_name,
            },
        ):
            logger.warning("launch_app not applicable for WebDevice")
            return False

    # === State Query ===
    def get_current_app(self) -> str:
        """Get the currently focused app name."""
        with trace_span(
            "device.get_current_app",
            attrs={"device_id": self._device_id, "device_impl": "web"},
        ) as span:
            span.set_attribute("current_app", "Web Browser")
            return "Web Browser"

    # === Keyboard Management ===
    def detect_and_set_adb_keyboard(self) -> str:
        """Detect current keyboard and switch to ADB Keyboard if needed.

        Not applicable for Web devices.
        """
        with trace_span(
            "device.detect_and_set_adb_keyboard",
            attrs={"device_id": self._device_id, "device_impl": "web"},
        ):
            return ""

    def restore_keyboard(self, ime: str) -> None:
        """Restore the original keyboard IME.

        Not applicable for Web devices.
        """
        with trace_span(
            "device.restore_keyboard",
            attrs={"device_id": self._device_id, "device_impl": "web"},
        ):
            pass

    # === Web-specific Operations ===
    def navigate(self, url: str) -> None:
        """Navigate to a URL (Web-specific operation).

        Args:
            url: The URL to navigate to.
        """
        with trace_span(
            "device.navigate",
            attrs={"device_id": self._device_id, "device_impl": "web", "url": url},
        ):
            resp = self._client.post("/navigate", json={"url": url})
            resp.raise_for_status()

    def close(self) -> None:
        """Close the HTTP client connection."""
        self._client.close()


# Verify WebDevice implements DeviceProtocol
assert isinstance(WebDevice("test"), DeviceProtocol)
