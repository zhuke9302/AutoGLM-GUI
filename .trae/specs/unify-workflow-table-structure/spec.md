# 归一客户端与服务端任务/步骤表结构 Spec

## Why
客户端（AutoGLM-GUI）和服务端（falconconsole）对 `patrol_workflows` 表的语义不同，同步时需要映射转换。通过最小改动对齐映射规则，降低维护成本。

## 现状

### 客户端
- `patrol_workflows`：工作流（uuid, name, text）
- `scheduled_tasks.workflow_uuid` → FK 指向 `patrol_workflows.uuid`

### 服务端
- `patrol_workflows`：步骤（id BIGINT, task_id BIGINT, step_name, step_order, step_type, step_config）
- 步骤通过 `task_id` 反向关联任务
- `listIncremental()` 已在做映射：按 taskId 分组 → 拼成 `{uuid, name, text}` 返回

## What Changes（方案 1：最小改动）

### 服务端变更
1. **`patrol_workflows.task_id` 类型从 BIGINT 改为 VARCHAR(UUID)**，与 `patrol_scheduled_tasks.id`（UUID）对齐
2. **映射规则明确化**：
   - `workflow.uuid` = `String.valueOf(taskId)` → 改为直接用 taskId（UUID String）
   - `workflow.name` = 第一个步骤的 `step_name`
   - `workflow.text` = 所有步骤的 `step_name` 按顺序拼接（换行分隔），**废弃 `step_config` 字段**
3. **`scheduled_tasks.workflow_uuid` 保留**，值等于 `task_id`（即任务自身 ID），客户端依赖此字段

### 客户端变更
- **无**，客户端表结构和代码维持不变

### 废弃字段
- `patrol_workflows.step_config`：不再使用，步骤内容统一存入 `step_name`

## Impact
- Affected code:
  - `falconconsole/PatrolWorkflow.java` — taskId 类型 Long → String，stepConfig 标记废弃
  - `falconconsole/PatrolWorkflowServiceImpl.java` — listIncremental 映射逻辑简化
  - `falconconsole/PatrolScheduledTaskServiceImpl.java` — workflowUuid 赋值逻辑
  - 数据库迁移：`patrol_workflows.task_id` 类型 BIGINT → VARCHAR(36)

## ADDED Requirements

### Requirement: patrol_workflows.task_id 类型统一为 UUID String
`patrol_workflows.task_id` SHALL 为 VARCHAR(36)，与 `patrol_scheduled_tasks.id`（UUID）类型一致。

#### Scenario: 步骤查询无需类型转换
- **WHEN** 通过 scheduled_task.id 查询关联步骤
- **THEN** 直接 `WHERE task_id = 'uuid-string'`，无需 Long 转换

### Requirement: 映射规则明确化
`listIncremental()` 的映射规则 SHALL 为：
- `uuid` = `task_id`（UUID String）
- `name` = 第一个步骤的 `step_name`
- `text` = 所有步骤的 `step_name` 按 `step_order` 顺序换行拼接

#### Scenario: 多步骤任务同步
- **WHEN** 服务端有任务含 3 个步骤（step_name: "打开APP", "点击按钮", "验证结果"）
- **THEN** 客户端收到 workflow: `{uuid: taskId, name: "打开APP", text: "打开APP\n点击按钮\n验证结果"}`

## MODIFIED Requirements

### Requirement: patrol_workflows.step_config 废弃
`step_config` 字段不再使用，步骤内容统一存入 `step_name`。

## REMOVED Requirements

（无删除项，方案1保持客户端不变）
