"""Scheduled task manager with APScheduler."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self
from uuid import uuid4

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from AutoGLM_GUI.logger import logger
from AutoGLM_GUI.models.scheduled_task import ScheduledTask

if TYPE_CHECKING:
    pass

# 断言步骤 prompt 约束：强制模型在回复末尾输出 PASS 或 FAIL
_ASSERTION_SUFFIX = (
    "\n\n【重要】你必须在回复的最后一行，单独输出一行，内容仅为以下之一："
    "\n- 如果断言成立，输出：RESULT: PASS"
    "\n- 如果断言不成立，输出：RESULT: FAIL"
    "\n不要遗漏这行结果标识。严格按照以上格式输出。"
)


@dataclass
class DeviceExecutionResult:
    serialno: str
    success: bool
    message: str
    device_model: str = ""
    # 业务状态：ok / abnormal / None（未涉及 assertion）
    business_status: str | None = None
    # 停止原因：action_failed / assertion_failed / None（正常完成）
    stop_reason: str | None = None
    # 执行步骤数
    step_count: int = 0


class SchedulerManager:
    _instance: Self | None = None

    def __new__(cls: type[Self]) -> Self:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._tasks_path = Path.home() / ".config" / "autoglm" / "scheduled_tasks.json"
        self._scheduler = AsyncIOScheduler()
        self._tasks: dict[str, ScheduledTask] = {}
        self._file_mtime: float | None = None

    async def start(self) -> None:
        self._load_tasks()
        for task in self._tasks.values():
            if task.enabled:
                self._add_job(task)
        self._scheduler.start()
        logger.info(f"SchedulerManager started with {len(self._tasks)} task(s)")

    async def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)
        logger.info("SchedulerManager shutdown")

    def create_task(
        self,
        name: str,
        workflow_uuid: str,
        device_serialnos: list[str] | None,
        cron_expression: str,
        enabled: bool = True,
        device_group_id: str | None = None,
        execution_mode: str = "classic",
    ) -> ScheduledTask:
        task = ScheduledTask(
            name=name,
            workflow_uuid=workflow_uuid,
            device_serialnos=device_serialnos or [],
            device_group_id=device_group_id,
            cron_expression=cron_expression,
            enabled=enabled,
            execution_mode=execution_mode,
        )
        self._tasks[task.id] = task
        self._save_tasks()

        if enabled:
            self._add_job(task)

        logger.info(f"Created scheduled task: {name} (id={task.id})")
        return task

    def update_task(self, task_id: str, **kwargs: Any) -> ScheduledTask | None:
        task = self._tasks.get(task_id)
        if not task:
            return None

        old_enabled = task.enabled
        old_cron = task.cron_expression

        for key, value in kwargs.items():
            if value is not None and hasattr(task, key):
                setattr(task, key, value)

        task.updated_at = datetime.now(tz=timezone.utc)
        self._save_tasks()

        if old_enabled and not task.enabled:
            self._remove_job(task_id)
        elif not old_enabled and task.enabled:
            self._add_job(task)
        elif task.enabled and old_cron != task.cron_expression:
            self._remove_job(task_id)
            self._add_job(task)

        logger.info(f"Updated scheduled task: {task.name} (id={task_id})")
        return task

    def delete_task(self, task_id: str) -> bool:
        task = self._tasks.pop(task_id, None)
        if not task:
            return False

        self._remove_job(task_id)
        self._save_tasks()
        logger.info(f"Deleted scheduled task: {task.name} (id={task_id})")
        return True

    def list_tasks(self) -> list[ScheduledTask]:
        return list(self._tasks.values())

    def get_task(self, task_id: str) -> ScheduledTask | None:
        return self._tasks.get(task_id)

    def set_enabled(self, task_id: str, enabled: bool) -> bool:
        task = self._tasks.get(task_id)
        if not task:
            return False

        if task.enabled == enabled:
            return True

        task.enabled = enabled
        task.updated_at = datetime.now(tz=timezone.utc)
        self._save_tasks()

        if enabled:
            self._add_job(task)
        else:
            self._remove_job(task_id)

        logger.info(f"{'Enabled' if enabled else 'Disabled'} task: {task.name}")
        return True

    def get_next_run_time(self, task_id: str) -> datetime | None:
        job = self._scheduler.get_job(task_id)
        if job and job.next_run_time:
            return job.next_run_time.replace(tzinfo=None)
        return None

    def _add_job(self, task: ScheduledTask) -> None:
        try:
            parts = task.cron_expression.split()
            # 兼容 Quartz 6 段格式（秒 分 时 日 月 周）：丢弃秒位，转为 5 段
            if len(parts) == 6:
                parts = parts[1:]
            if len(parts) != 5:
                logger.error(f"Invalid cron expression: {task.cron_expression}")
                return

            # 兼容 Quartz 的 "?"（不指定），APScheduler 用 "*" 表示任意
            parts = [p.replace("?", "*") for p in parts]

            trigger = CronTrigger(
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
                month=parts[3],
                day_of_week=parts[4],
            )

            self._scheduler.add_job(
                self._execute_task,
                trigger=trigger,
                id=task.id,
                args=[task.id],
                replace_existing=True,
            )
            logger.debug(f"Added job for task: {task.name}")
        except Exception as e:
            logger.error(f"Failed to add job for task {task.name}: {e}")

    def _remove_job(self, task_id: str) -> None:
        try:
            if self._scheduler.get_job(task_id):
                self._scheduler.remove_job(task_id)
                logger.debug(f"Removed job: {task_id}")
        except Exception as e:
            logger.warning(f"Failed to remove job {task_id}: {e}")

    async def _execute_single_device(
        self,
        serialno: str,
        workflow: dict[str, Any],
        task_name: str,
        manager: Any,
        device_manager: Any,
        history_manager: Any,
    ) -> DeviceExecutionResult:
        from AutoGLM_GUI.models.history import ConversationRecord, MessageRecord

        device = None
        for d in device_manager.get_devices():
            if d.serial == serialno and d.state.value == "online":
                device = d
                break

        if not device:
            return DeviceExecutionResult(
                serialno=serialno,
                success=False,
                message="Device offline",
                device_model="",
            )

        acquired = await manager.acquire_device_async(
            device.primary_device_id,
            timeout=0,
            raise_on_timeout=False,
            auto_initialize=True,
        )

        if not acquired:
            return DeviceExecutionResult(
                serialno=serialno,
                success=False,
                message="Device busy",
                device_model=device.model or serialno,
            )

        # SubTask 11.1: 解析 workflow steps；无 steps 时退化为单一 action 步骤
        workflow_steps_raw = workflow.get("steps") or []
        if not workflow_steps_raw:
            # 旧版兼容：仅 text 字段，退化为单一 action 步骤
            workflow_steps = [
                {
                    "step_order": 1,
                    "step_type": "action",
                    "step_name": workflow["text"],
                }
            ]
        else:
            # 按 step_order 升序排序
            workflow_steps = sorted(
                workflow_steps_raw, key=lambda s: s.get("step_order", 0)
            )

        workflow_text = workflow.get("text", "") or (
            workflow_steps[0].get("step_name", "") if workflow_steps else ""
        )

        start_time = datetime.now(tz=timezone.utc)
        # 初始 user 消息携带完整 workflow 文本，保持向后兼容
        messages: list[MessageRecord] = [
            MessageRecord(
                role="user",
                content=workflow_text,
                timestamp=start_time,
            )
        ]

        # SubTask 11.2 - 11.6: 按步骤循环执行
        business_status: str | None = None
        stop_reason: str | None = None
        step_count = 0
        result_message = ""
        task_success = False
        # 是否出现过 assertion 步骤；若有则业务状态需明确（ok/abnormal），否则为 None
        has_assertion = False

        try:
            agent: Any = await manager.get_agent_async(device.primary_device_id)

            for step in workflow_steps:
                step_type = step.get("step_type", "action")
                step_name = step.get("step_name", "")
                step_order = step.get("step_order", step_count + 1)

                if step_type == "assertion":
                    has_assertion = True
                    # 默认业务状态：在出现 assertion 后初始化为 ok，失败时改为 abnormal
                    if business_status is None:
                        business_status = "ok"
                    # 追加 prompt 约束，强制模型返回 PASS/FAIL 标识
                    step_name = "断言" + step_name + _ASSERTION_SUFFIX

                # 每步独立重置 agent 状态
                agent.reset()

                step_passed = True
                step_actual = ""
                step_result_message = ""

                async for event in agent.stream(step_name):
                    event_type = event["type"]
                    step_data: dict[str, Any] = event.get("data", {}) or {}

                    if event_type == "step":
                        # SubTask 12.1 & 12.2: step 事件 payload 标准化字段
                        messages.append(
                            MessageRecord(
                                role="assistant",
                                content="",
                                timestamp=datetime.now(tz=timezone.utc),
                                thinking=step_data.get("thinking", ""),
                                action=step_data.get("action", {}),
                                step=step_data.get("step", step_count),
                                step_type=step_type,
                                step_order=step_order,
                                step_name=step_name,
                                step_passed=None,  # 中间步骤尚未结束，暂不判定
                            )
                        )
                    elif event_type == "done":
                        step_result_message = step_data.get("message", "Step completed")
                        task_success = step_data.get("success", False)

                        # assertion 步骤需要解析 final_message 判定 PASS/FAIL
                        if step_type == "assertion":
                            msg_upper = step_result_message.upper()
                            if "PASS" in msg_upper:
                                step_passed = True
                            elif "FAIL" in msg_upper:
                                step_passed = False
                                step_actual = step_result_message
                            else:
                                # keyword 匹配失败，尝试用决策模型判断
                                from AutoGLM_GUI.task_manager import _judge_assertion_with_decision_model

                                judge_result = await _judge_assertion_with_decision_model(
                                    step_name, step_result_message
                                )
                                logger.info(f"Assertion step {step_name} judge result: {judge_result}")
                                if judge_result is True:
                                    step_passed = True
                                elif judge_result is False:
                                    step_passed = False
                                    step_actual = step_result_message
                                else:
                                    # 无决策模型或判断失败，保守按 FAIL 处理
                                    step_passed = False
                                    step_actual = (
                                        f"Unable to parse assertion result: "
                                        f"{step_result_message}"
                                    )
                            # 更新最后一条 step 消息的判定结果
                            if messages and messages[-1].role == "assistant":
                                messages[-1].step_passed = step_passed
                                messages[-1].step_actual = step_actual
                        else:
                            # action 步骤通过即视为 passed
                            if messages and messages[-1].role == "assistant":
                                messages[-1].step_passed = task_success
                        break
                    elif event_type == "error":
                        step_result_message = step_data.get("message", "Step failed")
                        task_success = False
                        if messages and messages[-1].role == "assistant":
                            messages[-1].step_passed = False
                            messages[-1].step_actual = step_result_message
                        break

                step_count += 1
                result_message = step_result_message or result_message

                # SubTask 11.3: action 步骤失败 → 任务 failed，停止循环
                if step_type == "action" and not task_success:
                    stop_reason = "action_failed"
                    business_status = None  # action 失败不涉及业务断言
                    break

                # SubTask 11.4 & 11.5: assertion 步骤失败 → 立即中断，business_status=abnormal
                if step_type == "assertion" and not step_passed:
                    business_status = "abnormal"
                    stop_reason = "assertion_failed"
                    result_message = (
                        f"Assertion failed at step {step_order}: {step_actual}"
                    )
                    break

            # SubTask 11.6: 所有步骤通过 → business_status=ok（仅当出现过 assertion 时）
            if stop_reason is None:
                task_success = True
                if has_assertion:
                    business_status = "ok"
                if not result_message:
                    result_message = "All steps completed successfully"

            steps = step_count
            end_time = datetime.now(tz=timezone.utc)
            device_model = device.model or serialno

            record = ConversationRecord(
                task_text=workflow_text,
                final_message=result_message,
                success=task_success,
                steps=steps,
                start_time=start_time,
                end_time=end_time,
                duration_ms=int((end_time - start_time).total_seconds() * 1000),
                source="scheduled",
                source_detail=f"{task_name} [{device_model}]",
                error_message=None if task_success else result_message,
                messages=messages,
            )
            await asyncio.to_thread(history_manager.add_record, serialno, record)

            return DeviceExecutionResult(
                serialno=serialno,
                success=task_success,
                message=result_message,
                device_model=device_model,
                business_status=business_status,
                stop_reason=stop_reason,
                step_count=steps,
            )

        except Exception as e:
            end_time = datetime.now(tz=timezone.utc)
            error_msg = str(e)
            device_model = device.model or serialno

            record = ConversationRecord(
                task_text=workflow_text,
                final_message=error_msg,
                success=False,
                steps=step_count,
                start_time=start_time,
                end_time=end_time,
                duration_ms=int((end_time - start_time).total_seconds() * 1000),
                source="scheduled",
                source_detail=f"{task_name} [{device_model}]",
                error_message=error_msg,
                messages=messages,
            )
            await asyncio.to_thread(history_manager.add_record, serialno, record)

            return DeviceExecutionResult(
                serialno=serialno,
                success=False,
                message=error_msg,
                device_model=device_model,
                business_status=business_status,
                stop_reason=stop_reason,
                step_count=step_count,
            )

        finally:
            await manager.release_device_async(device.primary_device_id)

    def _resolve_device_serialnos(self, task: ScheduledTask) -> list[str]:
        """解析任务的目标设备列表.

        如果指定了 device_group_id，则从分组获取设备列表；
        否则使用 device_serialnos 字段。
        """
        if task.device_group_id:
            from AutoGLM_GUI.device_group_manager import device_group_manager
            from AutoGLM_GUI.device_manager import DeviceManager

            device_manager = DeviceManager.get_instance()

            # 获取分组内的所有设备
            if task.device_group_id == "default":
                # 默认分组：获取所有未分配到其他分组的设备
                assignments = device_group_manager.get_all_assignments()
                assigned_serials = {
                    s for s, gid in assignments.items() if gid != "default"
                }
                managed_devices = device_manager.get_devices()
                return [
                    d.serial
                    for d in managed_devices
                    if d.serial not in assigned_serials
                ]
            else:
                # 其他分组：从分配中获取
                return device_group_manager.get_devices_in_group(task.device_group_id)
        else:
            return task.device_serialnos

    async def _execute_task(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if not task:
            logger.warning(f"Task {task_id} not found for execution")
            return

        # 解析目标设备列表
        device_serialnos = self._resolve_device_serialnos(task)

        logger.info(
            f"Executing scheduled task: {task.name} on {len(device_serialnos)} device(s)"
        )

        from AutoGLM_GUI.device_manager import DeviceManager
        from AutoGLM_GUI.task_manager import task_manager
        from AutoGLM_GUI.task_store import TaskStatus, task_store
        from AutoGLM_GUI.workflow_manager import workflow_manager

        workflow = workflow_manager.get_workflow(task.workflow_uuid)
        if not workflow:
            self._record_run(
                task=task,
                status="failure",
                message="Workflow not found",
                success_count=0,
                total_count=len(device_serialnos),
            )
            return

        device_manager = DeviceManager.get_instance()

        total_count = len(device_serialnos)
        if total_count == 0:
            self._record_run(
                task=task,
                status="failure",
                message="No devices selected",
                success_count=0,
                total_count=0,
            )
            return

        online_devices = {
            device.serial: device
            for device in device_manager.get_devices()
            if device.state.value == "online"
        }

        schedule_fire_id = str(uuid4())
        created_count = 0
        executor_key = (
            "scheduled_layered_workflow"
            if task.execution_mode == "layered"
            else "scheduled_workflow"
        )
        for serialno in device_serialnos:
            device = online_devices.get(serialno)
            if device is None:
                message = "Device offline"
                failed_task = await asyncio.to_thread(
                    task_store.create_task_run,
                    source="scheduled",
                    executor_key=executor_key,
                    scheduled_task_id=task.id,
                    workflow_uuid=task.workflow_uuid,
                    schedule_fire_id=schedule_fire_id,
                    device_id=serialno,
                    device_serial=serialno,
                    input_text=workflow["text"],
                )
                await asyncio.to_thread(
                    task_store.append_event,
                    task_id=failed_task["id"],
                    event_type="error",
                    payload={"message": message},
                )
                await asyncio.to_thread(
                    task_store.update_task_terminal,
                    task_id=failed_task["id"],
                    status=TaskStatus.FAILED.value,
                    final_message=message,
                    error_message=message,
                    step_count=0,
                )
                logger.warning(
                    f"Scheduled task {task.name} skipped offline device {serialno}"
                )
                continue

            await task_manager.enqueue_scheduled_task(
                scheduled_task_id=task.id,
                workflow_uuid=task.workflow_uuid,
                device_id=device.primary_device_id,
                device_serial=device.serial,
                input_text=workflow["text"],
                schedule_fire_id=schedule_fire_id,
                executor_key=executor_key,
            )
            created_count += 1

        if created_count == 0:
            self._record_run(
                task=task,
                status="failure",
                message="No online devices available",
                success_count=0,
                total_count=total_count,
            )
            return

        logger.info(
            f"Scheduled task {task.name} enqueued {created_count}/{total_count} task run(s)"
        )

    def _record_run(
        self,
        task: ScheduledTask,
        status: str,
        message: str,
        success_count: int,
        total_count: int,
    ) -> None:
        task.last_run_time = datetime.now(tz=timezone.utc)
        task.last_run_status = status
        task.last_run_success = status == "success"
        task.last_run_success_count = success_count
        task.last_run_total_count = total_count
        task.last_run_message = message[:500] if message else ""
        self._save_tasks()
        if status == "success":
            logger.info(f"Scheduled task completed: {task.name}")
        elif status == "partial":
            logger.warning(f"Scheduled task partially succeeded: {task.name}")
        else:
            logger.warning(f"Scheduled task failed: {task.name} - {message}")

    def _load_tasks(self) -> None:
        if not self._tasks_path.exists():
            return

        try:
            with open(self._tasks_path, encoding="utf-8") as f:
                data = json.load(f)
            tasks_data = data.get("tasks", [])
            self._tasks = {t["id"]: ScheduledTask.from_dict(t) for t in tasks_data}
            self._file_mtime = self._tasks_path.stat().st_mtime
            logger.debug(f"Loaded {len(self._tasks)} scheduled tasks")
        except Exception as e:
            logger.warning(f"Failed to load scheduled tasks: {e}")

    def _save_tasks(self) -> None:
        self._tasks_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._tasks_path.with_suffix(".tmp")

        try:
            data = {"tasks": [t.to_dict() for t in self._tasks.values()]}
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            temp_path.replace(self._tasks_path)
            self._file_mtime = self._tasks_path.stat().st_mtime
            logger.debug(f"Saved {len(self._tasks)} scheduled tasks")
        except Exception as e:
            logger.error(f"Failed to save scheduled tasks: {e}")
            if temp_path.exists():
                temp_path.unlink()


scheduler_manager = SchedulerManager()
