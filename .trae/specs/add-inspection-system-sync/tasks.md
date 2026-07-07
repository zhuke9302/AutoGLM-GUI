# Tasks

- [x] Task 1: 定义服务端接口规范模块
  - [x] 1.1 创建 `AutoGLM_GUI/sync/schemas.py`，定义所有同步/上报相关的 Pydantic 请求/响应模型（客户端注册、心跳、设备上报、任务同步、工作流同步、配置同步、任务日志上报、截图上传、SSE 推送事件等）
  - [x] 1.2 创建 `AutoGLM_GUI/sync/client.py`，实现服务端 HTTP 客户端（认证、重试、超时、gzip 压缩、错误处理）

- [x] Task 2: 实现客户端注册与心跳模块
  - [x] 2.1 创建 `AutoGLM_GUI/sync/registration.py`，实现客户端注册逻辑（启动时注册、令牌管理）
  - [x] 2.2 实现心跳定时任务（可配置间隔，上报设备数/运行任务数/状态）

- [x] Task 3: 实现 SSE 推送通道（服务端→客户端实时通知）
  - [x] 3.1 创建 `AutoGLM_GUI/sync/push_channel.py`，实现 SSE 长连接订阅（连接建立、事件解析、分发处理）
  - [x] 3.2 实现 SSE 断线自动重连（指数退避：1s→2s→4s→...→30s），重连后触发全量同步
  - [x] 3.3 实现 SSE 事件处理器：`scheduled_task.changed` → 触发增量拉取；`workflow.changed` → 触发增量拉取；`config.changed` → 触发配置同步；`task.cancel` → 取消任务；`task.dispatch` → 执行即时巡检

- [x] Task 4: 实现设备状态上报模块
  - [x] 4.1 创建 `AutoGLM_GUI/sync/device_reporter.py`，监听 DeviceManager 设备变更事件，触发即时上报
  - [x] 4.2 实现批量设备状态上报接口调用

- [x] Task 5: 实现数据同步模块（服务端 → 客户端）
  - [x] 5.1 创建 `AutoGLM_GUI/sync/sync_pull.py`，实现定时任务增量同步（since 参数 + 合并到 SchedulerManager + 删除处理）
  - [x] 5.2 实现工作流增量同步（合并到 WorkflowManager + 删除处理）
  - [x] 5.3 实现模型配置同步（插入到配置优先级链中）
  - [x] 5.4 实现全量同步（首次注册后 / SSE 重连后触发）和增量同步（SSE 推送 / 心跳兜底触发）

- [x] Task 6: 实现任务执行日志上报模块（客户端 → 服务端）
  - [x] 6.1 创建 `AutoGLM_GUI/sync/task_reporter.py`，监听 TaskManager 任务完成事件
  - [x] 6.2 实现任务运行结果上报
  - [x] 6.3 实现任务事件批量上报（支持分批，避免大请求体）
  - [x] 6.4 实现截图上传（multipart/form-data，获取 URL 后替换事件中的 base64 引用）

- [x] Task 7: 实现离线缓存与补报机制
  - [x] 7.1 创建 `AutoGLM_GUI/sync/offline_queue.py`，SQLite 存储待上报数据队列
  - [x] 7.2 服务端不可达时将上报数据写入队列，恢复连接后按顺序补报
  - [x] 7.3 设置队列容量上限和过期清理策略

- [x] Task 8: 集成同步模块到应用生命周期
  - [x] 8.1 在 `api/__init__.py` 的 lifespan 中启动/停止同步模块
  - [x] 8.2 新增配置项：服务端地址、心跳间隔、离线队列容量等
  - [x] 8.3 同步模块仅在配置了服务端地址时激活，未配置则保持纯单机模式

- [x] Task 9: 前端同步状态展示
  - [x] 9.1 在 NavigationSidebar 或 Footer 中展示服务端连接状态（已连接/离线/未配置）
  - [x] 9.2 在前端 api.ts 中新增同步状态查询接口类型定义

- [x] Task 10: 验证与测试
  - [x] 10.1 为同步模块编写单元测试（schemas、client、offline_queue、push_channel）
  - [x] 10.2 为集成流程编写测试（注册→SSE连接→推送同步→上报→离线降级→重连补报）

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 1, Task 5
- Task 4 depends on Task 1
- Task 5 depends on Task 1
- Task 6 depends on Task 1
- Task 7 depends on Task 1, Task 6
- Task 8 depends on Task 2, Task 3, Task 4, Task 5, Task 6, Task 7
- Task 9 depends on Task 8
- Task 10 depends on Task 8
