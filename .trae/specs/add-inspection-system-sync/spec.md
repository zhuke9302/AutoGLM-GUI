# 巡检系统客户端-服务端对接规范

## Why
当前 AutoGLM-GUI 以单机模式运行，所有数据（定时任务、工作流、任务日志、设备信息等）均存储在本地 JSON/SQLite 中。为支持多客户端统一管理、集中调度和全局监控，需要将本地客户端接入服务端管理系统，实现数据双向同步。

## What Changes
- 新增服务端接口规范文档，定义客户端需要调用的所有服务端 API
- 新增服务端表结构建议（仅限与本工程对接相关的表）
- 客户端新增同步模块：从服务端拉取定时任务、工作流步骤、模型配置等数据
- 客户端新增上报模块：向服务端推送设备连接状态、任务执行结果、执行日志/截图等
- 客户端新增心跳机制：定期向服务端报告客户端存活状态
- 现有本地存储作为离线缓存/降级方案保留

## Impact
- Affected specs: 定时任务管理、工作流管理、任务执行与日志、设备管理、模型配置
- Affected code:
  - `AutoGLM_GUI/scheduler_manager.py` — 定时任务需从服务端同步
  - `AutoGLM_GUI/workflow_manager.py` — 工作流需从服务端同步
  - `AutoGLM_GUI/task_store.py` — 任务日志需上报服务端
  - `AutoGLM_GUI/device_manager.py` — 设备状态需上报服务端
  - `AutoGLM_GUI/config_manager.py` — 模型配置可从服务端下发
  - `AutoGLM_GUI/api/` — 新增同步/上报相关 API 端点
  - `frontend/src/api.ts` — 前端需展示同步状态

## 可行性分析

### 当前工程能力
| 能力 | 现状 | 对接可行性 |
|------|------|-----------|
| 定时任务 | APScheduler + JSON 本地存储，已有完整 CRUD | 高 — 改为从服务端拉取任务定义，本地仍用 APScheduler 执行 |
| 工作流/步骤编排 | WorkflowManager + JSON 本地存储，结构简单 (uuid, name, text) | 高 — 服务端下发工作流定义，本地缓存执行 |
| 任务执行 | TaskManager + SQLite，支持排队/执行/取消/事件流 | 高 — 执行逻辑不变，增加结果上报 |
| 任务日志/截图 | task_events 表 + trace JSONL，已有完整事件记录 | 高 — 截图以 URL 引用上报，避免大文件传输 |
| 设备管理 | DeviceManager + ADB 轮询，支持 USB/WiFi/Remote | 高 — 上报设备在线状态和元数据 |
| 模型配置 | UnifiedConfigManager 四层优先级 | 中 — 服务端配置作为新优先级层插入，需注意与本地配置冲突处理 |
| 历史记录 | 双写（SQLite + JSON），已有合并逻辑 | 中 — 上报时需统一格式，注意去重 |

### 同步机制与实时性设计

#### 服务端→客户端变更推送（核心实时通道）

采用 **SSE（Server-Sent Events）** 作为服务端→客户端的实时推送通道，理由：
- 本项目已广泛使用 SSE（任务事件流 `streamTaskEvents`、聊天流 `sendMessageStream`），技术栈一致
- SSE 天然单向（服务端→客户端），符合"服务端下发变更通知"的场景
- 比 WebSocket 轻量更低，自动重连，无需额外心跳

**推送流程**：
1. 客户端注册后，建立 SSE 长连接到服务端
2. 服务端在定时任务/工作流/配置发生变更时，通过 SSE 推送变更通知
3. 客户端收到通知后，调用对应的增量拉取接口获取最新数据
4. SSE 连接断开时自动重连（指数退避），重连后触发全量同步

**实时性保证**：
| 场景 | 延迟 | 说明 |
|------|------|------|
| 服务端修改定时任务 | < 1s | SSE 推送 `scheduled_task.changed` 事件，客户端立即拉取增量 |
| 服务端修改工作流/步骤 | < 1s | SSE 推送 `workflow.changed` 事件 |
| 服务端修改模型配置 | < 1s | SSE 推送 `config.changed` 事件 |
| 服务端远程取消任务 | < 1s | SSE 推送 `task.cancel` 指令 |
| SSE 断线期间变更 | 下次重连后 < 1s | 重连后全量同步补齐 |
| 心跳（兜底） | 30s | 心跳响应中的 `task_changes`/`config_changes` 标志作为兜底检测 |

#### 客户端→服务端上报（HTTP POST）

客户端→服务端仍使用 HTTP POST，原因：
- 上报是离散事件，不需要长连接
- 支持重试、批量、压缩等策略
- 与现有 API 风格一致

### 性能考虑
1. **同步频率**：SSE 推送触发增量同步（基于 `updated_at` 时间戳），避免全量拉取；心跳作为兜底
2. **上报策略**：任务结果实时上报，设备状态变更时上报（非轮询），心跳间隔可配置（默认 30s）
3. **截图处理**：截图先上传到服务端对象存储，任务日志中只存 URL 引用，避免 base64 传输
4. **离线降级**：服务端不可达时，回退到本地存储，恢复连接后补报离线期间的数据
5. **批量上报**：任务事件支持批量上报，减少 HTTP 请求次数
6. **压缩**：大量事件上报时启用 gzip 压缩
7. **SSE 重连**：指数退避重连（1s → 2s → 4s → ... → 30s），重连后全量同步

---

## ADDED Requirements

### Requirement: 服务端接口规范
客户端 SHALL 调用服务端提供的以下接口，完成数据双向同步。

#### 接口分组一：客户端注册与心跳

**1.1 客户端注册**
- **POST** `/api/v1/clients/register`
- 客户端启动时调用，注册自身信息，获取 `client_id` 和访问令牌
- Request:
  ```json
  {
    "hostname": "string",
    "ip": "string",
    "os": "string",
    "version": "string"
  }
  ```
- Response:
  ```json
  {
    "client_id": "string (UUID)",
    "token": "string (JWT)",
    "heartbeat_interval_seconds": 30
  }
  ```

**1.2 客户端心跳**
- **POST** `/api/v1/clients/{client_id}/heartbeat`
- 定期上报存活状态和设备列表摘要
- Request:
  ```json
  {
    "timestamp": "ISO8601",
    "device_count": 3,
    "running_task_count": 1,
    "status": "healthy | degraded | error",
    "error_message": "string | null"
  }
  ```
- Response:
  ```json
  {
    "ack": true,
    "config_changes": true,
    "task_changes": true
  }
  ```
- `config_changes` / `task_changes` 为 true 时，客户端应立即触发对应同步

#### 接口分组二：设备状态上报

**2.1 批量上报设备状态**
- **POST** `/api/v1/clients/{client_id}/devices/report`
- 设备连接/断开时触发，也作为心跳补充
- Request:
  ```json
  {
    "timestamp": "ISO8601",
    "devices": [
      {
        "serial": "string",
        "model": "string",
        "connection_type": "usb | wifi | remote",
        "status": "online | offline",
        "display_name": "string | null",
        "group_id": "string | null",
        "agent_state": "idle | busy | error | initializing",
        "agent_model_name": "string | null"
      }
    ]
  }
  ```
- Response: `{ "ack": true }`

#### 接口分组三：定时任务同步

**3.1 拉取定时任务列表**
- **GET** `/api/v1/clients/{client_id}/scheduled-tasks?since={ISO8601}`
- `since` 参数：增量同步，只返回 `updated_at > since` 的任务
- Response:
  ```json
  {
    "tasks": [
      {
        "id": "string (UUID)",
        "name": "string",
        "workflow_uuid": "string",
        "device_serialnos": ["string"],
        "device_group_id": "string | null",
        "cron_expression": "string",
        "enabled": true,
        "execution_mode": "classic | layered",
        "updated_at": "ISO8601"
      }
    ],
    "deleted_ids": ["UUID"],
    "server_time": "ISO8601"
  }
  ```
- `deleted_ids`：服务端已删除的任务 ID，客户端应同步删除

**3.2 上报定时任务执行结果**
- **POST** `/api/v1/clients/{client_id}/scheduled-tasks/{task_id}/execution-report`
- 每次定时任务触发后上报执行结果
- Request:
  ```json
  {
    "fire_id": "string (UUID)",
    "timestamp": "ISO8601",
    "device_serial": "string",
    "task_run_id": "string (UUID)",
    "status": "succeeded | failed | cancelled | interrupted",
    "error_message": "string | null",
    "step_count": 5,
    "duration_ms": 12345
  }
  ```

#### 接口分组四：工作流同步

**4.1 拉取工作流列表**
- **GET** `/api/v1/clients/{client_id}/workflows?since={ISO8601}`
- Response:
  ```json
  {
    "workflows": [
      {
        "uuid": "string",
        "name": "string",
        "text": "string",
        "updated_at": "ISO8601"
      }
    ],
    "deleted_uuids": ["string"],
    "server_time": "ISO8601"
  }
  ```

#### 接口分组五：模型配置同步

**5.1 拉取模型配置**
- **GET** `/api/v1/clients/{client_id}/config`
- 服务端下发的配置优先级介于 CLI 和本地配置文件之间
- Response:
  ```json
  {
    "base_url": "string | null",
    "model_name": "string | null",
    "api_key": "string | null",
    "agent_type": "string | null",
    "default_max_steps": "int | null",
    "updated_at": "ISO8601"
  }
  ```
- null 字段表示服务端不管控该项，客户端使用本地值

#### 接口分组六：任务执行日志上报

**6.1 上报任务运行结果**
- **POST** `/api/v1/clients/{client_id}/task-runs/report`
- 任务完成时上报完整运行结果
- Request:
  ```json
  {
    "task_run_id": "string (UUID)",
    "source": "chat | scheduled",
    "session_id": "string | null",
    "scheduled_task_id": "string | null",
    "workflow_uuid": "string | null",
    "device_serial": "string",
    "status": "succeeded | failed | cancelled | interrupted",
    "input_text": "string",
    "final_message": "string | null",
    "error_message": "string | null",
    "stop_reason": "string | null",
    "trace_id": "string | null",
    "step_count": 5,
    "started_at": "ISO8601",
    "finished_at": "ISO8601",
    "duration_ms": 12345
  }
  ```

**6.2 批量上报任务事件**
- **POST** `/api/v1/clients/{client_id}/task-runs/{task_run_id}/events/batch`
- 支持批量上报，减少请求次数
- Request:
  ```json
  {
    "events": [
      {
        "seq": 1,
        "event_type": "string",
        "role": "string | null",
        "payload": {},
        "created_at": "ISO8601"
      }
    ]
  }
  ```
- Response: `{ "ack": true, "last_seq": 5 }`

**6.3 上传截图/附件**
- **POST** `/api/v1/clients/{client_id}/uploads`
- `Content-Type: multipart/form-data`
- 字段：`file` (二进制), `task_run_id` (string), `category` (screenshot | attachment)
- Response:
  ```json
  {
    "url": "string (可访问的 URL)",
    "file_id": "string"
  }
  ```
- 任务事件中的截图引用此 URL，不再内嵌 base64

#### 接口分组七：服务端推送通道（SSE）

**7.1 订阅服务端变更通知**
- **GET** `/api/v1/clients/{client_id}/events/stream`
- `Accept: text/event-stream`
- 客户端注册成功后建立此 SSE 长连接，服务端通过此通道实时推送变更通知
- 事件类型与数据格式：

| event 类型 | data 格式 | 触发时机 |
|-----------|----------|---------|
| `scheduled_task.changed` | `{"action": "created \| updated \| deleted", "id": "UUID", "updated_at": "ISO8601"}` | 定时任务被创建/修改/删除 |
| `workflow.changed` | `{"action": "created \| updated \| deleted", "uuid": "string", "updated_at": "ISO8601"}` | 工作流被创建/修改/删除 |
| `config.changed` | `{"updated_at": "ISO8601"}` | 模型配置被修改 |
| `task.cancel` | `{"task_run_id": "UUID"}` | 服务端远程取消任务 |
| `task.dispatch` | `{"scheduled_task_id": "UUID", "fire_id": "UUID", "device_serialnos": ["string"]}` | 服务端触发即时巡检任务（非定时，手动触发） |
| `ping` | `{}` | 保活（每 30s） |

- 客户端收到 `*.changed` 事件后，调用对应的增量拉取接口获取最新数据
- 客户端收到 `task.cancel` 事件后，立即取消对应任务
- 客户端收到 `task.dispatch` 事件后，立即执行指定任务（类似定时触发，但由服务端手动发起）
- 连接断开时客户端自动重连（指数退避），重连后触发全量同步

#### 接口分组八：任务控制（服务端 → 客户端）

**8.1 查询客户端任务列表**
- **GET** `/api/v1/clients/{client_id}/task-runs?status={status}&limit={limit}`
- 服务端可查询客户端正在执行/最近完成的任务
- Response:
  ```json
  {
    "task_runs": [
      {
        "task_run_id": "string",
        "device_serial": "string",
        "status": "string",
        "input_text": "string",
        "started_at": "ISO8601",
        "step_count": 3
      }
    ]
  }
  ```

**8.2 远程取消任务**
- **POST** `/api/v1/clients/{client_id}/task-runs/{task_run_id}/cancel`
- 服务端可远程取消客户端正在执行的任务
- Response: `{ "ack": true }`

---

### Requirement: 客户端同步模块
系统 SHALL 提供同步模块，实现以下功能：

#### Scenario: 客户端启动注册
- **WHEN** 客户端启动且配置了服务端地址
- **THEN** 调用注册接口获取 client_id 和令牌，建立 SSE 推送通道，触发全量同步

#### Scenario: SSE 推送触发增量同步
- **WHEN** 客户端通过 SSE 收到 `scheduled_task.changed` / `workflow.changed` / `config.changed` 事件
- **THEN** 立即调用对应的增量拉取接口（带 `since` 参数），合并到本地存储

#### Scenario: SSE 推送触发任务取消
- **WHEN** 客户端通过 SSE 收到 `task.cancel` 事件
- **THEN** 立即取消对应的任务运行

#### Scenario: SSE 推送触发即时巡检
- **WHEN** 客户端通过 SSE 收到 `task.dispatch` 事件
- **THEN** 立即为指定设备创建并执行任务（类似定时触发，但由服务端手动发起）

#### Scenario: SSE 断线重连
- **WHEN** SSE 连接断开
- **THEN** 指数退避重连（1s → 2s → 4s → ... → 30s），重连成功后触发全量同步

#### Scenario: 心跳兜底检测
- **WHEN** 心跳响应中 `task_changes=true` 或 `config_changes=true`（SSE 通知可能丢失时）
- **THEN** 触发对应增量同步，作为 SSE 的兜底机制

#### Scenario: 增量同步定时任务
- **WHEN** 触发定时任务同步（SSE 推送或心跳兜底）
- **THEN** 以本地最新 `updated_at` 为 `since` 参数拉取增量任务，合并到本地 SchedulerManager，删除 `deleted_ids` 中的任务

#### Scenario: 设备状态变更上报
- **WHEN** 设备连接或断开
- **THEN** 立即上报变更的设备状态，非轮询

#### Scenario: 任务完成上报
- **WHEN** 任务运行到达终态（succeeded/failed/cancelled/interrupted）
- **THEN** 上报任务运行结果，并批量上报该任务的所有事件

#### Scenario: 离线降级
- **WHEN** 服务端不可达
- **THEN** 继续使用本地数据执行任务，将待上报数据缓存到本地队列，恢复连接后补报

#### Scenario: 截图上传
- **WHEN** 任务事件包含截图数据
- **THEN** 先上传截图到服务端，获取 URL 后在事件中引用 URL 而非 base64

---

### Requirement: 配置优先级扩展
系统 SHALL 在现有四层配置优先级中插入"服务端配置"层。

#### Scenario: 服务端配置优先级
- **WHEN** 服务端下发了配置项
- **THEN** 优先级顺序为：CLI > 环境变量 > **服务端配置** > 本地配置文件 > 默认值

---

## 服务端表结构建议（仅限对接相关）

### 1. patrol_clients — 客户端注册表
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 客户端 ID |
| hostname | VARCHAR(255) | 主机名 |
| ip | VARCHAR(45) | IP 地址 |
| os | VARCHAR(50) | 操作系统 |
| version | VARCHAR(50) | 客户端版本 |
| token_hash | VARCHAR(255) | 令牌哈希 |
| status | ENUM(online,offline) | 在线状态 |
| last_heartbeat_at | TIMESTAMP | 最后心跳时间 |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 更新时间 |

### 2. patrol_client_devices — 客户端设备表
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 设备 ID |
| client_id | UUID FK(patrol_clients) | 所属客户端 |
| serial | VARCHAR(255) | 设备序列号 |
| model | VARCHAR(100) | 设备型号 |
| connection_type | ENUM(usb,wifi,remote) | 连接类型 |
| status | ENUM(online,offline) | 设备状态 |
| display_name | VARCHAR(100) | 显示名称 |
| group_id | UUID FK(patrol_device_groups) | 设备分组 |
| agent_state | VARCHAR(50) | Agent 状态 |
| agent_model_name | VARCHAR(100) | Agent 模型名 |
| reported_at | TIMESTAMP | 上报时间 |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 更新时间 |
| UNIQUE(client_id, serial) | | |

### 3. patrol_scheduled_tasks — 定时任务表
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 任务 ID |
| name | VARCHAR(255) | 任务名称 |
| workflow_uuid | UUID FK(patrol_workflows) | 关联工作流 |
| client_id | UUID FK(patrol_clients) | 目标客户端 |
| device_serialnos | JSON | 目标设备序列号列表 |
| device_group_id | UUID FK(patrol_device_groups) | 目标设备分组 |
| cron_expression | VARCHAR(100) | Cron 表达式 |
| enabled | BOOLEAN | 是否启用 |
| execution_mode | ENUM(classic,layered) | 执行模式 |
| last_run_time | TIMESTAMP | 最后运行时间 |
| last_run_status | VARCHAR(50) | 最后运行状态 |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 更新时间 |

### 4. patrol_workflows — 工作流表
| 字段 | 类型 | 说明 |
|------|------|------|
| uuid | UUID PK | 工作流 UUID |
| name | VARCHAR(255) | 工作流名称 |
| text | TEXT | 工作流指令文本 |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 更新时间 |

### 5. patrol_task_runs — 任务运行记录表
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 运行 ID |
| client_id | UUID FK(patrol_clients) | 来源客户端 |
| source | ENUM(chat,scheduled) | 来源 |
| scheduled_task_id | UUID FK(patrol_scheduled_tasks) | 关联定时任务 |
| workflow_uuid | UUID FK(patrol_workflows) | 关联工作流 |
| device_serial | VARCHAR(255) | 设备序列号 |
| status | ENUM(queued,running,succeeded,failed,cancelled,interrupted) | 状态 |
| input_text | TEXT | 输入指令 |
| final_message | TEXT | 最终消息 |
| error_message | TEXT | 错误信息 |
| stop_reason | VARCHAR(50) | 停止原因 |
| trace_id | VARCHAR(100) | Trace ID |
| step_count | INT | 步骤数 |
| started_at | TIMESTAMP | 开始时间 |
| finished_at | TIMESTAMP | 完成时间 |
| created_at | TIMESTAMP | 创建时间 |

### 6. patrol_task_events — 任务事件表
| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK | 自增 ID |
| task_run_id | UUID FK(patrol_task_runs) | 关联任务运行 |
| seq | INT | 序号 |
| event_type | VARCHAR(50) | 事件类型 |
| role | VARCHAR(20) | 角色 |
| payload | JSON | 事件载荷 |
| created_at | TIMESTAMP | 创建时间 |
| UNIQUE(task_run_id, seq) | | |

**event_type 枚举值**：

| event_type | role | 触发时机 | payload 结构 |
|---|---|---|---|
| `user_message` | `user` | 任务启动时记录用户输入 | `{"message": str, "attachments": [str]}` |
| `status` | `system` | 任务状态变更（queued→running→succeeded/failed 等） | `{"status": "queued" \| "running" \| "succeeded" \| "failed" \| "interrupted" \| "cancelled"}` |
| `thinking` | `assistant` | Agent 思考过程（模型推理输出） | `{"text": str, "step": int}` |
| `step` | `assistant` | 一个执行步骤完成（含截图、动作、耗时） | `{"step": int, "screenshot_url": str, "action": str, "timings": {"screenshot_ms": int, "llm_ms": int, "action_ms": int, "total_ms": int}}` |
| `trace_summary` | `assistant` | 任务结束时汇总的轨迹摘要 | `{"summary": {...}, "step_summaries": [...], "total_duration_ms": int, "steps": int}` |
| `error` | `assistant` | 执行过程中发生错误 | `{"message": str, "stop_reason": str \| null}` |
| `cancelled` | `assistant` | 任务被用户取消 | `{"message": str}` |

**payload 中的截图引用**：
- `step` 事件的 `screenshot_url` 字段为截图 URL，指向 `uploaded_files` 表中已上传的文件
- 客户端不直接存 base64，而是先上传截图到 `uploaded_files`，再在 `payload` 中引用 URL
- 这样可以避免事件表过大，也便于 CDN 加速和浏览器直接展示

**role 枚举值**：
- `user` — 用户输入相关事件
- `assistant` — Agent 产出相关事件
- `system` — 系统状态变更事件
- `tool` — 工具调用事件（预留）

**索引建议**：
- `idx_patrol_task_events_task_seq(task_run_id, seq)` — 按任务查询事件流，主查询路径
- `idx_patrol_task_events_type(event_type)` — 按事件类型筛选（如查所有错误事件）

### 7. patrol_uploaded_files — 上传文件表
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 文件 ID |
| task_run_id | UUID FK(patrol_task_runs) | 关联任务运行 |
| client_id | UUID FK(patrol_clients) | 来源客户端 |
| category | ENUM(screenshot,attachment) | 文件类别 |
| url | VARCHAR(1024) | 访问 URL |
| mime_type | VARCHAR(100) | MIME 类型 |
| size_bytes | BIGINT | 文件大小 |
| created_at | TIMESTAMP | 创建时间 |
