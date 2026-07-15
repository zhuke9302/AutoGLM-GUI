# Checklist

- [x] 服务端 `PatrolWorkflow.taskId` 类型已从 Long 改为 String
- [ ] 服务端 `patrol_workflows` 表 `task_id` 列类型已改为 VARCHAR(36)（需执行 ALTER TABLE）
- [x] 服务端 `listIncremental()` 不再有 `Long.valueOf(t.getId())` 类型转换 hack
- [x] 服务端 `workflow.uuid` 直接用 `task_id`（UUID String）
- [x] 服务端 `workflow.name` 取第一个步骤的 `step_name`
- [x] 服务端 `workflow.text` 为所有 `step_name` 按 `step_order` 换行拼接
- [x] 服务端 `step_config` 字段已标记 `@Deprecated`
- [x] 服务端 `scheduled_tasks.workflow_uuid` 创建时自动赋值为 `task.getId()`
- [ ] 端到端测试：多步骤任务同步后客户端 workflow 的 uuid/name/text 正确
