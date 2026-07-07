# AutoGLM-GUI 打包构建运行指南

> 本文档面向首次接触本项目的开发者，从零开始讲解环境准备、开发运行、打包构建的完整流程。
> 适用于 Windows / macOS / Linux，文中会标注 Windows 特有步骤。

---

## 目录

- [一、整体概念](#一整体概念)
- [二、环境准备](#二环境准备)
- [三、开发模式运行（最快上手）](#三开发模式运行最快上手)
- [四、生产模式运行（Python 包）](#四生产模式运行python-包)
- [五、打包桌面应用（Electron 可执行文件）](#五打包桌面应用electron-可执行文件)
- [六、Docker 部署](#六docker-部署)
- [七、常见问题](#七常见问题)

---

## 一、整体概念

AutoGLM-GUI 由三部分组成，理解这个结构是看懂构建流程的前提：

```
┌──────────────────────────────────────────────────────┐
│  ① Electron 壳 (electron/)                            │
│     • 桌面窗口、托盘、自动更新                          │
│     • 启动时 spawn 后端进程                             │
├──────────────────────────────────────────────────────┤
│  ② Python 后端 (AutoGLM_GUI/)                         │
│     • FastAPI + Socket.IO 服务                         │
│     • AI Agent、设备控制、任务调度                      │
│     • 内嵌前端静态文件 (static/)                        │
├──────────────────────────────────────────────────────┤
│  ③ React 前端 (frontend/)                             │
│     • Vite 打包成静态文件后，注入到后端 static/          │
└──────────────────────────────────────────────────────┘
```

**三种使用形态对应三套流程**：

| 形态 | 用途 | 入口 |
|------|------|------|
| 开发模式 | 改代码、热重载 | 前后端分别起 dev server |
| Python 包 | 服务器部署、pip 安装 | `autoglm-gui` CLI |
| 桌面应用 | 给终端用户的 `.exe` / `.dmg` | Electron 打包产物 |

---

## 二、环境准备

### 2.1 必备工具

| 工具 | 版本要求 | 安装方式 | 用途 |
|------|---------|---------|------|
| **Python** | ≥ 3.11 | [python.org](https://www.python.org/) | 后端运行时 |
| **uv** | 最新 | `powershell -c "irm https://astral.sh/uv/install.ps1 \| iex"` | Python 包管理器 |
| **Node.js** | ≥ 18 | [nodejs.org](https://nodejs.org/) | 前端构建 + Electron |
| **pnpm** | 最新 | `npm install -g pnpm` | 前端包管理器 |
| **ADB** | 最新 | [Android Platform Tools](https://developer.android.com/tools/releases/platform-tools) | 设备通信（开发模式） |
| **Git** | 任意 | [git-scm.com](https://git-scm.com/) | 拉取代码 |

> **Windows 注意**：ADB 安装后需将其 `platform-tools` 目录加到系统 `PATH` 环境变量。

### 2.2 验证环境

打开 PowerShell（Windows）或 Terminal（macOS/Linux），执行：

```powershell
python --version    # 应 ≥ 3.11
uv --version
node --version      # 应 ≥ 18
pnpm --version
adb version
git --version
```

任一命令报错，请回到 2.1 重新安装对应工具。

### 2.3 克隆代码

```powershell
cd G:\workspace
git clone https://github.com/suyiiyii/AutoGLM-GUI.git
cd AutoGLM-GUI
```

### 2.4 准备 Android 设备

1. 手机开启「开发者选项」→「USB 调试」
2. USB 连接电脑，执行 `adb devices` 应能看到设备
3. 若用 WiFi 调试，在「无线调试」里查到 `IP:端口`，再用 `adb connect 192.168.x.x:5555`

### 2.5 准备模型服务

AutoGLM-GUI 需要一个 OpenAI 兼容的视觉模型 API。三选一：

- **智谱 BigModel**：到 [open.bigmodel.cn](https://open.bigmodel.cn/) 申请 API Key，使用 `autoglm-phone-9b` 模型
- **ModelScope**：到 [modelscope.cn](https://modelscope.cn/) 申请
- **自建服务**：vLLM / SGLang 等，监听 `http://localhost:8080/v1`

记下三个信息：`Base URL`、`API Key`、`Model Name`，后续步骤会用到。

---

## 三、开发模式运行（最快上手）

适合改代码调试，前后端独立启动，都支持热重载。

### 3.1 安装依赖

```powershell
# 后端依赖（项目根目录）
uv sync （uv sync --python 3.12.13）

# 前端依赖
cd frontend
pnpm install
cd ..
```

```
注意：如果 uv sync 报错，尝试指定 Python 版本（如 3.12.13）
安装一些exe等依赖时，可能会被 Windows Defender 拦截，需要加入排除项。
1. Windows 安全中心 → 病毒和威胁防护 → 管理设置 → 排除项 → 添加排除项 → 文件夹
2. 依次添加：
   - G:\workspace\AutoGLM-GUI
   - G:\workspace\AutoGLM-GUI\.venv
   - C:\Users\zhuke\AppData\Local\uv
   - C:\Users\zhuke\AppData\Local\Temp


:: 1. 关闭 Windows Defender 实时保护（手动操作 GUI）

:: 2. 执行安装
cd /d G:\workspace\AutoGLM-GUI
set UV_LINK_MODE=copy
uv sync --python 3.12.13

:: 3. 验证
.venv\Scripts\python.exe -c "import fastapi, openai, uvicorn; print('OK')"

:: 4. 重新打开 Windows Defender 实时保护（手动操作 GUI）
```


### 3.2 启动后端

新开一个终端，在项目根目录执行：

```powershell
uv run autoglm-gui --base-url http://localhost:8080/v1 --apikey YOUR_KEY --model autoglm-phone-9b --reload
```

参数说明：
- `--base-url`：模型 API 地址（必填，或稍后在 UI 里配置）
- `--apikey`：API Key（也可用环境变量 `AUTOGLM_API_KEY`）
- `--model`：模型名，默认 `autoglm-phone-9b`
- `--reload`：代码改动自动重启
- `--port`：可选，不指定则从 8000 起自动找空闲端口

启动成功会打印：
```
==================================================
  AutoGLM-GUI - Phone Agent Web Interface
==================================================
  Version:    1.5.19
  Server:     http://127.0.0.1:8000
  ...
```

### 3.3 启动前端

再开一个终端：

```powershell
cd frontend
pnpm dev
```

前端开发服务器跑在 `http://localhost:3000`，会自动把 `/api/*` 和 `/socket.io/*` 代理到后端（默认 `http://localhost:8000`，见 [vite.config.js](file:///g:/workspace/AutoGLM-GUI/frontend/vite.config.js)）。

### 3.4 访问应用

浏览器打开 `http://localhost:3000`，看到设备首页即成功。

**首次配置模型**：点击左侧「设置」按钮，填写 Base URL / API Key / Model Name，点「测试连接」通过后「保存配置」。详见 [docs/guide/configure-model.md](file:///g:/workspace/AutoGLM-GUI/docs/docs/guide/configure-model.md)。

### 3.5（可选）Electron 开发模式

如果要在 Electron 窗口里调试：

```powershell
cd electron
pnpm install
pnpm run dev
```

Electron 会以 dev 模式启动后端（`uv run autoglm-gui`），并加载前端 `http://127.0.0.1:<port>`。

---

## 四、生产模式运行（Python 包）

把前端构建进后端，作为单一 Python 服务运行。适合服务器部署。

### 4.1 构建前端并注入后端

```powershell
# 项目根目录
uv run python scripts/build.py
```

这个脚本做了两件事（见 [scripts/build.py](file:///g:/workspace/AutoGLM-GUI/scripts/build.py)）：
1. `cd frontend && pnpm install && pnpm build` —— Vite 构建前端
2. 把 `frontend/dist/` 复制到 `AutoGLM_GUI/static/`

### 4.2 直接运行

```powershell
uv run autoglm-gui --host 0.0.0.0 --port 8000 --no-browser
```

浏览器访问 `http://localhost:8000`，前后端由同一个服务提供。

### 4.3（可选）打包成 wheel 分发

```powershell
uv run python scripts/build.py --pack
```

产出 `dist/autoglm_gui-1.5.19-py3-none-any.whl`。别人拿到这个 wheel 后：

```powershell
pip install autoglm_gui-1.5.19-py3-none-any.whl
autoglm-gui --base-url http://localhost:8080/v1
```

### 4.4 服务器部署要点

```powershell
# 监听所有网卡（局域网可访问）
autoglm-gui --host 0.0.0.0 --port 8000 --no-browser

# 启用 HTTPS（远程访问实时视频流必需）
autoglm-gui --host 0.0.0.0 --port 8000 --no-browser \
  --ssl-keyfile /path/to/key.pem \
  --ssl-certfile /path/to/cert.pem

# 自定义 CORS
$env:AUTOGLM_CORS_ORIGINS="https://app.example.com"
autoglm-gui --host 0.0.0.0 --port 8000 --no-browser
```

完整服务器部署指南：[docs/guide/deploy-server.md](file:///g:/workspace/AutoGLM-GUI/docs/docs/guide/deploy-server.md)

---

## 五、打包桌面应用（Electron 可执行文件）

这是最复杂也是最完整的流程，产出给终端用户的 `.exe` / `.dmg` / `.AppImage`。

### 5.1 一键打包

在项目根目录执行：

```powershell
uv run python scripts/build_electron.py --publish never
```

`--publish never` 表示只本地打包，不发布到 GitHub Releases。其他模式：
- `--publish onTag`：CI 推荐，仅在 git tag 上发布
- `--publish always`：总是发布（需要 `GH_TOKEN` 环境变量）

### 5.2 构建流水线详解

[scripts/build_electron.py](file:///g:/workspace/AutoGLM-GUI/scripts/build_electron.py) 会按顺序执行 7 步，每步失败都会终止：

```
Step 1/7  检查环境依赖（uv / node / pnpm）
          ↓ 失败会打印安装指引
          
Step 2/7  uv sync --dev --extra droidrun
          ↓ 安装 Python 开发依赖（含 PyInstaller）
          
Step 3/7  构建前端
          ├─ cd frontend && pnpm install
          ├─ VITE_BACKEND_VERSION=1.5.19 pnpm build
          └─ cp -r frontend/dist → AutoGLM_GUI/static
          
Step 4/7  下载 ADB 工具
          └─ resources/adb/windows/platform-tools/adb.exe
          
Step 5/7  PyInstaller 打包后端
          ├─ cd scripts && uv run pyinstaller autoglm.spec
          ├─ 输出 scripts/dist/autoglm-gui/
          │   ├─ autoglm-gui.exe          ← Python 后端可执行文件
          │   └─ _internal/               ← Python 运行时 + 依赖库
          └─ cp -r → resources/backend/
          
Step 6/7  安装 Electron 依赖
          └─ cd electron && pnpm install
          
Step 7/7  electron-builder 打包
          ├─ pnpm run build -- --publish never
          ├─ afterPack.js 设置可执行权限
          └─ 输出 electron/dist/
```

### 5.3 跳过某些步骤（增量构建）

调试打包流程时，可以跳过已完成的步骤加速：

```powershell
# 跳过前端构建（已经构建过）
uv run python scripts/build_electron.py --skip-frontend --publish never

# 跳过 ADB 下载
uv run python scripts/build_electron.py --skip-adb --publish never

# 跳过后端打包
uv run python scripts/build_electron.py --skip-backend --publish never

# 全跳过，只重新跑 electron-builder
uv run python scripts/build_electron.py --skip-frontend --skip-adb --skip-backend --publish never
```

### 5.4 构建产物

打包完成后，`electron/dist/` 目录下会有：

**Windows**：
```
AutoGLM-GUI-Setup-1.5.19.exe        # NSIS 安装包（推荐分发）
AutoGLM-GUI-1.5.19-portable.exe     # 便携版（免安装）
```

**macOS**：
```
AutoGLM-GUI-1.5.19.dmg              # DMG 镜像
AutoGLM-GUI-1.5.19-mac.zip          # ZIP 备用
```

**Linux**：
```
AutoGLM-GUI-1.5.19.AppImage         # 通用格式
autoglm-gui_1.5.19_amd64.deb        # Debian/Ubuntu
autoglm-gui-1.5.19.tar.gz           # 便携版
```

### 5.5 产物内部结构

以 Windows 安装版为例，安装后目录：

```
AutoGLM GUI/
├─ AutoGLM GUI.exe                  ← Electron 主程序（用户双击启动）
├─ resources/
│  ├─ app.asar                      ← 打包的 main.js + preload.js + 前端代码
│  ├─ backend/                      ← PyInstaller 打包的 Python 后端
│  │  ├─ autoglm-gui.exe           ← 后端可执行文件
│  │  ├─ _internal/                ← Python 3.11 运行时 + 所有依赖
│  │  └─ ...                       ← static/（前端）、scrcpy-server、APK
│  └─ adb/windows/platform-tools/  ← ADB 工具
└─ ...Electron 运行时（Chromium、Node.js）
```

### 5.6 运行打包后的应用

双击 `AutoGLM GUI.exe`，Electron 主进程会：
1. 从 38000 起找可用端口
2. spawn `resources/backend/autoglm-gui.exe --no-browser --port <port>`
3. 注入 `resources/adb/windows/platform-tools` 到 `PATH`
4. 每 500ms 健康检查后端，超时 30s
5. 后端就绪后，BrowserWindow 加载 `http://127.0.0.1:<port>`

日志位置：
- Windows: `%APPDATA%/AutoGLM GUI/logs/autoglm_YYYY-MM-DD.log`
- macOS: `~/Library/Application Support/AutoGLM GUI/logs/`
- Linux: `~/.config/AutoGLM GUI/logs/`

### 5.7 平台交叉构建限制

electron-builder 不支持交叉编译，**在哪个平台打包就出哪个平台的产物**：

| 运行平台 | 可产出 |
|---------|--------|
| Windows | `.exe`（nsis + portable） |
| macOS | `.dmg` |
| Linux | `.AppImage` / `.deb` / `.tar.gz` |

需要同时发布三平台？用 GitHub Actions，配置见 [.github/workflows/build.yml](file:///g:/workspace/AutoGLM-GUI/.github/workflows/build.yml)，它会在 `windows-latest` / `macos-latest` / `ubuntu-22.04` 三个 runner 上并行构建。

---

## 六、Docker 部署

适合服务器 7x24 运行，免装环境。

### 6.1 使用官方镜像

```powershell
docker-compose up -d
```

[docker-compose.yml](file:///g:/workspace/AutoGLM-GUI/docker-compose.yml) 会拉镜像并启动服务，默认监听 8000 端口。

### 6.2 自行构建镜像

```powershell
docker build -t autoglm-gui .
docker run -d -p 8000:8000 -v ~/.config/autoglm:/root/.config/autoglm autoglm-gui
```

详见 [docs/guide/deploy-docker.md](file:///g:/workspace/AutoGLM-GUI/docs/docs/guide/deploy-docker.md)。

---

## 七、常见问题

### Q1: Windows 打包后启动报「Failed to load Python DLL」

缺少 Microsoft Visual C++ 运行库。打包后的应用会自动检测并提示，点击「下载」跳转到官方页面安装 [vc_redist.x64.exe](https://aka.ms/vs/17/release/vc_redist.x64.exe) 即可。

### Q2: PyInstaller 打包报「ModuleNotFoundError」

PyInstaller 无法自动检测动态导入的模块。编辑 [scripts/autoglm.spec](file:///g:/workspace/AutoGLM-GUI/scripts/autoglm.spec)，在 `hiddenimports` 列表里加上缺失的模块名，重新打包。

### Q3: 前端构建报 TypeScript 错误

```powershell
cd frontend
pnpm type-check    # 看具体错误
pnpm lint          # ESLint 检查
```

修复后再跑 `pnpm build`。

### Q4: ADB 连不上设备

```powershell
adb kill-server
adb start-server
adb devices         # 应显示设备序列号
```

如果显示 `unauthorized`，手机上确认 USB 调试授权弹窗。

### Q5: 实时视频流不工作（远程访问）

浏览器的媒体能力只在「安全上下文」可用。`localhost` 算安全上下文，但 `http://<服务器IP>:8000` 不算。解决方法：
- 用 `--ssl-keyfile` + `--ssl-certfile` 启用 HTTPS，或
- 在前面放 Nginx / Caddy 反向代理终结 TLS

### Q6: 打包体积太大

PyInstaller 默认包含完整 Python 运行时。可尝试：
- 在 `autoglm.spec` 的 `excludes` 里排除不需要的模块
- 启用 UPX 压缩（`upx=True`），但首次打包不建议，可能引入稳定性问题

### Q7: electron-builder 报网络错误（下载 Electron 二进制慢）

设置镜像：
```powershell
$env:ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"
$env:ELECTRON_BUILDER_BINARIES_MIRROR="https://npmmirror.com/mirrors/electron-builder-binaries/"
```

### Q8: 如何只重新打包后端（跳过其他步骤）

```powershell
# 先确保 resources/backend 已清理
Remove-Item -Recurse -Force resources\backend -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force scripts\dist -ErrorAction SilentlyContinue

# 只跑后端打包 + Electron
uv run python scripts/build_electron.py --skip-frontend --skip-adb --publish never
```

---

## 附录：命令速查表

| 场景 | 命令 |
|------|------|
| 安装后端依赖 | `uv sync` |
| 安装前端依赖 | `cd frontend && pnpm install` |
| 启动后端（开发） | `uv run autoglm-gui --reload` |
| 启动前端（开发） | `cd frontend && pnpm dev` |
| 启动 Electron（开发） | `cd electron && pnpm run dev` |
| 构建前端到后端 | `uv run python scripts/build.py` |
| 构建 wheel 包 | `uv run python scripts/build.py --pack` |
| 一键打包桌面应用 | `uv run python scripts/build_electron.py --publish never` |
| Lint 检查 | `uv run python scripts/lint.py --check-only` |
| Lint 自动修复 | `uv run python scripts/lint.py` |
| 后端类型检查 | `uv run pyright AutoGLM_GUI/` |
| 前端类型检查 | `cd frontend && pnpm type-check` |
| 单元测试 | `uv run pytest -m "not integration and not e2e" -v` |
| 全部测试 | `uv run pytest -v` |
| Docker 部署 | `docker-compose up -d` |

---

**文档生成日期**: 2026-07-01
**项目版本**: 1.5.19
