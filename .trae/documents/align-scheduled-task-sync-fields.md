# 定时任务同步字段对齐 — 删除 workflow_uuid 并适配

## Summary

从 `patrol_scheduled_tasks` 表和客户端模型中删除 `workflow_uuid`，并在客户端定时任务执行逻辑中改用 `input_text` 字段直接存储指令文本，替代通过 `workflow_uuid` 间接查找的方式。

## Current State Analysis

### 服务端（falconconsole）
- `PatrolScheduledTask.java` 实体：已删除 `workflowUuid`，已添加 `executionMode`
- `ClientSyncController.ScheduledTaskSyncDTO`：已无 `workflowUuid` 字段
- `schema.sql` DDL：`patrol_scheduled_tasks` 表仍有 `workflow_uuid` 列（需删除）
- `patrol_task_runs` 表：仍有 `workflow_uuid` 列（保留，用于记录运行关联的工作流）

### 客户端（AutoGLM-GUI）
- `ScheduledTaskSyncItem`（sync/schemas.py）：已删除 `workflow_uuid`
- `ScheduledTask` 模型（models/scheduled_task.py）：已删除 `workflow_uuid`
- `_merge_scheduled_task`（sync/sync_pull.py）：已删除 `workflow_uuid`
- `scheduler_manager.create_task()`：已删除 `workflow_uuid` 参数

### 仍引用 workflow_uuid 的客户端文件
1. **`scheduler_manager.py` L375,421,448** — 执行逻辑通过 `task.workflow_uuid` 查找工作流文本
2. **`sync/push_channel.py` L177,179,204** — SSE dispatch 时通过 `task.workflow_uuid` 查找工作流文本
3. **`schemas.py` L905,961,1022,1076** — API schema 中 `TaskRunResponse.workflow_uuid`、`ScheduledTaskCreate.workflow_uuid`、`ScheduledTaskUpdate.workflow_uuid`、`ScheduledTaskResponse.workflow_uuid`
4. **`api/scheduled_tasks.py` L26,80,86** — 创建/响应时使用 `workflow_uuid`
5. **`api/tasks.py` L62-63** — `TaskRunResponse` 中映射 `workflow_uuid`
6. **`task_manager.py` L199,211** — `enqueue_scheduled_task()` 接收 `workflow_uuid`
7. **`task_store.py` L101,372,390,403,415** — SQLite DDL 和 `create_task_run()` 中有 `workflow_uuid`
8. **`sync/schemas.py` L161** — `TaskRunReportRequest.workflow_uuid`
9. **`sync/task_reporter.py` L89** — 上报时取 `workflow_uuid`
10. **`trace.py` L264** — trace 属性中包含 `workflow_uuid`

## Proposed Changes

### 核心设计决策

**删除 `workflow_uuid` 后，定时任务如何获取执行指令？**

方案：在 `ScheduledTask` 模型中新增 `input_text: str` 字段，服务端同步时也下发该字段。这样定时任务执行时直接使用 `task.input_text`，不再依赖 `WorkflowManager` 查找。

理由：
- 服务端 `patrol_scheduled_tasks` 表可新增 `input_text` 列存储指令文本
- 客户端不再需要维护本地 `WorkflowManager` 与 `scheduled_task` 的关联
- `input_text` 是任务运行时实际需要的唯一工作流数据
- 简化了执行链路：`task.input_text` 直接可用，无需间接查找

### Step 1: 服务端 — DDL 修改

**文件**: `falconconsole/src/main/resources/schema.sql`
- `patrol_scheduled_tasks` 表：删除 `workflow_uuid` 列，新增 `input_text TEXT DEFAULT NULL COMMENT '执行指令文本'`

**文件**: `docs/mysql.md`
- 更新 `patrol_scheduled_tasks` 表定义：删除 `workflow_uuid`，新增 `input_text`

### Step 2: 服务端 — 实体和 DTO 修改

**文件**: `falconconsole/.../entity/PatrolScheduledTask.java`
- 已删除 `workflowUuid`（已完成）
- 新增 `private String inputText;`

**文件**: `falconconsole/.../controller/ClientSyncController.java`
- `ScheduledTaskSyncDTO` 新增 `private String inputText;`
- `toScheduledTaskSyncDTO()` 方法中添加 `task.getInputText()` 映射
- `ScheduledTaskSyncDTO` 的 `@AllArgsConstructor` 构造器参数需同步更新

### Step 3: 客户端 — ScheduledTask 模型

**文件**: `AutoGLM_GUI/models/scheduled_task.py`
- 新增 `input_text: str = ""` 字段
- 更新 `to_dict()` 和 `from_dict()` 方法

### Step 4: 客户端 — 同步 schema

**文件**: `AutoGLM_GUI/sync/schemas.py`
- `ScheduledTaskSyncItem` 新增 `input_text: str = ""`

### Step 5: 客户端 — 同步拉取

**文件**: `AutoGLM_GUI/sync/sync_pull.py`
- `_merge_scheduled_task()` 中传递 `input_text=item.input_text`

### Step 6: 客户端 — scheduler_manager 执行逻辑

**文件**: `AutoGLM_GUI/scheduler_manager.py`
- `create_task()` 新增 `input_text: str = ""` 参数
- `_execute_task()` 方法（L375 附近）：删除 `workflow_manager.get_workflow(task.workflow_uuid)` 逻辑，改用 `task.input_text`
- L421, L448：删除 `workflow_uuid=task.workflow_uuid`，改用 `input_text=task.input_text` 传入 `task_store.create_task_run()` 和 `task_manager.enqueue_scheduled_task()`

### Step 7: 客户端 — push_channel dispatch 逻辑

**文件**: `AutoGLM_GUI/sync/push_channel.py`
- L175-179：删除 `workflow_manager.get_workflow(task.workflow_uuid)` 逻辑，改用 `task.input_text`
- L204：删除 `workflow_uuid=task.workflow_uuid`，改用 `input_text=task.input_text`

### Step 8: 客户端 — API schemas

**文件**: `AutoGLM_GUI/schemas.py`
- `ScheduledTaskCreate`（L957-1008）：删除 `workflow_uuid: str`，新增 `input_text: str = ""`
- `ScheduledTaskUpdate`（L1018-1068）：删除 `workflow_uuid: str | None`，新增 `input_text: str | None = None`
- `ScheduledTaskResponse`（L1071-）：删除 `workflow_uuid: str`，新增 `input_text: str = ""`
- `TaskRunResponse`（L899-919）：保留 `workflow_uuid: str | None = None`（task_runs 表中仍记录）

### Step 9: 客户端 — API 路由

**文件**: `AutoGLM_GUI/api/scheduled_tasks.py`
- `_task_to_response()`（L20-67）：删除 `workflow_uuid=task.workflow_uuid`，新增 `input_text=task.input_text`
- `create_scheduled_task()`（L76-93）：删除 `workflow_manager.get_workflow(request.workflow_uuid)` 验证逻辑，改用 `input_text=request.input_text`

### Step 10: 客户端 — task_manager

**文件**: `AutoGLM_GUI/task_manager.py`
- `enqueue_scheduled_task()`（L195-219）：将 `workflow_uuid: str` 参数改为可选 `workflow_uuid: str | None = None`，新增 `input_text: str = ""` 参数（或直接移除 `workflow_uuid`，因为 `input_text` 已包含指令内容）
- 实际上 `workflow_uuid` 在 `task_store.create_task_run()` 中仍被存储到 SQLite，用于上报给服务端。但服务端 `patrol_task_runs` 表也有 `workflow_uuid` 列。**决策：保留 `task_runs.workflow_uuid` 用于记录关联，但定时任务创建时不再强制传入**

### Step 11: 客户端 — task_store

**文件**: `AutoGLM_GUI/task_store.py`
- SQLite DDL 中 `task_runs` 表的 `workflow_uuid` 列保留（用于记录运行关联）
- `create_task_run()` 中 `workflow_uuid` 参数保留但改为可选

### Step 12: 客户端 — sync schemas 和 task_reporter

**文件**: `AutoGLM_GUI/sync/schemas.py`
- `TaskRunReportRequest.workflow_uuid`（L161）：保留为 `str | None = None`，因为 `patrol_task_runs` 表中仍有该字段

**文件**: `AutoGLM_GUI/sync/task_reporter.py`
- L89：`workflow_uuid=task_run.get("workflow_uuid")` 保留，因为 task_runs 表中仍有该字段

### Step 13: 客户端 — spec.md 更新

**文件**: `.trae/specs/add-inspection-system-sync/spec.md`
- `patrol_scheduled_tasks` 表定义：删除 `workflow_uuid`，新增 `input_text`

## Assumptions & Decisions

1. **`task_runs.workflow_uuid` 保留**：`patrol_task_runs` 表中的 `workflow_uuid` 列保留，用于记录运行关联的工作流。定时任务创建 task_run 时 `workflow_uuid` 为 None。
2. **`WorkflowManager` 保留但不再被定时任务使用**：`WorkflowManager` 仍用于 chat 模式等其他场景，但定时任务执行不再依赖它。
3. **`input_text` 为空时的处理**：如果 `task.input_text` 为空，定时任务执行时记录错误并跳过（类似当前 workflow not found 的处理）。
4. **服务端 `patrol_workflows` 表不变**：该表是步骤配置表，与本次修改无关。

## Verification Steps

1. 服务端：确认 `ScheduledTaskSyncDTO` 返回 `inputText` 字段
2. 客户端：`uv run python scripts/lint.py --backend --check-only`
3. 客户端：`uv run pytest -m "not integration and not e2e" -v`
4. 手动验证：同步定时任务后，`task.input_text` 有值；执行定时任务时不再查找 workflow
