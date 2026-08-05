#!/usr/bin/env python3
"""
AutoGLM-GUI Electron 一键构建脚本

功能：
1. 检查环境依赖
2. 同步 Python 开发依赖
3. 构建前端
4. 下载 ADB 工具
5. 打包 Python 后端
6. 打包 midscene-service
7. 构建 Electron 应用

用法：
    uv run python scripts/build_electron.py [--skip-frontend] [--skip-adb] [--skip-backend] [--skip-midscene] [--publish MODE]

发布模式 (--publish):
    never   - 不发布（默认，用于本地开发）
    onTag   - 仅在 git tag 上发布（CI 推荐）
    always  - 总是发布
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

# 修复 Windows 编码问题
if sys.platform == "win32":
    import codecs

    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "strict")
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "strict")


class Color:
    """终端颜色"""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"


def print_step(step: str, total: int, current: int):
    """打印步骤信息"""
    print(f"\n{Color.CYAN}{Color.BOLD}[{current}/{total}] {step}{Color.RESET}")
    print("=" * 60)


def print_success(message: str):
    """打印成功信息"""
    print(f"{Color.GREEN}✓ {message}{Color.RESET}")


def print_error(message: str):
    """打印错误信息"""
    print(f"{Color.RED}✗ {message}{Color.RESET}", file=sys.stderr)


def print_warning(message: str):
    """打印警告信息"""
    print(f"{Color.YELLOW}⚠ {message}{Color.RESET}")


def run_command(
    cmd: list[str],
    cwd: Path | None = None,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> bool:
    """执行命令"""
    cmd_str = " ".join(str(c) for c in cmd)
    print(f"{Color.BLUE}$ {cmd_str}{Color.RESET}")

    try:
        # Windows 下 pnpm/npm 等命令需要通过 shell 执行
        use_shell = sys.platform == "win32" and cmd[0] in ["pnpm", "npm", "npx"]

        result = subprocess.run(
            cmd,
            cwd=cwd,
            check=check,
            capture_output=False,
            text=True,
            shell=use_shell,
            env=env,
        )
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        print_error(f"命令执行失败: {e}")
        return False
    except FileNotFoundError:
        print_error(f"命令未找到: {cmd[0]}")
        return False


def check_command(cmd: str) -> bool:
    """检查命令是否可用"""
    try:
        # Windows 下某些命令（如 pnpm）需要通过 shell 执行
        subprocess.run(
            [cmd, "--version"],
            capture_output=True,
            check=True,
            shell=(sys.platform == "win32"),
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_backend_version(root_dir: Path) -> str:
    """读取后端版本号（用于前端构建注入）。"""
    pyproject_path = root_dir / "pyproject.toml"
    try:
        with pyproject_path.open("rb") as file:
            data = tomllib.load(file)
        return str(data.get("project", {}).get("version") or "unknown")
    except Exception:
        return "unknown"


class ElectronBuilder:
    def __init__(self, args):
        self.args = args
        self.root_dir = Path(__file__).parent.parent
        self.frontend_dir = self.root_dir / "frontend"
        self.scripts_dir = self.root_dir / "scripts"
        self.electron_dir = self.root_dir / "electron"
        self.resources_dir = self.root_dir / "resources"

        # 平台信息
        self.platform = platform.system().lower()
        self.is_windows = self.platform == "windows"
        self.is_macos = self.platform == "darwin"
        self.is_linux = self.platform == "linux"

    def check_environment(self) -> bool:
        """检查环境依赖"""
        print_step("检查环境依赖", 8, 1)

        required_tools = {
            "uv": "Python 包管理器",
            "node": "Node.js 运行时",
            "pnpm": "pnpm 包管理器",
        }

        missing_tools = []
        for tool, description in required_tools.items():
            if check_command(tool):
                print_success(f"{description} ({tool}) 已安装")
            else:
                print_error(f"{description} ({tool}) 未安装")
                missing_tools.append(tool)

        if missing_tools:
            print_error(f"\n缺少必需工具: {', '.join(missing_tools)}")
            print("\n安装指南:")
            if "uv" in missing_tools:
                print("  uv: curl -LsSf https://astral.sh/uv/install.sh | sh")
            if "node" in missing_tools:
                print("  Node.js: https://nodejs.org/")
            if "pnpm" in missing_tools:
                print("  pnpm: npm install -g pnpm")
            return False

        return True

    def sync_python_deps(self) -> bool:
        """同步 Python 开发依赖（含 droidrun 可选依赖）"""
        print_step("同步 Python 开发依赖", 8, 2)
        return run_command(
            ["uv", "sync", "--dev", "--extra", "droidrun"], cwd=self.root_dir
        )

    def build_frontend(self) -> bool:
        """构建前端"""
        print_step("构建前端", 8, 3)

        # 安装前端依赖
        print("\n安装前端依赖...")
        if not run_command(["pnpm", "install"], cwd=self.frontend_dir):
            return False

        # 构建前端
        print("\n构建前端代码...")
        env = os.environ.copy()
        env["VITE_BACKEND_VERSION"] = get_backend_version(self.root_dir)
        print(f"前端构建版本: {env['VITE_BACKEND_VERSION']}")
        if not run_command(["pnpm", "build"], cwd=self.frontend_dir, env=env):
            return False

        # 复制前端构建产物到后端 static 目录
        print("\n复制前端到后端...")
        frontend_dist = self.frontend_dir / "dist"
        backend_static = self.root_dir / "AutoGLM_GUI" / "static"

        if backend_static.exists():
            shutil.rmtree(backend_static)

        shutil.copytree(frontend_dist, backend_static)
        print_success(f"前端已复制到 {backend_static}")

        return True

    def download_adb(self) -> bool:
        """下载 ADB 工具"""
        print_step("下载 ADB 工具", 8, 4)

        # 确定要下载的平台
        platforms = []
        if self.is_windows:
            platforms.append("windows")
        elif self.is_macos:
            platforms.extend(["darwin", "windows"])  # macOS 上构建两个平台
        elif self.is_linux:
            platforms.append("linux")  # Linux 下载自己的 ADB
        else:
            print_warning(f"未知平台 {self.platform}，跳过 ADB 下载")
            return True

        # 下载 ADB
        for plat in platforms:
            print(f"\n下载 {plat} ADB...")
            if not run_command(
                ["uv", "run", "python", "scripts/download_adb.py", plat],
                cwd=self.root_dir,
            ):
                return False

        return True

    def build_backend(self) -> bool:
        """打包 Python 后端"""
        print_step("打包 Python 后端", 8, 5)

        # 清理旧的构建输出
        pyinstaller_dist = self.scripts_dir / "dist" / "autoglm-gui"
        pyinstaller_build = self.scripts_dir / "build" / "autoglm"
        if pyinstaller_dist.exists():
            shutil.rmtree(pyinstaller_dist)
            print_success("清理旧的 PyInstaller dist 输出")
        if pyinstaller_build.exists():
            shutil.rmtree(pyinstaller_build)
            print_success("清理旧的 PyInstaller build 输出")

        # 运行 PyInstaller
        print("\n运行 PyInstaller...")
        if not run_command(
            ["uv", "run", "pyinstaller", "autoglm.spec"], cwd=self.scripts_dir
        ):
            return False

        # 复制到 resources/backend
        print("\n复制后端到 resources...")
        backend_dist = self.scripts_dir / "dist" / "autoglm-gui"
        backend_resources = self.resources_dir / "backend"

        if backend_resources.exists():
            shutil.rmtree(backend_resources)

        shutil.copytree(backend_dist, backend_resources)
        print_success(f"后端已复制到 {backend_resources}")

        return True

    def build_midscene_service(self) -> bool:
        """打包 midscene-service（Node.js 运行时 + 脚本 + Playwright 浏览器）"""
        print_step("打包 midscene-service", 8, 6)

        service_dir = self.root_dir / "midscene-service"
        if not service_dir.exists():
            print_warning("midscene-service 目录不存在，跳过")
            return True

        # 安装依赖
        print("\n安装 midscene-service 依赖...")
        if not run_command(["npm", "install"], cwd=service_dir):
            return False

        # 下载 Playwright Chromium 浏览器到本地目录
        print("\n下载 Playwright Chromium 浏览器...")
        browsers_dir = service_dir / "browsers"
        if browsers_dir.exists():
            shutil.rmtree(browsers_dir)
        browsers_dir.mkdir(parents=True, exist_ok=True)

        browser_install_env = os.environ.copy()
        browser_install_env["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_dir)
        # 使用国内镜像加速下载
        browser_install_env["PLAYWRIGHT_DOWNLOAD_HOST"] = "https://cdn.npmmirror.com/binaries/playwright"
        if not run_command(
            ["npx", "playwright", "install", "chromium"],
            cwd=service_dir,
            env=browser_install_env,
        ):
            print_warning("Playwright 浏览器下载失败，midscene-service 将回退到系统 Chrome")
            return True

        print_success(f"Playwright Chromium 已下载到 {browsers_dir}")

        # 复制到 resources 目录（直接复制脚本 + node_modules，不使用 pkg）
        dest = self.resources_dir / "midscene-service"
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)

        # 复制源码和依赖
        for item in ["server.js", "executor.js", "logger.js", "package.json", "node_modules"]:
            src = service_dir / item
            if src.is_file():
                shutil.copy2(src, dest / item)
            elif src.is_dir():
                shutil.copytree(src, dest / item)
        print_success(f"midscene-service 脚本已复制到 {dest}")

        # 复制 Playwright 浏览器到 resources
        browsers_dest = dest / "browsers"
        if browsers_dir.exists():
            shutil.copytree(browsers_dir, browsers_dest)
            print_success(f"Playwright 浏览器已复制到 {browsers_dest}")

        # 下载 Node.js 独立运行时
        print("\n下载 Node.js 运行时...")
        node_dir = dest / "node-runtime"
        node_dir.mkdir(parents=True, exist_ok=True)

        import urllib.request
        import zipfile

        # 获取当前 Node.js 版本
        node_version_result = subprocess.run(
            ["node", "--version"], capture_output=True, text=True, shell=True
        )
        node_version = node_version_result.stdout.strip().lstrip("v")
        if not node_version:
            node_version = "18.20.4"
            print_warning(f"无法检测 Node 版本，使用默认 {node_version}")

        # 确定 Node.js 下载 URL（使用 npmmirror 镜像）
        arch = "x64" if platform.machine().endswith("64") else "x86"
        if self.is_windows:
            node_url = f"https://cdn.npmmirror.com/binaries/node/v{node_version}/node-v{node_version}-win-{arch}.zip"
            node_exe_name = "node.exe"
        elif self.is_linux:
            node_url = f"https://cdn.npmmirror.com/binaries/node/v{node_version}/node-v{node_version}-linux-{arch}.tar.gz"
            node_exe_name = "bin/node"
        else:
            print_warning(f"不支持的平台 {self.platform}，跳过 Node.js 运行时下载")
            return True

        print(f"下载: {node_url}")
        node_archive = dest / "node-archive"
        try:
            urllib.request.urlretrieve(node_url, node_archive)
        except Exception as e:
            print_warning(f"Node.js 运行时下载失败: {e}")
            return True

        # 解压
        import tarfile
        print("解压 Node.js 运行时...")
        try:
            if self.is_windows:
                with zipfile.ZipFile(node_archive, "r") as zf:
                    zf.extractall(node_dir)
                # 找到 node.exe（在 node-vXX.X.X-win-x64/ 目录下）
                for item in node_dir.iterdir():
                    if item.is_dir() and item.name.startswith("node-v"):
                        src_exe = item / node_exe_name
                        if src_exe.exists():
                            shutil.copy2(src_exe, node_dir / "node.exe")
                        shutil.rmtree(item)
                        break
            else:
                with tarfile.open(node_archive, "r:gz") as tf:
                    tf.extractall(node_dir)
                for item in node_dir.iterdir():
                    if item.is_dir() and item.name.startswith("node-v"):
                        src_exe = item / node_exe_name
                        if src_exe.exists():
                            shutil.copy2(src_exe, node_dir / "node")
                        shutil.rmtree(item)
                        break
        except Exception as e:
            print_warning(f"Node.js 解压失败: {e}")
            return True
        finally:
            if node_archive.exists():
                node_archive.unlink()

        print_success(f"Node.js 运行时已安装到 {node_dir}")

        return True

    def build_electron(self) -> bool:
        """构建 Electron 应用"""
        print_step("安装 Electron 依赖", 8, 7)

        # 安装 Electron 依赖（使用 pnpm，electron-builder 26.x+ 已支持）
        if not run_command(["pnpm", "install"], cwd=self.electron_dir):
            return False

        print_step("构建 Electron 应用", 8, 8)

        # 获取发布模式
        publish_mode = self.args.publish
        print(f"发布模式: {publish_mode}")

        # 构建 Electron
        build_cmd = ["pnpm", "run", "build", "--", "--publish", publish_mode]
        if not run_command(build_cmd, cwd=self.electron_dir):
            if self.is_macos:
                # macOS 上可能需要清理磁盘镜像后重试
                run_command(
                    [
                        "bash",
                        "-lc",
                        "hdiutil info | awk '/\\/dev\\/disk[0-9]+/ {print $1}' | xargs -n1 -I{} hdiutil detach -force -quiet {} || true; "
                        "sudo mdutil -a -i off || true; "
                        "sudo pkill -9 mds || true; "
                        "sudo pkill -9 mds_stores || true; "
                        "sleep 3",
                    ],
                    cwd=self.root_dir,
                )
                if not run_command(build_cmd, cwd=self.electron_dir):
                    return False
            else:
                return False

        # 显示构建产物
        print("\n" + "=" * 60)
        print(f"{Color.GREEN}{Color.BOLD}✓ 构建完成！{Color.RESET}")
        print("=" * 60)

        dist_dir = self.electron_dir / "dist"
        if dist_dir.exists():
            print(f"\n构建产物位置: {dist_dir}")
            print("\n文件列表:")
            for item in sorted(dist_dir.iterdir()):
                if item.is_file():
                    size = item.stat().st_size / (1024 * 1024)
                    print(f"  - {item.name} ({size:.1f} MB)")
                elif item.is_dir() and not item.name.startswith("."):
                    print(f"  - {item.name}/ (目录)")

        return True

    def build(self) -> bool:
        """执行完整构建流程"""
        print(f"\n{Color.BOLD}AutoGLM-GUI Electron 构建工具{Color.RESET}")
        print(f"平台: {self.platform}")
        print(f"项目根目录: {self.root_dir}\n")

        # 仅构建 midscene-service
        if self.args.midscene_only:
            print(f"{Color.CYAN}仅构建 midscene-service{Color.RESET}\n")
            steps = [
                ("环境检查", lambda: self.check_environment()),
                ("midscene-service", lambda: self.build_midscene_service()),
            ]
        else:
            steps = [
                ("环境检查", lambda: self.check_environment()),
                ("Python 依赖", lambda: self.sync_python_deps()),
                (
                    "前端构建",
                    lambda: self.build_frontend()
                    if not self.args.skip_frontend
                    else (print_warning("跳过前端构建"), True)[1],
                ),
                (
                    "ADB 工具",
                    lambda: self.download_adb()
                    if not self.args.skip_adb
                    else (print_warning("跳过 ADB 下载"), True)[1],
                ),
                (
                    "后端打包",
                    lambda: self.build_backend()
                    if not self.args.skip_backend
                    else (print_warning("跳过后端打包"), True)[1],
                ),
                (
                    "midscene-service",
                    lambda: self.build_midscene_service()
                    if not self.args.skip_midscene
                    else (print_warning("跳过 midscene-service 打包"), True)[1],
                ),
                ("Electron", lambda: self.build_electron()),
            ]

        for step_name, step_func in steps:
            if not step_func():
                print_error(f"\n构建失败: {step_name}")
                return False

        return True


def main():
    parser = argparse.ArgumentParser(description="AutoGLM-GUI Electron 一键构建脚本")
    parser.add_argument("--skip-frontend", action="store_true", help="跳过前端构建")
    parser.add_argument("--skip-adb", action="store_true", help="跳过 ADB 工具下载")
    parser.add_argument("--skip-backend", action="store_true", help="跳过后端打包")
    parser.add_argument("--skip-midscene", action="store_true", help="跳过 midscene-service 打包")
    parser.add_argument("--midscene-only", action="store_true", help="仅构建 midscene-service（含 Playwright 浏览器）")
    parser.add_argument(
        "--publish",
        choices=["never", "onTag", "always"],
        default="never",
        help="发布模式: never(默认), onTag(CI推荐), always",
    )
    args = parser.parse_args()

    builder = ElectronBuilder(args)

    try:
        success = builder.build()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print_error("\n\n构建已取消")
        sys.exit(1)
    except Exception as e:
        print_error(f"\n\n构建失败: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
