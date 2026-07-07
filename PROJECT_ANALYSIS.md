# AutoGLM-GUI 工程结构分析

> 本文档基于代码库静态分析生成，覆盖工程整体架构、模块职责、关键运行流程和构建机制。

## 一、工程定位

**AutoGLM-GUI** 是一个 AI 驱动的 Android 自动化桌面应用：用户通过桌面端 UI 输入自然语言指令，后端调用大模型（GLM / Gemini / Qwen / MAI / DroidRun / Midscene）规划动作，再通过 ADB / scrcpy 在 Android 设备上执行截图、点击、滑动、输入等操作，并把过程实时回传到前端展示。

- **License**: Apache-2.0
- **版本**: 1.5.19（前后端同步）
- **Python**: ≥ 3.11
- **Node**: ≥ 18，包管理器为 pnpm
- **构建工具链**: `uv`（Python）、`pnpm`（前端）、`PyInstaller`（后端打包）、`electron-builder`（桌面打包）

## 二、顶层目录结构

```
AutoGLM-GUI/
├── AutoGLM_GUI/        # Python 后端（FastAPI + uvicorn + Socket.IO）
├── frontend/           # React 前端（Vite + TanStack Router + TailwindCSS 4）
├── electron/           # Electron 壳（main.js + preload.js + electron-builder 配置）
├── scripts/            # 构建/校验/打包脚本（build.py、build_electron.py、autoglm.spec 等）
├── docs/               # Docusaurus 文档站
├── tests/              # 单测 + e2e（pytest、playwright）
├── resources/          # 构建中间产物（adb、backend）
├── .github/            # CI/CD 工作流（build.yml、release.yml、_electron-build.yml 等）
├── pyproject.toml      # Python 工程元数据 + 依赖
├── Dockerfile          # 容器化部署
└── docker-compose.yml  # 一键部署
```

## 三、运行时分层架构

```
┌─────────────────────────────────────────────────────────────┐
│ Electron 壳 (electron/)                                       │
│  - 主进程 main.js: spawn 后端、管理窗口、自动更新              │
│  - preload.js: 隔离上下文桥接                                  │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP / SSE / WebSocket(117)
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ Python 后端 (AutoGLM_GUI/)                                    │
│  - FastAPI REST API (/api/*)                                  │
│  - Socket.IO 实时通道 (scrcpy 视频流 + 事件推送)               │
│  - 多 Agent 引擎 (glm/gemini/mai/qwen/droidrun/midscene)      │
│  - 设备管理 (ADB / mDNS / Remote HTTP)                        │
│  - 任务调度 / 历史记录 / 工作流 / 定时任务                      │
└──────────────────────┬──────────────────────────────────────┘
                       │ ADB / scrcpy-server
                       ▼
                Android 设备 / 模拟器
```

Electron 主进程启动时会：
1. 找一个 38000 起的可用端口；
2. spawn `resources/backend/autoglm-gui.exe --no-browser --port <port>`；
3. 健康检查通过后，让 BrowserWindow 加载 `http://127.0.0.1:<port>`。

## 四、Python 后端模块详解

入口: [AutoGLM_GUI/__main__.py](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/__main__.py) —— CLI 解析、配置初始化、uvicorn 启动。

### 4.1 应用装配

| 文件 | 职责 |
|------|------|
| [server.py](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/server.py) | 将 FastAPI 应用与 Socket.IO 服务器通过 `ASGIApp` 组合 |
| [api/__init__.py](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/api/__init__.py) | `create_app()` 工厂：注册 13 个路由模块、CORS、静态资源、SPA fallback、MCP 挂载 |

### 4.2 API 路由（[api/](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/api/)）

| 路由 | 功能 |
|------|------|
| `agents` | Agent 列表 / 类型 / 配置查询 |
| `tasks` | 任务创建 / 查询 / 取消（任务队列） |
| `layered_agent` | 分层规划 Agent（规划器 + 视觉执行器）流式接口 |
| `devices` | 设备列表 / 连接 / mDNS 发现 / QR 配对 |
| `control` | 设备控制（截图、点击、滑动、输入、按键） |
| `media` | 截图、屏幕视频流 |
| `history` | 会话历史、步骤时间线 |
| `scheduled_tasks` | 定时任务 CRUD |
| `workflows` | 工作流模板 CRUD |
| `terminal` | ADB 终端（xterm.js 后端） |
| `mcp` | MCP（Model Context Protocol）工具服务 |
| `metrics` | Prometheus 指标 |
| `health` / `version` | 健康检查 / 版本信息 |

### 4.3 Agent 引擎（[agents/](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/agents/)）

采用 **工厂模式 + 注册表**：

- 接口：[protocols.py](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/agents/protocols.py) 中的 `AsyncAgent` Protocol
  - `run(task)` 完整执行
  - `stream(task)` 异步生成器，事件类型：`thinking` / `step` / `done` / `cancelled` / `error`
  - `cancel()` 立即中断（基于 `asyncio.CancelledError`，关闭 HTTP 连接）
  - `reset()` 清理状态

- 工厂：[factory.py](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/agents/factory.py) 中的 `AGENT_REGISTRY` + `create_agent()`

内置 6 种 Agent：

| 类型 | 模块 | 特点 |
|------|------|------|
| `glm-async` / `async-glm` | [glm/async_agent.py](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/agents/glm/async_agent.py) | AutoGLM Phone 原生流式协议 |
| `mai` | [mai/async_agent.py](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/agents/mai/async_agent.py) | 带轨迹记忆（traj_memory），`history_n` 控制上下文长度 |
| `gemini` / `general-vision` | [gemini/async_agent.py](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/agents/gemini/async_agent.py) | OpenAI 兼容 function calling，适配 Gemini/GPT-4o/Claude |
| `qwen` | [qwen/async_agent.py](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/agents/qwen/async_agent.py) | `<answer>` 标签解析 + AST 修复 + `info()` 交互 |
| `droidrun` | [droidrun/async_agent.py](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/agents/droidrun/async_agent.py) | 包装 DroidRun 的 DroidAgent，需 Portal APK |
| `midscene` | [midscene/async_agent.py](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/agents/midscene/async_agent.py) | 通过 npx 调用 Midscene.js CLI |

### 4.4 分层规划 Agent（[layered_agent_service.py](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/layered_agent_service.py)）

基于 `openai-agents` SDK 实现 **规划器 + 视觉执行器** 双层结构：
- 规划器（Planner）：拆解用户意图，调用 `chat(device_id, message)` 工具
- 视觉模型（Vision Model）：执行具体 UI 动作或回答屏幕信息
- 使用 `SQLiteSession` 持久化规划层会话
- `LAYERED_MAX_TURNS` 默认 50，最小 1

### 4.5 设备抽象（[device_protocol.py](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/device_protocol.py)）

定义 `DeviceProtocol`（同步）和 `AsyncDeviceProtocol`，实现包括：
- [devices/adb_device.py](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/devices/adb_device.py) — 本地 ADB
- [devices/remote_device.py](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/devices/remote_device.py) — HTTP 远程设备
- [devices/mock_device.py](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/devices/mock_device.py) — 测试用状态机

### 4.6 设备管理（[device_manager.py](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/device_manager.py)）

`DeviceManager` 单例：
- 三种标识符体系：`DeviceSerial`（设备身份）/ `ConnectionDeviceID`（传输端点）/ `PrimaryDeviceID`（当前激活端点）
- 后台轮询 ADB 设备列表，缓存状态（`ONLINE` / `OFFLINE` / `DISCONNECTED` / `AVAILABLE_MDNS`）
- 支持 USB / WiFi / mDNS / Remote 多种连接方式
- 使用 `ThreadPoolExecutor` 并发探测

### 4.7 ADB 与 adb_plus

| 目录 | 作用 |
|------|------|
| [adb/](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/adb/) | 底层 ADB：`connection.py`、`device.py`、`input.py`、`screenshot.py`、`apps.py` |
| [adb_plus/](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/adb_plus/) | 增强：mDNS 发现、QR 配对、无线键盘 APK 安装、scrcpy 触摸事件 |

### 4.8 任务编排

- [task_manager.py](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/task_manager.py)：基于队列的 per-device worker，注册 4 种执行器：
  - `classic_chat` —— 经典 Agent
  - `layered_chat` —— 分层 Agent
  - `scheduled_workflow` —— 定时工作流
  - `scheduled_layered_workflow` —— 定时分层工作流
- [task_store.py](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/task_store.py)：SQLite 持久化，状态机 `QUEUED → RUNNING → SUCCEEDED/FAILED/CANCELLED/INTERRUPTED`
- [phone_agent_manager.py](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/phone_agent_manager.py)：Agent 生命周期单例，状态机 `IDLE ↔ BUSY / ERROR / INITIALIZING`，自研 `_AsyncLock` 跨事件循环工作

### 4.9 配置系统（[config_manager.py](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/config_manager.py)）

**四层优先级**：`CLI > 环境变量 > 配置文件 > 默认值`

- 配置文件路径：`~/.config/autoglm/config.json`
- 基于 Pydantic 的类型安全模型（`ConfigModel`）
- 支持 `ThinkingMode`（fast / deep）
- `--reload` 模式下通过环境变量同步给子进程

### 4.10 可观测性

- [trace.py](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/trace.py)：span 化追踪，输出 JSONL 到 `logs/trace_{date}.jsonl`
  - Span 覆盖：`step.llm`、`model.call`、`tool.call`、`device.*`、`adb.*`、`memory.*`、`task_store.*`
  - 默认开启，可通过 `AUTOGLM_TRACE_ENABLED=0` 关闭
- [metrics.py](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/metrics.py)：Prometheus 指标，`/api/metrics` 暴露
- [logger.py](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/logger.py)：loguru，支持控制台 + 文件双输出

### 4.11 持久化模块

| 模块 | 存储 | 用途 |
|------|------|------|
| `task_store.py` | SQLite (`~/.config/autoglm/tasks.db`) | 任务/会话/事件 |
| `history_manager.py` | JSON (`~/.config/autoglm/history/`) | 对话历史 |
| `workflow_manager.py` | JSON (`~/.config/autoglm/workflows.json`) | 工作流模板 |
| `scheduler_manager.py` | JSON + APScheduler | 定时任务 |
| `device_metadata_manager.py` | JSON | 设备元数据 |

### 4.12 scrcpy 实时投屏

- [scrcpy_stream.py](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/scrcpy_stream.py)：启动 scrcpy-server，解码视频流
- [scrcpy_protocol.py](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/scrcpy_protocol.py)：媒体包协议
- [socketio_server.py](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/socketio_server.py)：通过 Socket.IO 把 H.264 包推到前端，前端用 WebCodecs 解码
- 服务端二进制：`AutoGLM_GUI/resources/scrcpy-server-v3.3.3`

### 4.13 资源文件

- [resources/apks/ADBKeyboard.apk](file:///g:/workspace/AutoGLM-GUI/AutoGLM_GUI/resources/apks/) — 用于绕过 IME 输入中文
- `scrcpy-server-v3.3.3` — 投屏服务端，会被 push 到设备执行

## 五、前端模块详解

技术栈：**React 19 + TanStack Router + TailwindCSS 4 + Vite 7 + Radix UI + shadcn/ui**

### 5.1 入口与路由

- [src/main.tsx](file:///g:/workspace/AutoGLM-GUI/frontend/src/main.tsx) — `RouterProvider` + `ThemeProvider` + `I18nProvider`
- [src/routes/](file:///g:/workspace/AutoGLM-GUI/frontend/src/routes/) — 文件式路由：
  - `__root.tsx` — 布局
  - `index.tsx` — 设备首页
  - `chat.tsx` — 聊天主界面
  - `history.tsx` — 历史记录
  - `terminal.tsx` — ADB 终端
  - `workflows.tsx` — 工作流管理
  - `scheduled-tasks.tsx` — 定时任务
  - `logs.tsx` — 日志查看
  - `about.tsx` — 关于页

### 5.2 关键组件

- `ChatKitPanel.tsx` — 对话面板，对接 SSE 流
- `DeviceSidebar.tsx` / `GroupedDeviceList.tsx` — 设备列表
- `ScrcpyPlayer.tsx` — WebCodecs 解码 scrcpy 流
- `DeviceMonitor.tsx` — 设备状态轮询
- `MarkdownContent.tsx` — Markdown 渲染（react-markdown + remark-gfm）

### 5.3 状态与通信

- `api.ts` — REST 客户端（redaxios）
- `lib/sse.ts` — SSE 流式接收
- `hooks/useTaskSessionConversation.ts` — 任务会话状态
- `hooks/useScreenshotPolling.ts` — 截图轮询
- `lib/i18n-context.tsx` — 中英双语
- `lib/theme-provider.tsx` — 主题切换

## 六、Electron 桌面壳

### 6.1 [electron/main.js](file:///g:/workspace/AutoGLM-GUI/electron/main.js) 核心

- **端口管理**：38000 起，100 个端口探测
- **后端进程**：
  - 开发：`uv run autoglm-gui --no-browser --port <port>`
  - 生产：`resources/backend/autoglm-gui.exe --no-browser --port <port> --log-file <userData>/logs/autoglm_{date}.log`
- **ADB 路径注入**：把 `resources/adb/windows/platform-tools` 加到 `PATH`
- **健康检查**：每 500ms 探测，超时 30s
- **窗口生命周期**：`did-start-loading` / `dom-ready` / `did-finish-load` / `did-fail-provisional-load` 全链路日志
- **VC++ 缺失友好提示**：检测到退出码 -1 或 `Failed to load Python DLL` 时引导下载 `vc_redist.x64.exe`
- **自动更新**：`electron-updater` + GitHub Releases，支持 `autoDownload` + `quitAndInstall`

### 6.2 [electron/preload.js](file:///g:/workspace/AutoGLM-GUI/electron/preload.js)

通过 `contextBridge` 暴露安全 API（`contextIsolation: true`、`nodeIntegration: false`）。

### 6.3 [electron/verify-deps.js](file:///g:/workspace/AutoGLM-GUI/electron/verify-deps.js)

`prebuild` 钩子，校验 `electron-updater` / `electron-log` 已安装。

## 七、构建机制

### 7.1 构建脚本总览

| 脚本 | 用途 |
|------|------|
| [scripts/build.py](file:///g:/workspace/AutoGLM-GUI/scripts/build.py) | 仅构建前端 + 复制到 `AutoGLM_GUI/static`，可选 `--pack` 出 wheel |
| [scripts/build_electron.py](file:///g:/workspace/AutoGLM-GUI/scripts/build_electron.py) | 一键打包桌面应用（7 步流水线） |
| [scripts/autoglm.spec](file:///g:/workspace/AutoGLM-GUI/scripts/autoglm.spec) | PyInstaller 配置 |
| [scripts/download_adb.py](file:///g:/workspace/AutoGLM-GUI/scripts/download_adb.py) | 下载 Google platform-tools |
| [scripts/lint.py](file:///g:/workspace/AutoGLM-GUI/scripts/lint.py) | 后端 + 前端统一 lint/format 入口 |

### 7.2 桌面应用构建流水线（build_electron.py 7 步）

```
Step 1: 检查环境 (uv / node / pnpm)
Step 2: uv sync --dev --extra droidrun
Step 3: 前端构建
        - cd frontend && pnpm install
        - VITE_BACKEND_VERSION=1.5.19 pnpm build  (vite build && tsc --noEmit)
        - cp -r frontend/dist → AutoGLM_GUI/static
Step 4: 下载 ADB (resources/adb/<platform>/platform-tools)
Step 5: PyInstaller 打包后端
        - cd scripts && uv run pyinstaller autoglm.spec
        - 输出 scripts/dist/autoglm-gui/
        - cp -r → resources/backend/
Step 6: cd electron && pnpm install
Step 7: pnpm run build -- --publish never
        - electron-builder 按 electron-builder.yml 打包
        - afterPack.js 设置可执行权限
        - 输出 electron/dist/
```

### 7.3 PyInstaller 配置要点（[autoglm.spec](file:///g:/workspace/AutoGLM-GUI/scripts/autoglm.spec)）

| 配置 | 内容 |
|------|------|
| 入口 | `AutoGLM_GUI/__main__.py` |
| binaries | `scrcpy-server-v3.3.3` |
| datas | `static/`（前端）、`apks/`（ADBKeyboard）、`fastmcp` metadata |
| hiddenimports | uvicorn 子模块、FastAPI 子模块、`PIL._tkinter_finder`、`llama_index.llms.openai_like` |
| runtime_hooks | `pyi_rth_utf8.py` — Windows 下强制 stdout/stderr UTF-8 |
| OPTIONS | `X utf8_mode=1` — PyInstaller 6.9+ 必须用此方式启用 UTF-8 模式 |
| 输出模式 | `EXE` + `COLLECT`（目录形式，便于 electron-builder 引用） |

### 7.4 electron-builder 配置要点（[electron-builder.yml](file:///g:/workspace/AutoGLM-GUI/electron/electron-builder.yml)）

```yaml
win:
  target: [nsis, portable]      # 安装包 + 便携版
  icon: icon.ico
nsis:
  oneClick: false               # 非一键安装
  perMachine: false             # 用户级，无需管理员
  createDesktopShortcut: true
  createStartMenuShortcut: true
extraResources:
  - ../resources/backend → backend
  - ../resources/adb → adb
publish:
  provider: github              # 自动更新源
```

### 7.5 最终产物结构

```
AutoGLM-GUI-Setup-1.5.19.exe        # NSIS 安装包
AutoGLM-GUI-1.5.19-portable.exe     # 便携版

安装后目录结构：
AutoGLM GUI/
├─ AutoGLM GUI.exe                 # Electron 主程序
├─ resources/
│  ├─ app.asar                     # main.js + preload.js + 前端代码
│  ├─ backend/                     # PyInstaller 打包的 Python 后端
│  │  ├─ autoglm-gui.exe
│  │  ├─ _internal/                # Python 运行时 + 依赖
│  │  └─ ...                       # static/、scrcpy-server、APK
│  └─ adb/windows/platform-tools/  # ADB 工具
└─ ...Electron 运行时
```

## 八、CI/CD（[.github/workflows/](file:///g:/workspace/AutoGLM-GUI/.github/workflows/)）

- `_electron-build.yml` — 可复用工作流，支持 `windows` / `macos-arm64` / `macos-x64` / `linux` 四平台
- `build.yml` — CI 构建（`--publish never`，上传 artifact）
- `release.yml` — Release 构建（`--publish onTag`，发布到 GitHub Releases）
- `pr-lint.yml` — PR 检查（lint + typecheck + 单测）
- `docker-publish.yml` / `docker-e2e.yml` — Docker 镜像构建与 e2e

Windows 构建关键步骤：
```yaml
env:
  PYTHONIOENCODING: utf-8
run: uv run python scripts/build_electron.py --publish never
```

## 九、关键设计模式

1. **三层解耦**：Electron / Python / Frontend 独立构建，最终组合
2. **Protocol 抽象**：`DeviceProtocol` / `AsyncAgent` 让实现可替换（ADB / Remote / Mock）
3. **工厂 + 注册表**：Agent 通过 `register_agent()` 动态注册，新增类型无需改工厂
4. **单例模式**：`DeviceManager` / `PhoneAgentManager` / `HistoryManager` / `WorkflowManager` / `SchedulerManager` 均为单例
5. **任务队列 + per-device worker**：`TaskManager` 保证同设备任务串行，跨设备并行
6. **四层配置优先级**：CLI > ENV > FILE > DEFAULT
7. **Span 化追踪**：全链路 trace_id 串联 API → LLM → 工具 → ADB
8. **UTF-8 三重保险**：spec OPTIONS + runtime hook + Python codecs，解决 Windows 编码问题
9. **降级友好**：VC++ 缺失时引导下载，而非崩溃
10. **SPA fallback**：FastAPI 通过自定义 `SPAApp` 把非 `/mcp` 请求回退到 `index.html`

## 十、本地开发命令速查

```bash
# 后端开发
uv sync
uv run autoglm-gui --base-url http://localhost:8080/v1 --reload

# 前端开发
cd frontend && pnpm install && pnpm dev

# Electron 开发
cd electron && pnpm install && pnpm run dev

# Lint
uv run python scripts/lint.py --check-only

# 测试
uv run pytest -m "not integration and not e2e" -v

# 桌面打包
uv run python scripts/build_electron.py --publish never
```

## 十一、数据流时序（典型聊天任务）

```
用户输入 "打开微信"
  ↓
前端 POST /api/tasks/{device_id}/sessions/{session_id}/tasks
  ↓
TaskManager 入队 → per-device worker 取出
  ↓
PhoneAgentManager.use_agent_async(device_id)
  ├─ 若无 agent，create_agent(agent_type, model_config, ...)
  └─ 状态 IDLE → BUSY
  ↓
agent.stream("打开微信")
  ├─ 截图 (device.get_screenshot)
  ├─ 调用 LLM (openai.AsyncOpenAI.chat.completions.create)
  ├─ 解析动作 (parser.parse_action)
  ├─ 执行动作 (device.tap / swipe / input)
  └─ 每步 yield {"type": "step", ...}
  ↓
前端 SSE 接收事件 → 渲染思考过程 + 截图 + 动作
  ↓
agent yield {"type": "done", "success": True}
  ↓
PhoneAgentManager 状态 BUSY → IDLE
TaskStore 更新任务状态 → SUCCEEDED
HistoryManager 写入对话记录
trace 输出 summary span + Prometheus 指标
```

---

**文档生成日期**: 2026-07-01
**代码库版本**: 1.5.19
