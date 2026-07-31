# Tasks

## 阶段一：midscene-service Node.js 微服务

- [x] Task 1: 创建 midscene-service 项目骨架
  - [x] SubTask 1.1: 创建 `midscene-service/package.json`，依赖 `@midscene/web`、`@anthropic-ai/sdk`、`express`
  - [x] SubTask 1.2: 创建 `midscene-service/server.js`，实现 Express HTTP 服务入口
  - [x] SubTask 1.3: 实现 `POST /health` 健康检查接口

- [x] Task 2: 实现浏览器执行器
  - [x] SubTask 2.1: 创建 `midscene-service/executor.js`，封装 Playwright 浏览器生命周期管理
  - [x] SubTask 2.2: 实现浏览器启动逻辑：优先 `channel: 'chrome'`，fallback 到 Playwright Chromium
  - [x] SubTask 2.3: 实现 `POST /execute` 接口，接收 `{url, prompt}` 参数
  - [x] SubTask 2.4: 实现 SSE 事件流输出：thinking/step/done/error 事件格式
  - [x] SubTask 2.5: 实现 `POST /cancel` 接口，终止正在执行的巡检任务

- [x] Task 3: 实现设备操作接口
  - [x] SubTask 3.1: 实现 `POST /screenshot` 接口，返回当前页面截图（base64）
  - [x] SubTask 3.2: 实现 `POST /tap` 接口，执行坐标点击
  - [x] SubTask 3.3: 实现 `POST /type` 接口，执行文本输入
  - [x] SubTask 3.4: 实现 `POST /navigate` 接口，导航到指定 URL

## 阶段二：Python 客户端集成

- [x] Task 4: 新增 WebDevice 设备抽象
  - [x] SubTask 4.1: 创建 `AutoGLM_GUI/devices/web_device.py`
  - [x] SubTask 4.2: 实现 `DeviceProtocol` 接口：`get_screenshot()`、`tap()`、`type_text()`、`swipe()`
  - [x] SubTask 4.3: 通过 HTTP 调用 midscene-service 的对应接口

- [x] Task 5: 新增 MidsceneWebAgent
  - [x] SubTask 5.1: 创建 `AutoGLM_GUI/agents/midscene_web/__init__.py`
  - [x] SubTask 5.2: 创建 `AutoGLM_GUI/agents/midscene_web/async_agent.py`
  - [x] SubTask 5.3: 实现 `AsyncAgent` 协议的 `stream()` 方法，通过 SSE 调用 midscene-service
  - [x] SubTask 5.4: 实现 `cancel()` 方法，调用 midscene-service 的取消接口
  - [x] SubTask 5.5: 事件格式转换：将 midscene-service 的事件映射为标准 thinking/step/done/error

- [x] Task 6: 注册 Agent 工厂
  - [x] SubTask 6.1: 在 `AutoGLM_GUI/agents/factory.py` 中注册 `"midscene-web"` 类型
  - [x] SubTask 6.2: 添加 `"web-patrol"` 别名

- [x] Task 7: 配置项支持
  - [x] SubTask 7.1: 在 `AutoGLM_GUI/config.py` 中新增 `midscene_service_url` 配置项
  - [x] SubTask 7.2: 支持环境变量 `MIDSCENE_SERVICE_URL`，默认 `http://localhost:39000`

## 阶段三：前端适配

- [x] Task 8: 截图展示适配
  - [x] SubTask 8.1: 在 `ChatKitPanel.tsx` 中根据 `terminalType` 区分截图展示方式
  - [x] SubTask 8.2: PC Web 巡检使用 `<img>` 标签展示静态截图
  - [x] SubTask 8.3: 移动端巡检保持现有 Scrcpy 流展示

## 阶段四：Electron 打包集成

- [x] Task 9: Node.js 服务打包
  - [x] SubTask 9.1: 在 `scripts/build_electron.py` 中新增 Node.js 服务打包步骤
  - [x] SubTask 9.2: 使用 `pkg` 将 midscene-service 打包为可执行文件
  - [x] SubTask 9.3: 将打包产物复制到 `resources/midscene-service/`

- [x] Task 10: Electron 主进程集成
  - [x] SubTask 10.1: 在 `electron/main.js` 中新增 midscene-service 进程启动逻辑
  - [x] SubTask 10.2: 实现进程健康检查和自动重启
  - [x] SubTask 10.3: 应用退出时清理 midscene-service 进程

## 阶段五：验证与测试

- [ ] Task 11: 端到端验证
  - [ ] SubTask 11.1: 手动启动 midscene-service，验证健康检查接口
  - [ ] SubTask 11.2: 通过 Python 客户端发起 PC Web 巡检任务，验证完整流程
  - [ ] SubTask 11.3: 验证 iframe 嵌套页面的操作能力
  - [ ] SubTask 11.4: 验证任务取消功能

# Task Dependencies

- Task 1 → Task 2 → Task 3（Node.js 服务顺序开发）
- Task 4 → Task 5 → Task 6（Python 客户端顺序开发）
- Task 7 可与 Task 4-6 并行
- Task 8 依赖 Task 5（需要知道事件格式）
- Task 9 → Task 10（Electron 打包顺序）
- Task 11 依赖所有前置任务
