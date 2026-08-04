# 计划：客户端同步任务记录时只同步定时任务，不同步 chat 类型

## 概述

当前客户端 `TaskReporter` 会将所有已完成的任务（包括 `chat` 和 `scheduled` 两种 source）都上报到服务端。需要修改为：只上报 `source="scheduled"` 的定时任务记录，不再上报 `source="chat"` 的聊天任务记录。

## 当前状态分析

### 任务上报流程

1. `TaskReporter._poll_loop()`（[task_reporter.py:242](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/sync/task_reporter.py#L242)）每 5 秒调用 `_check_and_report_completed_tasks()`
2. `_check_and_report_completed_tasks()`（[task_reporter.py:253](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/sync/task_reporter.py#L253)）调用 `task_store.list_recent_terminal_tasks(limit=10)` 获取最近终态任务
3. 对每个未上报的任务，依次调用 `report_task_run()` 和 `report_task_events()`
4. `list_recent_terminal_tasks()`（[task_store.py:892](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/task_store.py#L892)）查询所有终态任务，**不区分 source**

### source 字段取值

| source 值 | 含义 | 创建位置 |
|---|---|---|
| `"chat"` | 聊天任务 | task_manager.py:213 |
| `"scheduled"` | 定时任务 | task_manager.py:270, scheduler_manager.py:562 |

### 离线队列重放

`SyncManager._replay_offline_queue()`（[manager.py:201](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/sync/manager.py#L201)）会重放离线队列中的 `task_run` 和 `task_events` 类型项。如果 chat 任务在离线时被推入队列，重放时也会被上报。

## 修改方案

### 修改 1：`_check_and_report_completed_tasks` 中过滤 chat 任务

**文件**: `g:\workspace\AutoGLM-GUI\AutoGLM_GUI\sync\task_reporter.py`
**位置**: 第 253-268 行

在遍历 `recent_tasks` 时，跳过 `source == "chat"` 的任务记录：

```python
async def _check_and_report_completed_tasks(self) -> None:
    """Find recently completed tasks and report them."""
    if not self._client.is_registered:
        return
    try:
        recent_tasks = await asyncio.to_thread(
            self._task_store.list_recent_terminal_tasks, limit=10
        )
        for task_run in recent_tasks:
            task_id = task_run["id"]
            if task_id not in self._reported_tasks:
                # 只上报定时任务，不同步 chat 类型任务
                if task_run.get("source") == "chat":
                    self._reported_tasks.add(task_id)
                    continue
                success = await self.report_task_run(task_id)
                if success:
                    await self.report_task_events(task_id)
    except Exception as e:
        logger.error("Error checking completed tasks: %s", e)
```

**要点**：
- 对 chat 任务执行 `self._reported_tasks.add(task_id)`，将其标记为已上报，避免后续轮询重复检查
- 不修改 `list_recent_terminal_tasks` 的 SQL 查询，保持数据访问层通用性

### 修改 2：离线队列重放时跳过 chat 任务

**文件**: `g:\workspace\AutoGLM-GUI\AutoGLM_GUI\sync\manager.py`
**位置**: 第 214-218 行

在 `_replay_offline_queue` 中重放 `task_run` 类型时，检查 source 字段并跳过 chat 任务：

```python
if item.item_type == "task_run":
    from AutoGLM_GUI.sync.schemas import TaskRunReportRequest

    req = TaskRunReportRequest.model_validate(payload)
    # 只上报定时任务，跳过 chat 类型
    if req.source == "chat":
        self._offline_queue.pop(item.id)
        continue
    await self._client.report_task_run(req)
```

**要点**：
- 对 chat 任务的离线队列项直接 pop 丢弃，避免无限重试
- `TaskRunReportRequest` 的 `source` 字段类型为 `Literal["chat", "scheduled"]`（[schemas.py:181](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/sync/schemas.py#L181)），可直接判断

## 假设与决策

1. **不修改 `list_recent_terminal_tasks` 的 SQL**：保持数据访问层的通用性，过滤逻辑放在业务层（TaskReporter）
2. **chat 任务仍标记为已上报**：避免 `_reported_tasks` 集合无限增长和重复日志
3. **离线队列中的 chat 任务直接丢弃**：既然不再上报 chat 任务，已入队的 chat 任务也没有保留价值
4. **不修改 `report_task_run` 方法本身**：保持方法签名和行为的通用性，过滤逻辑在调用方处理

## 验证步骤

1. **Lint 检查**：`uv run ruff check AutoGLM_GUI/sync/task_reporter.py AutoGLM_GUI/sync/manager.py`
2. **格式检查**：`uv run ruff format --check AutoGLM_GUI/sync/task_reporter.py AutoGLM_GUI/sync/manager.py`
3. **单元测试**：`uv run pytest tests/ -k "reporter or sync" -v`（如有相关测试）
