# PC Web 巡检功能 Spec

## Why
当前 AutoGLM-GUI 仅支持 Android 移动设备巡检。需要拓展 PC Web 巡检能力，通过 Midscene-main（TypeScript 原版）的 SDK 驱动浏览器执行 Web 应用巡检，支持 iframe 嵌套页面。

## What Changes

### 新增组件
- **midscene-service**：独立 Node.js 微服务，调用 `@midscene/web` SDK 驱动 Playwright 浏览器
- **MidsceneWebAgent**：Python Agent 实现，通过 HTTP/SSE 调用 midscene-service
- **WebDevice**：Python 设备抽象，实现 `DeviceProtocol`，包装 Node.js 服务的浏览器操作

### 修改组件
- **Agent 工厂**：注册 `"midscene-web"` Agent 类型
- **前端聊天面板**：根据 `terminalType` 区分移动端/PC Web 截图展示
- **Electron 打包脚本**：新增 Node.js 服务打包步骤

### 不变组件
- 服务端（falconconsole）：`terminalType = "PC"` 已支持，无需改动
- 网关（gateway）：透传机制不变
- 同步协议：客户端注册、心跳、任务同步流程不变

## Impact

### Affected specs
- 无已有 spec 冲突

### Affected code

**客户端（AutoGLM-GUI）：**
- `AutoGLM_GUI/agents/factory.py` — 注册新 Agent 类型
- `AutoGLM_GUI/agents/midscene_web/` — 新增目录
- `AutoGLM_GUI/devices/web_device.py` — 新增
- `AutoGLM_GUI/config.py` — 新增 midscene-service 配置项
- `scripts/build_electron.py` — 新增 Node.js 服务打包

**新增目录（midscene-service/）：**
- `package.json`
- `server.js` — HTTP/SSE 服务入口
- `executor.js` — Playwright + Midscene 执行器

**前端（frontend/）：**
- `src/components/ChatKitPanel.tsx` — 截图展示适配

## ADDED Requirements

### Requirement: Midscene Node.js 微服务
系统 SHALL 提供独立的 Node.js 微服务（midscene-service），通过 HTTP API 接收巡检指令，使用 Playwright + `@midscene/web` SDK 驱动浏览器执行巡检。

#### Scenario: 启动浏览器并导航
- **WHEN** 收到 `POST /execute` 请求，包含 `url` 和 `prompt`
- **THEN** 服务启动 Chromium 浏览器，导航到目标 URL，返回 SSE 事件流

#### Scenario: 支持 iframe 嵌套页面
- **WHEN** 目标页面包含同源 iframe
- **THEN** Midscene SDK 能提取 iframe 内元素并执行操作（最多 10 层嵌套）

#### Scenario: 复用系统 Chrome
- **WHEN** 用户系统已安装 Chrome
- **THEN** 优先使用系统 Chrome（`channel: 'chrome'`），否则下载 Playwright Chromium

### Requirement: MidsceneWebAgent
系统 SHALL 提供 `MidsceneWebAgent`，实现 `AsyncAgent` 协议，通过 HTTP/SSE 调用 midscene-service。

#### Scenario: 流式执行巡检任务
- **WHEN** 用户发起 PC Web 巡检任务
- **THEN** Agent 调用 midscene-service，流式返回 thinking/step/done/error 事件

#### Scenario: 取消巡检任务
- **WHEN** 用户取消正在执行的 PC Web 巡检
- **THEN** Agent 通知 midscene-service 终止执行，关闭浏览器页面

### Requirement: WebDevice 设备抽象
系统 SHALL 提供 `WebDevice`，实现 `DeviceProtocol`，将浏览器操作映射为标准设备操作。

#### Scenario: 截图
- **WHEN** 调用 `get_screenshot()`
- **THEN** 返回当前页面截图（base64 + 宽高）

#### Scenario: 点击/输入/滚动
- **WHEN** 调用 `tap(x, y)` / `type_text(text)` / `swipe(...)`
- **THEN** 通过 midscene-service 在浏览器中执行对应操作

### Requirement: Agent 工厂注册
系统 SHALL 在 Agent 工厂中注册 `"midscene-web"` 类型。

#### Scenario: 创建 MidsceneWebAgent
- **WHEN** `agent_type = "midscene-web"` 且 `terminalType = "PC"`
- **THEN** 工厂返回 `MidsceneWebAgent` 实例

### Requirement: 前端截图展示
前端 SHALL 根据 `terminalType` 区分截图展示方式。

#### Scenario: PC Web 巡检截图
- **WHEN** 事件类型为 `step` 且 `terminalType = "PC"`
- **THEN** 使用静态图片展示截图（`<img src={screenshot_url}>`）

#### Scenario: 移动端巡检截图
- **WHEN** 事件类型为 `step` 且 `terminalType = "APP"`
- **THEN** 使用 Scrcpy 流展示实时投屏

### Requirement: Electron 打包集成
Electron 打包 SHALL 包含 midscene-service 的可执行文件。

#### Scenario: 打包 Node.js 服务
- **WHEN** 执行 `build_electron.py`
- **THEN** 使用 `pkg` 将 midscene-service 打包为可执行文件，放入 `resources/midscene-service/`

#### Scenario: 启动 Node.js 服务
- **WHEN** Electron 应用启动
- **THEN** 自动 spawn midscene-service 进程，监听本地端口

## MODIFIED Requirements

### Requirement: Agent 工厂
现有 Agent 工厂需新增 `"midscene-web"` 注册，支持 PC Web 巡检场景。

## REMOVED Requirements
无

## 技术约束

1. **Node.js 版本**：>= 18（Midscene SDK 要求）
2. **Playwright 浏览器**：优先复用系统 Chrome，fallback 到 Playwright Chromium
3. **iframe 支持**：仅支持同源 iframe，跨域 iframe 因浏览器安全限制无法操作
4. **端口分配**：midscene-service 默认端口 39000，可通过环境变量配置
5. **截图格式**：PNG，base64 编码，通过 S3 存储
