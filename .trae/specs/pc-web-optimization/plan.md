# PC Web 巡检逻辑优化方案

## 背景

当前客户端支持移动设备（App）和 PC Web 两种巡检模式。PC Web 巡检逻辑为后加功能，存在以下三个问题，需参考移动端巡检逻辑进行优化。

---

## 问题1: PC Web 断言失败抛异常 — 区分运行失败和业务失败

### 现状

- PC Web 断言步骤使用 `aiAct` 执行，断言不通过时模型可能抛出异常或返回错误
- `task_manager.py` 已有断言解析逻辑：从 `done` 事件中提取 `RESULT: PASS/FAIL`，将断言失败映射为 `business_status=abnormal` + `status=SUCCEEDED`
- 但 `executor.js` 中 `aiAct` 不保证稳定返回 PASS/FAIL 格式，容易抛异常导致任务直接标记为 `FAILED`（运行失败）

### 方案

在 `midscene-service/executor.js` 中，检测断言 prompt 并使用 `aiAssert` 代替 `aiAct`：

1. **新增 `_extractAssertionPrompt(prompt)`**：检测以"断言"开头的 prompt，提取纯断言内容（去除前缀和 `_ASSERTION_SUFFIX`）
2. **新增 `_executeAssertion(url, assertionContent, onEvent, stepCount)`**：使用 `aiAssert` 执行断言
   - **关键**：传入 `keepRawResponse: true` 选项，让 `aiAssert` 返回 `{pass, thought, message}` 对象而非抛异常
   - `pass=true` → `done` 事件，message="RESULT: PASS"，success=true
   - `pass=false` → `done` 事件，message="RESULT: FAIL"，success=false（**业务失败，不抛异常**）
   - 执行异常（如浏览器崩溃）→ `error` 事件（运行失败）
3. **修改 `execute()` 方法**：在导航完成后、创建 `aiAct` 之前，先检测是否为断言 prompt，若是则走 `_executeAssertion` 分支

> **注意**：`@midscene/core` 的 `aiAssert` 默认行为是断言失败时抛异常（`throw new Error(message)`），必须传 `keepRawResponse: true` 才能拿到返回值而不抛异常。

### 改动文件

| 文件 | 改动 |
|------|------|
| `midscene-service/executor.js` | 新增 `_extractAssertionPrompt()`、`_executeAssertion()` 方法；`execute()` 中增加断言分支判断 |

### 效果

- 断言失败 → `business_status=abnormal`，`status=SUCCEEDED`（业务异常，任务本身运行成功）
- 运行异常 → `status=FAILED`（运行失败，如浏览器崩溃、网络断开等）
- 与移动端行为一致

---

## 问题2: 后台定时任务多个时，PC Web 如何排队

### 现状

- 移动端：`task_manager.py` 使用 per-device worker 队列（`_device_worker(device_id)`），同一设备的任务串行执行
- PC Web：`device_manager.get_devices()` 不返回 web-browser 设备，导致：
  - `scheduler_manager._execute_task()` 查找在线设备时找不到 web-browser
  - `push_channel._on_task_dispatch()` 查找在线设备时找不到 web-browser
  - 服务端 `PatrolScheduledTaskController.save()` 不为 PC Web 任务填充 `deviceSerialnos`
  - 服务端 `runTaskNow()` 跳过非 APP 端任务

### 方案

#### 客户端：注册 web-browser 虚拟设备

1. **新增 `WEB_BROWSER_SERIAL = "web-browser"` 常量**
2. **新增 `_create_web_browser_device()` 函数**：创建始终在线的虚拟设备，serial="web-browser"，model="PC Web Browser"，connection_type=REMOTE，state=ONLINE
3. **修改 `get_devices()`**：返回列表中追加 web-browser 虚拟设备
4. **修改 `get_connected_devices()`**：同上
5. **修改 `get_device_by_serial(serial)`**：serial="web-browser" 时返回虚拟设备
6. **修改 `get_device_by_device_id(device_id)`**：device_id="web-browser" 时返回虚拟设备

#### 服务端：PC Web 任务填充 deviceSerialnos 并推送 SSE

7. **修改 `PatrolScheduledTaskController.save()`**：PC Web 任务自动填充 `deviceSerialnos=["web-browser"]`
8. **修改 `PatrolScheduledTaskController.save()`**：移除 `TerminalType.isApp()` 条件，PC Web 任务也推送 SSE 通知
9. **修改 `PatrolScheduledTaskController.update()`**：同上
10. **修改 `PatrolScheduledTaskController.delete()`**：同上
11. **修改 `PatrolScheduledTaskController.toggle()`**：同上

#### 服务端：PC Web 任务立即执行

12. **修改 `PatrolScheduledTaskServiceImpl.runTaskNow()`**：PC Web 任务查找拥有 web-browser 设备的在线客户端，通过 SSE 派发 `TASK_DISPATCH` 事件

### 改动文件

| 文件 | 改动 |
|------|------|
| `AutoGLM_GUI/device_manager.py` | 新增 `WEB_BROWSER_SERIAL`、`_create_web_browser_device()`；修改 `get_devices()`、`get_connected_devices()`、`get_device_by_serial()`、`get_device_by_device_id()` |
| `falconconsole/.../PatrolScheduledTaskController.java` | `save()` 填充 deviceSerialnos + 推送 SSE；`update()`/`delete()`/`toggle()` 推送 SSE |
| `falconconsole/.../PatrolScheduledTaskServiceImpl.java` | `runTaskNow()` 支持 PC Web 任务派发 |

### 排队机制

PC Web 任务绑定 `device_serial="web-browser"`，`task_manager` 按 device_id 创建 worker 队列。多个 PC Web 定时任务由同一个 `web-browser` worker 串行执行，与移动端设备排队逻辑一致。

---

## 问题3: PC Web 没有注册上服务端

### 现状

- `device_reporter.report_all_devices()` 遍历 `device_manager.get_devices()` 上报设备
- `get_devices()` 不包含 web-browser 设备，导致服务端看不到 PC Web 设备

### 方案

此问题已在问题2中一并解决：

1. `get_devices()` 返回 web-browser 虚拟设备 → `device_reporter` 自动上报
2. 服务端 `patrol_client_devices` 表会记录 serial="web-browser"、connection_type="remote"、status="online"
3. 服务端 `runTaskNow()` 可通过查询 `patrol_client_devices` 表找到拥有 web-browser 设备的客户端

### 改动文件

同问题2，无需额外改动。

---

## 改动总览

| 仓库 | 文件 | 改动类型 |
|------|------|----------|
| AutoGLM-GUI (客户端) | `midscene-service/executor.js` | 新增断言检测 + aiAssert 执行 |
| AutoGLM-GUI (客户端) | `AutoGLM_GUI/device_manager.py` | 新增 web-browser 虚拟设备 |
| falconconsole (服务端) | `PatrolScheduledTaskController.java` | PC Web 任务填充 deviceSerialnos + SSE 推送 |
| falconconsole (服务端) | `PatrolScheduledTaskServiceImpl.java` | runTaskNow 支持 PC Web |

## 数据流

```
服务端创建 PC Web 定时任务
  → deviceSerialnos=["web-browser"]
  → SSE 推送 SCHEDULED_TASK_CHANGED / WORKFLOW_CHANGED
  → 客户端 sync_pull 同步任务

客户端 scheduler_manager 定时触发
  → _resolve_device_serialnos() 返回 ["web-browser"]
  → device_manager.get_devices() 包含 web-browser (state=ONLINE)
  → task_manager.enqueue_scheduled_task(device_serial="web-browser")
  → _device_worker("web-browser") 串行执行

服务端 runTaskNow
  → 查询 patrol_client_devices (serial=web-browser, status=online)
  → SSE 推送 TASK_DISPATCH 到对应客户端
  → push_channel._on_task_dispatch() 处理
  → task_manager.enqueue_scheduled_task(device_serial="web-browser")

设备上报
  → device_reporter.report_all_devices()
  → get_devices() 包含 web-browser
  → 服务端 patrol_client_devices 表记录 web-browser 设备
```
