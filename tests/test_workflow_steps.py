"""Unit tests for workflow step execution and business_status propagation.

Covers Task 11-14 of the business-assertion feature:

- Task 8  : WorkflowRecord / WorkflowStepItem persistence (steps field)
- Task 9  : WorkflowStepSyncItem / TaskRunReportRequest schemas (business_status)
- Task 11 : _execute_classic_chat step loop (action/assertion discrimination)
- Task 12 : step event payload standardization (step_type / step_order / step_name / passed / actual)
- Task 14 : task_store business_status persistence
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from AutoGLM_GUI.task_manager import TaskManager
from AutoGLM_GUI.task_store import TaskStatus, TaskStore
from AutoGLM_GUI.workflow_manager import (
    WorkflowManager,
    WorkflowRecord,
    WorkflowStepItem,
)


# ============================================================================
# 1. WorkflowRecord / WorkflowStepItem persistence (Task 8)
# ============================================================================


def test_workflow_record_with_steps_roundtrip(tmp_path: Path) -> None:
    """WorkflowRecord serialized with steps and reloaded retains steps field."""
    manager = WorkflowManager()
    # Redirect manager file location to tmp_path to avoid touching user config.
    manager._workflows_path = tmp_path / "workflows.json"
    manager._file_cache = None
    manager._file_mtime = None

    steps: list[WorkflowStepItem] = [
        {"step_order": 1, "step_type": "action", "step_name": "打开设置"},
        {"step_order": 2, "step_type": "action", "step_name": "进入 Wi-Fi"},
        {"step_order": 3, "step_type": "assertion", "step_name": "验证 Wi-Fi 已开启"},
    ]
    wf = manager.create_workflow(name="wf-steps", text="检查 Wi-Fi", steps=steps)
    assert wf["steps"] == steps

    reloaded = manager.get_workflow(wf["uuid"])
    assert reloaded is not None
    assert reloaded["steps"] == steps
    assert [s["step_order"] for s in reloaded["steps"]] == [1, 2, 3]
    assert reloaded["steps"][2]["step_type"] == "assertion"


def test_workflow_record_without_steps_omits_key(tmp_path: Path) -> None:
    """Legacy workflow (no steps) should not have the steps key on disk."""
    manager = WorkflowManager()
    manager._workflows_path = tmp_path / "workflows.json"
    manager._file_cache = None
    manager._file_mtime = None

    wf = manager.create_workflow(name="wf-legacy", text="just text")
    assert "steps" not in wf

    raw = json.loads((tmp_path / "workflows.json").read_text(encoding="utf-8"))
    assert "steps" not in raw["workflows"][0]

    reloaded = manager.get_workflow(wf["uuid"])
    assert reloaded is not None
    assert "steps" not in reloaded


def test_workflow_update_preserves_and_overwrites_steps(tmp_path: Path) -> None:
    """update_workflow with steps overwrites prior steps; None leaves them intact."""
    manager = WorkflowManager()
    manager._workflows_path = tmp_path / "workflows.json"
    manager._file_cache = None
    manager._file_mtime = None

    steps_v1: list[WorkflowStepItem] = [
        {"step_order": 1, "step_type": "action", "step_name": "v1-step"},
    ]
    wf = manager.create_workflow(name="wf-up", text="t", steps=steps_v1)

    steps_v2: list[WorkflowStepItem] = [
        {"step_order": 1, "step_type": "action", "step_name": "v2-a"},
        {"step_order": 2, "step_type": "assertion", "step_name": "v2-b"},
    ]
    updated = manager.update_workflow(
        wf["uuid"], name="wf-up", text="t2", steps=steps_v2
    )
    assert updated is not None
    assert updated["steps"] == steps_v2

    # Calling update_workflow without steps keeps existing steps
    updated_again = manager.update_workflow(
        wf["uuid"], name="wf-up-renamed", text="t3", steps=None
    )
    assert updated_again is not None
    assert updated_again["name"] == "wf-up-renamed"
    assert updated_again["steps"] == steps_v2


# ============================================================================
# 2. Schemas (Task 9 / Task 13) - WorkflowStepSyncItem + TaskRunReportRequest
# ============================================================================


class TestSchemasForBusinessAssertion:
    def test_workflow_step_sync_item_action(self) -> None:
        from AutoGLM_GUI.sync.schemas import WorkflowStepSyncItem

        item = WorkflowStepSyncItem(
            step_order=1, step_type="action", step_name="打开 App"
        )
        assert item.step_order == 1
        assert item.step_type == "action"
        assert item.step_name == "打开 App"

    def test_workflow_step_sync_item_assertion(self) -> None:
        from AutoGLM_GUI.sync.schemas import WorkflowStepSyncItem

        item = WorkflowStepSyncItem(
            step_order=2, step_type="assertion", step_name="计数 > 0"
        )
        assert item.step_type == "assertion"

    def test_workflow_step_sync_item_rejects_bad_type(self) -> None:
        from pydantic import ValidationError

        from AutoGLM_GUI.sync.schemas import WorkflowStepSyncItem

        with pytest.raises(ValidationError):
            WorkflowStepSyncItem(step_order=1, step_type="verify", step_name="bad")

    def test_workflow_sync_item_default_empty_steps(self) -> None:
        from AutoGLM_GUI.sync.schemas import WorkflowSyncItem

        item = WorkflowSyncItem(
            uuid="u1", name="n", text="t", updated_at="2025-01-01T00:00:00Z"
        )
        assert item.steps == []

    def test_workflow_sync_item_with_steps(self) -> None:
        from AutoGLM_GUI.sync.schemas import WorkflowStepSyncItem, WorkflowSyncItem

        item = WorkflowSyncItem(
            uuid="u1",
            name="n",
            text="t",
            updated_at="2025-01-01T00:00:00Z",
            steps=[
                WorkflowStepSyncItem(step_order=1, step_type="action", step_name="s1"),
            ],
        )
        assert len(item.steps) == 1
        assert item.steps[0].step_type == "action"

    def test_task_run_report_request_business_status_ok(self) -> None:
        from AutoGLM_GUI.sync.schemas import TaskRunReportRequest

        req = TaskRunReportRequest(
            task_run_id="tr1",
            source="scheduled",
            device_serial="s1",
            status="succeeded",
            input_text="hello",
            step_count=5,
            started_at="2025-01-01T00:00:00Z",
            finished_at="2025-01-01T00:01:00Z",
            duration_ms=60000,
            business_status="ok",
        )
        assert req.business_status == "ok"

    def test_task_run_report_request_business_status_abnormal(self) -> None:
        from AutoGLM_GUI.sync.schemas import TaskRunReportRequest

        req = TaskRunReportRequest(
            task_run_id="tr2",
            source="scheduled",
            device_serial="s1",
            status="succeeded",
            input_text="hello",
            step_count=2,
            started_at="2025-01-01T00:00:00Z",
            finished_at="2025-01-01T00:01:00Z",
            duration_ms=60000,
            business_status="abnormal",
        )
        assert req.business_status == "abnormal"

    def test_task_run_report_request_business_status_defaults_none(self) -> None:
        from AutoGLM_GUI.sync.schemas import TaskRunReportRequest

        req = TaskRunReportRequest(
            task_run_id="tr3",
            source="chat",
            device_serial="s1",
            status="succeeded",
            input_text="hello",
            step_count=1,
            started_at="2025-01-01T00:00:00Z",
            finished_at="2025-01-01T00:01:00Z",
            duration_ms=60000,
        )
        assert req.business_status is None

    def test_task_run_report_request_business_status_rejects_invalid(self) -> None:
        from pydantic import ValidationError

        from AutoGLM_GUI.sync.schemas import TaskRunReportRequest

        with pytest.raises(ValidationError):
            TaskRunReportRequest(
                task_run_id="tr4",
                source="chat",
                device_serial="s1",
                status="succeeded",
                input_text="hello",
                step_count=1,
                started_at="2025-01-01T00:00:00Z",
                finished_at="2025-01-01T00:01:00Z",
                duration_ms=60000,
                business_status="weird",
            )


# ============================================================================
# 3. task_store business_status persistence (Task 14)
# ============================================================================


def test_task_store_persists_business_status_via_update_task_terminal(
    tmp_path: Path,
) -> None:
    """update_task_terminal writes business_status into the task row."""
    store = TaskStore(tmp_path / "tasks.db")
    task = store.create_task_run(
        source="chat",
        executor_key="classic_chat",
        device_id="d1",
        device_serial="s1",
        input_text="hello",
    )
    # Initially NULL
    assert task["business_status"] is None

    store.update_task_terminal(
        task_id=task["id"],
        status=TaskStatus.SUCCEEDED.value,
        final_message="done",
        error_message=None,
        stop_reason="completed",
        step_count=3,
        business_status="ok",
    )

    refreshed = store.get_task(task["id"])
    assert refreshed is not None
    assert refreshed["business_status"] == "ok"
    assert refreshed["status"] == TaskStatus.SUCCEEDED.value
    store.close()


def test_task_store_update_business_status_standalone(tmp_path: Path) -> None:
    """update_task_business_status updates only the business_status column."""
    store = TaskStore(tmp_path / "tasks.db")
    task = store.create_task_run(
        source="chat",
        executor_key="classic_chat",
        device_id="d1",
        device_serial="s1",
        input_text="hello",
    )

    updated = store.update_task_business_status(task["id"], "abnormal")
    assert updated is not None
    assert updated["business_status"] == "abnormal"
    # status should remain QUEUED (no side effect)
    assert updated["status"] == TaskStatus.QUEUED.value

    # Clearing back to NULL is allowed
    cleared = store.update_task_business_status(task["id"], None)
    assert cleared is not None
    assert cleared["business_status"] is None
    store.close()


def test_task_store_create_task_run_with_initial_business_status(
    tmp_path: Path,
) -> None:
    """create_task_run accepts initial business_status (used by reporters/tests)."""
    store = TaskStore(tmp_path / "tasks.db")
    task = store.create_task_run(
        source="scheduled",
        executor_key="scheduled_workflow",
        device_id="d1",
        device_serial="s1",
        input_text="hello",
        business_status="ok",
    )
    assert task["business_status"] == "ok"
    store.close()


# ============================================================================
# 4. _execute_classic_chat step loop (Tasks 11 & 12)
# ============================================================================
#
# These are end-to-end tests through TaskManager._execute_classic_chat, with
# PhoneAgentManager / workflow_manager monkeypatched so we control the agent
# stream output and the workflow steps returned.


def _build_step_workflow(
    *,
    uuid: str = "wf-test-uuid",
    text: str = "巡视任务",
    steps: list[dict[str, Any]] | None = None,
) -> WorkflowRecord:
    record: WorkflowRecord = {"uuid": uuid, "name": "巡检", "text": text}
    if steps is not None:
        record["steps"] = steps  # type: ignore[typeddict-item]
    return record


class _FakeAgent:
    """Fake agent whose ``stream`` yields scripted events per call.

    ``scripts`` is a list whose i-th element is the list of events to yield
    on the (i+1)-th call to ``stream``. The agent also records every call's
    instruction text so tests can assert ordering and stop conditions.
    """

    def __init__(self, scripts: list[list[dict[str, Any]]]) -> None:
        self._scripts = list(scripts)
        self.calls: list[str] = []
        self.reset_count = 0
        self.cancel_count = 0

    def reset(self) -> None:
        self.reset_count += 1

    async def cancel(self) -> None:
        self.cancel_count += 1

    def set_user_image_attachments(self, _: object) -> None:  # pragma: no cover
        pass

    async def stream(
        self, instruction: str, **_: object
    ) -> AsyncIterator[dict[str, Any]]:
        self.calls.append(instruction)
        # Pop the next script; if exhausted, default to a success done event.
        if self._scripts:
            events = self._scripts.pop(0)
        else:  # pragma: no cover - safety net
            events = [{"type": "done", "data": {"message": "PASS", "success": True}}]
        for event in events:
            yield event


class _FakePhoneAgentManager:
    """Minimal PhoneAgentManager stub satisfying _execute_classic_chat needs."""

    def __init__(self, agent: _FakeAgent) -> None:
        self._agent = agent

    @classmethod
    def get_instance(cls) -> _FakePhoneAgentManager:
        # Returned via monkeypatch; instance is bound there.
        raise NotImplementedError

    async def acquire_device_async(
        self,
        device_id: str,
        auto_initialize: bool = False,
        context: str = "default",
    ) -> bool:
        return True

    async def get_agent_with_context_async(
        self,
        device_id: str,
        context: str = "default",
        agent_type: str | None = None,
    ) -> _FakeAgent:
        return self._agent

    async def register_abort_handler_async(
        self,
        device_id: str,
        handler: object,
        context: str = "default",
    ) -> None:
        return None

    async def unregister_abort_handler_async(
        self, device_id: str, context: str = "default"
    ) -> None:
        return None

    async def set_error_state_async(
        self, device_id: str, error_message: str, context: str = "default"
    ) -> None:
        return None

    async def release_device_async(
        self, device_id: str, context: str = "default"
    ) -> None:
        return None


def _done_event(message: str, success: bool = True, steps: int = 1) -> dict[str, Any]:
    return {
        "type": "done",
        "data": {"message": message, "success": success, "steps": steps},
    }


def _make_task_record(
    store: TaskStore,
    *,
    workflow_uuid: str | None = None,
    input_text: str = "巡视",
) -> dict[str, Any]:
    return store.create_task_run(
        source="chat",
        executor_key="classic_chat",
        device_id="d1",
        device_serial="s1",
        input_text=input_text,
        workflow_uuid=workflow_uuid,
    )


def _patch_classic_chat_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    agent: _FakeAgent,
    workflow: WorkflowRecord | None,
) -> _FakePhoneAgentManager:
    """Wire up PhoneAgentManager and workflow_manager for _execute_classic_chat."""
    import AutoGLM_GUI.phone_agent_manager as phone_module
    import AutoGLM_GUI.task_manager as task_manager_module
    import AutoGLM_GUI.workflow_manager as workflow_module

    fake_manager = _FakePhoneAgentManager(agent)
    monkeypatch.setattr(
        phone_module.PhoneAgentManager,
        "get_instance",
        staticmethod(lambda: fake_manager),
    )
    # task_manager imports PhoneAgentManager lazily inside the function, but
    # patching the class attribute is enough because the import binds the
    # same class object.

    def fake_get_workflow(uuid: str) -> WorkflowRecord | None:
        if workflow is None:
            return None
        if workflow["uuid"] != uuid:
            return None
        return workflow

    monkeypatch.setattr(
        workflow_module.workflow_manager, "get_workflow", fake_get_workflow
    )
    # Also patch the symbol imported inside _execute_classic_chat
    monkeypatch.setattr(
        task_manager_module,
        # The function does: from AutoGLM_GUI.workflow_manager import workflow_manager
        # We patch the source module's attribute (already done above) so the
        # late import picks up our patched instance.
        "_TASK_MANAGER_PATCH_MARKER",
        True,
        raising=False,
    )
    return fake_manager


def _run_classic_chat(task: dict[str, Any], manager: TaskManager) -> None:
    asyncio.run(manager._execute_classic_chat(task))


# ----------------------------------------------------------------------------
# SubTask 16.1: 3 action + 2 assertion all pass → business_status=ok
# ----------------------------------------------------------------------------


def test_classic_chat_all_steps_pass_business_status_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    steps = [
        {"step_order": 1, "step_type": "action", "step_name": "action-1"},
        {"step_order": 2, "step_type": "action", "step_name": "action-2"},
        {"step_order": 3, "step_type": "action", "step_name": "action-3"},
        {"step_order": 4, "step_type": "assertion", "step_name": "assert-1"},
        {"step_order": 5, "step_type": "assertion", "step_name": "assert-2"},
    ]
    workflow = _build_step_workflow(steps=steps)

    # 5 successful streams; assertions include PASS in message.
    scripts = [
        [_done_event("action-1 ok", success=True, steps=1)],
        [_done_event("action-2 ok", success=True, steps=1)],
        [_done_event("action-3 ok", success=True, steps=1)],
        [_done_event("PASS: count=10", success=True, steps=1)],
        [_done_event("PASS: latency=20ms", success=True, steps=1)],
    ]
    agent = _FakeAgent(scripts)
    _patch_classic_chat_dependencies(monkeypatch, agent=agent, workflow=workflow)

    store = TaskStore(tmp_path / "tasks.db")
    manager = TaskManager(store)
    task = _make_task_record(store, workflow_uuid=workflow["uuid"])

    _run_classic_chat(task, manager)

    final = store.get_task(task["id"])
    assert final is not None
    assert final["status"] == TaskStatus.SUCCEEDED.value
    assert final["business_status"] == "ok"
    assert final["stop_reason"] == "completed"
    # step_count is the max of the per-step "steps" field (each=1 → 1),
    # then overwritten by the last done event's "steps" (=1).
    assert final["step_count"] == 1

    # agent.stream called once per step (5 times)
    assert agent.calls == [
        "action-1",
        "action-2",
        "action-3",
        "assert-1",
        "assert-2",
    ]
    # agent.reset called once per step (5 times)
    assert agent.reset_count == 5
    store.close()


# ----------------------------------------------------------------------------
# SubTask 16.2: assertion fails at step 3 → business_status=abnormal, steps 4/5 skipped
# ----------------------------------------------------------------------------


def test_classic_chat_assertion_failure_stops_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    steps = [
        {"step_order": 1, "step_type": "action", "step_name": "action-1"},
        {"step_order": 2, "step_type": "action", "step_name": "action-2"},
        {"step_order": 3, "step_type": "assertion", "step_name": "assert-1"},
        {"step_order": 4, "step_type": "action", "step_name": "action-4"},
        {"step_order": 5, "step_type": "assertion", "step_name": "assert-2"},
    ]
    workflow = _build_step_workflow(steps=steps)

    scripts = [
        [_done_event("action-1 ok", success=True, steps=1)],
        [_done_event("action-2 ok", success=True, steps=1)],
        # Step 3 assertion fails: success stays True (agent ran fine),
        # but the message starts with FAIL so step_passed=False.
        [_done_event("FAIL: expected >0, actual 0", success=True, steps=1)],
        # Steps 4-5 scripts are present but should NEVER be consumed.
        [_done_event("action-4 ok", success=True, steps=1)],
        [_done_event("PASS", success=True, steps=1)],
    ]
    agent = _FakeAgent(scripts)
    _patch_classic_chat_dependencies(monkeypatch, agent=agent, workflow=workflow)

    store = TaskStore(tmp_path / "tasks.db")
    manager = TaskManager(store)
    task = _make_task_record(store, workflow_uuid=workflow["uuid"])

    _run_classic_chat(task, manager)

    final = store.get_task(task["id"])
    assert final is not None
    assert final["status"] == TaskStatus.SUCCEEDED.value
    assert final["business_status"] == "abnormal"
    assert final["stop_reason"] == "assertion_failed"
    assert agent.calls == ["action-1", "action-2", "assert-1"]
    assert agent.reset_count == 3
    store.close()


# ----------------------------------------------------------------------------
# SubTask 16.3: legacy workflow without steps → single action, no assertion
# ----------------------------------------------------------------------------


def test_classic_chat_legacy_workflow_without_steps_falls_back_to_single_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Legacy workflow: only text, no steps.
    workflow = _build_step_workflow(text="legacy-task-text", steps=None)

    scripts = [[_done_event("legacy done", success=True, steps=1)]]
    agent = _FakeAgent(scripts)
    _patch_classic_chat_dependencies(monkeypatch, agent=agent, workflow=workflow)

    store = TaskStore(tmp_path / "tasks.db")
    manager = TaskManager(store)
    task = _make_task_record(
        store,
        workflow_uuid=workflow["uuid"],
        input_text="user-input-text",
    )

    _run_classic_chat(task, manager)

    final = store.get_task(task["id"])
    assert final is not None
    assert final["status"] == TaskStatus.SUCCEEDED.value
    # No assertion → business_status stays None (no assertion encountered)
    assert final["business_status"] is None
    assert final["stop_reason"] == "completed"
    # agent.stream called exactly once, with workflow["text"] (legacy behavior:
    # when there are no steps, we synthesize a single action using input_text
    # from the task record).
    assert agent.calls == ["user-input-text"]
    assert agent.reset_count == 1
    store.close()


def test_classic_chat_no_workflow_uuid_falls_back_to_single_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When task has no workflow_uuid, fall back to a single action step."""
    # workflow_manager.get_workflow never gets called meaningfully; pass None.
    scripts = [[_done_event("plain chat done", success=True, steps=2)]]
    agent = _FakeAgent(scripts)
    _patch_classic_chat_dependencies(monkeypatch, agent=agent, workflow=None)

    store = TaskStore(tmp_path / "tasks.db")
    manager = TaskManager(store)
    task = _make_task_record(store, workflow_uuid=None, input_text="hi there")

    _run_classic_chat(task, manager)

    final = store.get_task(task["id"])
    assert final is not None
    assert final["status"] == TaskStatus.SUCCEEDED.value
    assert final["business_status"] is None
    assert final["stop_reason"] == "completed"
    assert agent.calls == ["hi there"]
    # step_count taken from the done event's "steps" field (=2)
    assert final["step_count"] == 2
    store.close()


# ----------------------------------------------------------------------------
# SubTask 16.4: assertion message unparseable → treated as FAIL
# ----------------------------------------------------------------------------


def test_classic_chat_unparseable_assertion_treated_as_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    steps = [
        {"step_order": 1, "step_type": "action", "step_name": "action-1"},
        {"step_order": 2, "step_type": "assertion", "step_name": "assert-1"},
        {"step_order": 3, "step_type": "action", "step_name": "action-3"},
    ]
    workflow = _build_step_workflow(steps=steps)

    scripts = [
        [_done_event("action-1 ok", success=True, steps=1)],
        # Assertion message contains neither PASS nor FAIL
        [_done_event("无法确定的文本", success=True, steps=1)],
        # Should never run
        [_done_event("action-3 ok", success=True, steps=1)],
    ]
    agent = _FakeAgent(scripts)
    _patch_classic_chat_dependencies(monkeypatch, agent=agent, workflow=workflow)

    store = TaskStore(tmp_path / "tasks.db")
    manager = TaskManager(store)
    task = _make_task_record(store, workflow_uuid=workflow["uuid"])

    _run_classic_chat(task, manager)

    final = store.get_task(task["id"])
    assert final is not None
    assert final["status"] == TaskStatus.SUCCEEDED.value
    assert final["business_status"] == "abnormal"
    assert final["stop_reason"] == "assertion_failed"
    assert agent.calls == ["action-1", "assert-1"]
    store.close()


# ----------------------------------------------------------------------------
# Extra: action failure → task FAILED, business_status=None (Task 11.3)
# ----------------------------------------------------------------------------


def test_classic_chat_action_failure_marks_task_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    steps = [
        {"step_order": 1, "step_type": "action", "step_name": "action-1"},
        {"step_order": 2, "step_type": "assertion", "step_name": "assert-1"},
    ]
    workflow = _build_step_workflow(steps=steps)

    scripts = [
        # action step fails (success=False)
        [_done_event("action crashed", success=False, steps=1)],
        # assertion step should not be reached
        [_done_event("PASS", success=True, steps=1)],
    ]
    agent = _FakeAgent(scripts)
    _patch_classic_chat_dependencies(monkeypatch, agent=agent, workflow=workflow)

    store = TaskStore(tmp_path / "tasks.db")
    manager = TaskManager(store)
    task = _make_task_record(store, workflow_uuid=workflow["uuid"])

    _run_classic_chat(task, manager)

    final = store.get_task(task["id"])
    assert final is not None
    assert final["status"] == TaskStatus.FAILED.value
    assert final["business_status"] is None
    assert final["stop_reason"] == "action_failed"
    assert agent.calls == ["action-1"]
    store.close()


# ----------------------------------------------------------------------------
# Extra: step event payload standardization (Task 12.1 / 12.2)
# ----------------------------------------------------------------------------


def test_classic_chat_step_events_carry_step_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """done events for each step must carry step_type / step_order / step_name."""
    steps = [
        {"step_order": 1, "step_type": "action", "step_name": "open-app"},
        {"step_order": 2, "step_type": "assertion", "step_name": "count-gt-0"},
    ]
    workflow = _build_step_workflow(steps=steps)

    scripts = [
        [_done_event("ok", success=True, steps=1)],
        [_done_event("PASS", success=True, steps=1)],
    ]
    agent = _FakeAgent(scripts)
    _patch_classic_chat_dependencies(monkeypatch, agent=agent, workflow=workflow)

    store = TaskStore(tmp_path / "tasks.db")
    manager = TaskManager(store)
    task = _make_task_record(store, workflow_uuid=workflow["uuid"])

    _run_classic_chat(task, manager)

    events = store.list_task_events(task["id"])
    done_events = [e for e in events if e["event_type"] == "done"]
    # Two step done events are emitted (one per step). _finalize_task
    # de-duplicates: when a done event already exists, it does not append
    # another finalize done event. So we expect exactly 2 done events here.
    assert len(done_events) == 2

    step_done_1 = done_events[0]["payload"]
    assert step_done_1["step_type"] == "action"
    assert step_done_1["step_order"] == 1
    assert step_done_1["step_name"] == "open-app"
    assert step_done_1["passed"] is True
    # action steps don't populate "actual" meaningfully
    assert step_done_1["actual"] == ""

    step_done_2 = done_events[1]["payload"]
    assert step_done_2["step_type"] == "assertion"
    assert step_done_2["step_order"] == 2
    assert step_done_2["step_name"] == "count-gt-0"
    assert step_done_2["passed"] is True
    store.close()
