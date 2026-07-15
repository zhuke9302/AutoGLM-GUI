# 服务端"立即执行"与客户端拉通分析

## 摘要

服务端定时任务已有"立即执行"按钮，客户端不需要添加。核心问题是：服务端点击"立即执行"后，如何确保客户端能正确接收并执行任务。

## 现状分析

### 已有的完整链路

服务端"立即执行" → SSE `TASK_DISPATCH` 事件推送 → 客户端 `PushChannel._on_task_dispatch()` → 执行任务

具体流程：

1. **服务端**：用户点击"立即执行"按钮，服务端通过 SSE 推送 `TASK_DISPATCH` 事件
2. **SSE 通道**：`ServerClient.events_stream()` 持续监听 SSE 流，解析 `event:` 和 `data:` 行
3. **事件分发**：`PushChannel._handle_event()` 根据 `event_type` 路由到 `_on_task_dispatch()`
4. **客户端执行**：`_on_task_dispatch()` 解析 `SSETaskDispatch`（含 `scheduled_task_id`、`fire_id`、`device_serialnos`），查找本地 ScheduledTask 和 Workflow，对在线设备调用 `task_manager.enqueue_scheduled_task()` 入队执行
5. **结果上报**：执行完成后 `TaskReporter` 自动上报结果到服务端

### 关键代码位置

| 组件 | 文件 | 行号 |
|------|------|------|
| SSE 事件类型定义 | `AutoGLM_GUI/sync/schemas.py` | L205-211 |
| TaskDispatch Schema | `AutoGLM_GUI/sync/schemas.py` | L237-240 |
| SSE 流监听 | `AutoGLM_GUI/sync/client.py` | L412-458 |
| 事件路由 | `AutoGLM_GUI/sync/push_channel.py` | L117-127 |
| TaskDispatch 处理 | `AutoGLM_GUI/sync/push_channel.py` | L156-213 |
| 执行入队 | `AutoGLM_GUI/scheduler_manager.py` | L361-468 |

### SSE TaskDispatch 数据格式

```json
{
  "scheduled_task_id": "uuid-of-the-task",
  "fire_id": "uuid-for-this-fire-instance",
  "device_serialnos": ["device1", "device2"]
}
```

## 结论

**链路已完整，无需额外开发。** 服务端的"立即执行"按钮通过 SSE `TASK_DISPATCH` 事件推送到客户端，客户端 `PushChannel._on_task_dispatch()` 已实现完整的接收和执行逻辑。

### 可能需要排查的问题

如果"立即执行"不生效，可能的原因：

1. **SSE 连接未建立**：客户端未注册或 SSE 流断开 → 检查 `PushChannel.is_connected` 和日志 `SSE stream disconnected`
2. **任务未同步到客户端**：服务端创建了任务但客户端本地没有 → 检查 `SCHEDULED_TASK_CHANGED` 事件是否触发增量同步
3. **设备离线**：`_on_task_dispatch()` 跳过离线设备 → 日志会打印 `Device xxx offline, skipping dispatch`
4. **Workflow 未同步**：客户端找不到对应的 Workflow → 日志会打印 `Workflow xxx not found for dispatch`
5. **服务端未推送 TASK_DISPATCH 事件**：服务端 Java 代码可能未实现该 SSE 推送 → 需要检查服务端 Gateway 代码

### 验证方法

1. 启动客户端，确认日志出现 `SSE: task.dispatch scheduled_task_id=xxx`
2. 在服务端点击"立即执行"
3. 观察客户端日志是否收到 `TASK_DISPATCH` 事件并开始执行
4. 执行完成后检查 `task_reporter` 是否上报结果
