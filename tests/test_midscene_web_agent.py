"""Tests for MidsceneWebAgent."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from AutoGLM_GUI.agents.midscene_web import MidsceneWebAgent
from AutoGLM_GUI.config import AgentConfig, ModelConfig


def aiter(items):
    """Helper to create an async iterator from a list."""
    async def _aiter():
        for item in items:
            yield item
    return _aiter()


@pytest.fixture
def mock_device():
    """Create a mock device."""
    device = MagicMock()
    device.device_id = "web-device"
    device._target_url = "http://example.com"
    return device


@pytest.fixture
def agent(mock_device):
    """Create a MidsceneWebAgent instance."""
    model_config = ModelConfig()
    agent_config = AgentConfig()
    return MidsceneWebAgent(
        model_config=model_config,
        agent_config=agent_config,
        device=mock_device,
        service_url="http://localhost:39000",
    )


def test_agent_initialization(agent):
    """Test agent initialization."""
    assert agent.step_count == 0
    assert agent.is_running is False
    assert agent.context == []
    assert agent._service_url == "http://localhost:39000"


def test_agent_reset(agent):
    """Test agent reset."""
    agent._step_count = 5
    agent._context = [{"type": "step", "data": {}}]
    agent._cancel_event.set()

    agent.reset()

    assert agent.step_count == 0
    assert agent.context == []
    assert agent._cancel_event.is_set() is False


def test_agent_step_raises_not_implemented(agent):
    """Test that step() raises NotImplementedError."""
    with pytest.raises(NotImplementedError):
        agent.step("test task")


def test_agent_cancel(agent):
    """Test agent cancel."""
    async def _test():
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.post = AsyncMock()

            await agent.cancel()

            assert agent._cancel_event.is_set()
            mock_client.return_value.post.assert_called_once_with("/cancel", json={})

    asyncio.run(_test())


def test_agent_stream_sse_parsing(agent):
    """Test SSE event parsing."""
    async def _test():
        mock_response = MagicMock()
        mock_response.aiter_lines = MagicMock(return_value=aiter([
            'data: {"type": "step", "data": {"action": {"type": "click"}}}',
            'data: {"type": "done", "data": {"message": "Task completed"}}',
        ]))

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.stream = MagicMock(return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            ))

            events = []
            async for event in agent.stream("test task"):
                events.append(event)

            assert len(events) == 2
            assert events[0]["type"] == "step"
            assert events[1]["type"] == "done"
            assert agent.step_count == 1

    asyncio.run(_test())


def test_agent_stream_cancelled(agent):
    """Test stream cancellation."""
    async def _test():
        agent._cancel_event.set()

        events = []
        async for event in agent.stream("test task"):
            events.append(event)

        assert len(events) == 1
        assert events[0]["type"] == "cancelled"

    asyncio.run(_test())


def test_agent_context_property(agent):
    """Test context property."""
    agent._context = [
        {"type": "step", "data": {"step": 1}},
        {"type": "step", "data": {"step": 2}},
    ]

    assert len(agent.context) == 2
    assert agent.context[0]["type"] == "step"


def test_agent_is_running_property(agent):
    """Test is_running property."""
    assert agent.is_running is False
    agent._is_running = True
    assert agent.is_running is True