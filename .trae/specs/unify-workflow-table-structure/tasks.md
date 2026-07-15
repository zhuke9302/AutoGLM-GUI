# Tasks

- [x] Task 1: 服务端 patrol_workflows.task_id 类型改为 String
  - [x] 1.1 修改 `PatrolWorkflow.java`：`taskId` 从 `Long` 改为 `String`
  - [x] 1.2 修改 `PatrolWorkflowServiceImpl.java`：所有 `taskId` 相关查询适配 String 类型
  - [x] 1.3 修改 `PatrolWorkflowServiceImpl.listIncremental()`：去掉 `Long.valueOf(t.getId())` 转换 hack，直接用 UUID String 查询
  - [x] 1.4 数据库迁移文档更新：`task_id` 类型 BIGINT → VARCHAR(36)

- [x] Task 2: 服务端简化 listIncremental 映射逻辑
  - [x] 2.1 `workflow.uuid` 改为直接用 `task_id`（UUID String），不再 `String.valueOf(entry.getKey())`
  - [x] 2.2 `workflow.name` 取第一个步骤的 `step_name`
  - [x] 2.3 `workflow.text` 改为所有步骤的 `step_name` 按 `step_order` 换行拼接，不再拼接 `step_config`
  - [x] 2.4 废弃 `step_config` 字段（Java 实体加 `@Deprecated`，不删除列）

- [x] Task 3: 服务端 scheduled_tasks.workflow_uuid 赋值对齐
  - [x] 3.1 确认 `workflow_uuid` 值等于 `task_id`（即任务自身 ID），创建任务时自动赋值
  - [x] 3.2 `PatrolScheduledTaskServiceImpl` 中 `listByTaskId` 调用从 `task.getSystemId()` 改为 `task.getId()`

- [ ] Task 4: 验证
  - [ ] 4.1 端到端测试：服务端创建含多步骤的任务 → 客户端同步 → 验证 workflow 的 uuid/name/text 正确
  - [ ] 4.2 验证客户端执行同步后的任务正常

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 1
- Task 4 depends on Task 2, Task 3
