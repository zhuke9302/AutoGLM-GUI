# 任务详情回显修复 & PC Web 环境信息同步

## 问题概述

1. **任务中心编辑/查看详情时，PC Web 任务的目标环境、执行账号、密码、目标客户端、巡检设备等信息没有回显**
2. **PC Web 定时任务执行时，需要将环境信息（URL、登录账号、密码）同步到客户端，任务执行第一步先登录环境**

---

## 问题 1：任务详情回显缺失

### 根因分析

#### 1.1 编辑对话框 `TaskCreateDialog.vue` 回显缺失

**文件**: `g:\workspace\cuc-ikb-ai-xunjian-repository\frontend\src\views\task\modules\TaskCreateDialog.vue`

| 缺陷 | 位置 | 影响 |
|------|------|------|
| `fillFromEdit` 和 `fillFromCopy` 中 `deviceSerialnos` 解析条件为 `terminalType === 'App'`，PC Web 被排除 | 第 347、291 行 | PC Web 设备序列号未解析，多选框回显为空 |
| `isFilling=true` 期间 watcher 被跳过，`currentClientOptions` 未赋值 | 第 405、429 行 | 客户端下拉框选项列表为空，clientId 无法显示标签 |
| `fillFromEdit` 仅 App 端调用 `loadDevicesByClient` | 第 378 行 | PC Web 设备列表未加载，设备下拉框选项为空 |

#### 1.2 详情弹窗 `TaskDetailDialog.vue` 回显缺失

**文件**: `g:\workspace\cuc-ikb-ai-xunjian-repository\frontend\src\views\task\modules\TaskDetailDialog.vue`

| 缺陷 | 位置 | 影响 |
|------|------|------|
| PC Web 部分只显示 `targetEnv` 和 `executeAccount`，缺少目标客户端和巡检设备 | 第 132-139 行 | PC Web 详情不完整 |
| App 部分显示 `clientId` 为原始 ID 字符串，未转换为客户端名称 | 第 145 行 | 用户体验差 |

#### 1.3 后端详情接口缺少环境 URL 和密码

**文件**: `g:\workspace\cuc-ikb-ai-xunjian-repository\falconconsole\src\main\java\com\falcon\patrol\service\impl\PatrolScheduledTaskServiceImpl.java`

- `TaskCenterVO` 继承 `PatrolScheduledTask`，有 `clientId`、`deviceSerialnos`、`executeAccount` 字段
- `targetEnv` 来自 `PatrolSystem.targetEnv`（系统级粗粒度标识），不是 `PatrolSystemEnv` 表中的具体环境
- **缺少 `envUrl` 和 `executePassword` 字段**：环境 URL 和密码存储在 `patrol_system_env` 表中，但 `TaskCenterVO` 不返回这些信息

### 修复方案

#### 前端修复（TaskCreateDialog.vue）

1. **`fillFromEdit` / `fillFromCopy` 中 `deviceSerialnos` 解析条件**：去掉 `terminalType === 'App'` 限制，改为所有端类型都解析
2. **`fillFromEdit` / `fillFromCopy` 中手动赋值 `currentClientOptions`**：在 `loadSystemDetail` 之后，根据 `terminalType` 手动赋值客户端选项
3. **`fillFromEdit` / `fillFromCopy` 中 PC Web 也加载设备列表**：将 `loadDevicesByClient` 调用条件从仅 App 扩展为 PC Web 和 App 都调用

#### 前端修复（TaskDetailDialog.vue）

1. **PC Web 部分增加客户端和设备信息展示**
2. **App 部分 `clientId` 显示为客户端名称**

#### 后端修复（PatrolScheduledTaskServiceImpl.java）

1. **`TaskCenterVO` 增加 `envUrl` 和 `executePassword` 字段**
2. **`convertToVOList` 方法中查询 `PatrolSystemEnv` 表，回填环境 URL 和密码**

---

## 问题 2：PC Web 环境信息同步到客户端

### 根因分析

当前 PC Web 任务执行的数据流：

```
服务端 TASK_DISPATCH 事件 → 客户端 push_channel._on_task_dispatch → scheduler_manager.get_task → task_manager.enqueue_scheduled_task → MidsceneWebAgent._stream_impl
```

**缺失环节**：

1. **TASK_DISPATCH 事件数据**（`PatrolScheduledTaskServiceImpl.runTaskNow`）：只包含 `scheduled_task_id`、`fire_id`、`device_serialnos`，**没有环境 URL、登录账号、密码**
2. **定时任务同步接口**（`ClientSyncController.ScheduledTaskSyncItem`）：只包含 `id`、`name`、`workflow_uuid`、`device_serialnos` 等，**没有环境信息**
3. **客户端 `ScheduledTask` 模型**（`AutoGLM_GUI/models/scheduled_task.py`）：没有 `env_url`、`execute_account`、`execute_password` 字段
4. **MidsceneWebAgent**（`AutoGLM_GUI/agents/midscene_web/async_agent.py`）：只从任务文本中提取 URL，没有登录步骤

### 修复方案

#### 方案设计

环境信息（URL、账号、密码）存储在服务端 `patrol_system_env` 表中，通过 `systemId → PatrolSystemTerminal → PatrolSystemEnv` 关联。任务表 `patrol_scheduled_tasks` 有 `systemId` 和 `targetEnv`（环境名称），可以据此查询到具体的环境配置。

**核心思路**：在 TASK_DISPATCH 事件和定时任务同步接口中，增加环境信息字段；客户端接收后，在执行 PC Web 任务时先导航到环境 URL 并执行登录。

#### 后端修改

**2.1 TASK_DISPATCH 事件增加环境信息**

文件：`PatrolScheduledTaskServiceImpl.java`

在 `runTaskNow` 方法中，PC Web 分支构建 `eventData` 时，查询 `PatrolSystemEnv` 表获取环境 URL、账号、密码，加入事件数据：

```java
// 查询环境信息
if ("PC".equals(task.getTerminalType())) {
    List<PatrolSystemTerminal> terminals = systemTerminalService.listBySystemId(task.getSystemId());
    if (!CollectionUtils.isEmpty(terminals)) {
        List<PatrolSystemEnv> envs = systemEnvService.listByTerminalId(terminals.get(0).getId());
        // 根据 targetEnv 匹配具体环境
        String targetEnvName = task.getTargetEnv(); // 需要从 PatrolSystem 获取
        PatrolSystemEnv matchedEnv = envs.stream()
            .filter(e -> e.getEnvName().equals(targetEnvName))
            .findFirst().orElse(null);
        if (matchedEnv != null) {
            eventData.put("env_url", matchedEnv.getEnvUrl());
            eventData.put("execute_account", matchedEnv.getExecuteAccount());
            eventData.put("execute_password", matchedEnv.getExecutePassword());
        }
    }
}
```

**注意**：`PatrolScheduledTask` 没有 `targetEnv` 字段，但 `PatrolSystem` 有。需要通过 `task.getSystemId()` 查询 `PatrolSystem.targetEnv`。

**2.2 定时任务同步接口增加环境信息**

文件：`ClientSyncController.java`

在 `ScheduledTaskSyncItem` 中增加 `envUrl`、`executeAccount`、`executePassword` 字段，在 `from` 方法中查询 `PatrolSystemEnv` 表填充。

#### 客户端修改

**2.3 SSETaskDispatch 模型增加环境信息字段**

文件：`AutoGLM_GUI/sync/schemas.py`

```python
class SSETaskDispatch(SyncBaseModel):
    scheduled_task_id: str
    fire_id: str
    device_serialnos: list[str]
    env_url: str | None = None
    execute_account: str | None = None
    execute_password: str | None = None
```

**2.4 ScheduledTaskSyncItem 模型增加环境信息字段**

文件：`AutoGLM_GUI/sync/schemas.py`

```python
class ScheduledTaskSyncItem(SyncBaseModel):
    # ... 现有字段 ...
    env_url: str | None = None
    execute_account: str | None = None
    execute_password: str | None = None
```

**2.5 ScheduledTask 模型增加环境信息字段**

文件：`AutoGLM_GUI/models/scheduled_task.py`

```python
@dataclass
class ScheduledTask:
    # ... 现有字段 ...
    env_url: str = ""
    execute_account: str = ""
    execute_password: str = ""
```

**2.6 push_channel._on_task_dispatch 传递环境信息**

文件：`AutoGLM_GUI/sync/push_channel.py`

在 `_on_task_dispatch` 方法中，将 `evt.env_url`、`evt.execute_account`、`evt.execute_password` 传递给 `enqueue_scheduled_task`。

**2.7 TaskManager 增加环境信息参数**

文件：`AutoGLM_GUI/task_manager.py`

- `enqueue_scheduled_task` 方法增加 `env_url`、`execute_account`、`execute_password` 参数
- `TaskRecord`（`task_store.create_task_run`）增加对应字段
- 数据库 `task_runs` 表增加 `env_url`、`execute_account`、`execute_password` 列

**2.8 MidsceneWebAgent 执行前先登录环境**

文件：`AutoGLM_GUI/agents/midscene_web/async_agent.py`

修改 `_stream_impl` 方法：
1. 优先使用 `env_url`（从 task 传入）而非从文本提取 URL
2. 导航到环境 URL 后，如果提供了 `execute_account` 和 `execute_password`，先执行登录步骤
3. 登录完成后再执行巡检任务

**2.9 midscene-service 增加登录 API**

文件：`g:\workspace\AutoGLM-GUI\midscene-service\server.js` 和 `executor.js`

增加 `POST /login` 接口，接收 `{url, account, password}`，使用 Playwright 在页面上执行登录操作。

---

## 修改文件清单

### 问题 1：任务详情回显

| 文件 | 修改内容 |
|------|---------|
| `frontend/src/views/task/modules/TaskCreateDialog.vue` | 修复 `fillFromEdit`/`fillFromCopy` 中 deviceSerialnos 解析、currentClientOptions 赋值、设备列表加载 |
| `frontend/src/views/task/modules/TaskDetailDialog.vue` | PC Web 部分增加客户端和设备信息展示 |
| `falconconsole/.../vo/TaskCenterVO.java` | 增加 `envUrl`、`executePassword` 字段 |
| `falconconsole/.../impl/PatrolScheduledTaskServiceImpl.java` | `convertToVOList` 中查询 `PatrolSystemEnv` 回填环境 URL 和密码 |

### 问题 2：PC Web 环境信息同步

| 文件 | 修改内容 |
|------|---------|
| `falconconsole/.../impl/PatrolScheduledTaskServiceImpl.java` | `runTaskNow` 中 TASK_DISPATCH 事件增加 env_url/execute_account/execute_password |
| `falconconsole/.../controller/ClientSyncController.java` | `ScheduledTaskSyncItem` 增加 env_url/execute_account/execute_password |
| `AutoGLM_GUI/sync/schemas.py` | `SSETaskDispatch` 和 `ScheduledTaskSyncItem` 增加环境信息字段 |
| `AutoGLM_GUI/models/scheduled_task.py` | `ScheduledTask` 增加 env_url/execute_account/execute_password |
| `AutoGLM_GUI/sync/sync_pull.py` | `_merge_scheduled_task` 传递环境信息字段 |
| `AutoGLM_GUI/sync/push_channel.py` | `_on_task_dispatch` 传递环境信息到 enqueue_scheduled_task |
| `AutoGLM_GUI/task_manager.py` | `enqueue_scheduled_task` 增加环境信息参数 |
| `AutoGLM_GUI/task_store.py` | `create_task_run` 增加 env_url/execute_account/execute_password 字段，DDL 增加列 |
| `AutoGLM_GUI/agents/midscene_web/async_agent.py` | 使用 env_url，执行前先登录 |
| `midscene-service/server.js` | 增加 `/login` 接口 |
| `midscene-service/executor.js` | 增加 `login` 方法 |

---

## 验证步骤

1. **问题 1 验证**：
   - 创建 PC Web 定时任务，选择目标环境、客户端、设备
   - 点击编辑，确认目标环境、执行账号、客户端、设备都已回显
   - 点击查看详情，确认所有字段正确显示

2. **问题 2 验证**：
   - 创建 PC Web 定时任务并立即执行
   - 检查 TASK_DISPATCH 事件数据包含 env_url、execute_account、execute_password
   - 确认客户端接收到环境信息
   - 确认 midscene-service 先导航到环境 URL，执行登录，再执行巡检步骤
