# Checklist

## midscene-service Node.js 微服务
- [x] `midscene-service/package.json` 存在且依赖正确
- [x] `POST /health` 接口返回服务状态
- [x] `POST /execute` 接口接收 `{url, prompt}` 并返回 SSE 事件流
- [x] 浏览器启动优先使用系统 Chrome，fallback 到 Playwright Chromium
- [x] `POST /cancel` 接口能终止正在执行的任务
- [x] `POST /screenshot` 返回当前页面截图（base64）
- [x] `POST /tap` 执行坐标点击
- [x] `POST /type` 执行文本输入
- [x] `POST /navigate` 导航到指定 URL

## Python 客户端集成
- [x] `AutoGLM_GUI/devices/web_device.py` 实现 `DeviceProtocol`
- [x] `WebDevice.get_screenshot()` 返回 `Screenshot` 对象
- [x] `WebDevice.tap(x, y)` 通过 HTTP 调用 midscene-service
- [x] `AutoGLM_GUI/agents/midscene_web/async_agent.py` 实现 `AsyncAgent` 协议
- [x] `MidsceneWebAgent.stream()` 返回标准 thinking/step/done/error 事件流
- [x] `MidsceneWebAgent.cancel()` 能取消正在执行的任务
- [x] Agent 工厂注册 `"midscene-web"` 类型和 `"web-patrol"` 别名
- [x] `MIDSCENE_SERVICE_URL` 环境变量生效，默认 `http://localhost:39000`

## 前端适配
- [x] `ChatKitPanel.tsx` 根据 `terminalType` 区分截图展示
- [x] PC Web 巡检使用 `<img>` 展示静态截图
- [x] 移动端巡检保持 Scrcpy 流展示

## Electron 打包
- [x] `scripts/build_electron.py` 包含 Node.js 服务打包步骤
- [x] `electron/main.js` 启动时 spawn midscene-service 进程
- [x] 应用退出时清理 midscene-service 进程

## 端到端验证
- [ ] 手动启动 midscene-service，健康检查通过
- [ ] 通过 Python 客户端发起 PC Web 巡检，完整流程跑通
- [ ] iframe 嵌套页面操作正常
- [ ] 任务取消功能正常
