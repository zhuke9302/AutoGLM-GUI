"""Package version helper."""

from importlib.metadata import version as get_version
from pathlib import Path

try:
    APP_VERSION = get_version("ai-check")
except Exception:
    # 回退：从 pyproject.toml 读取版本（开发模式或打包后未安装元数据时）
    try:
        toml_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
        if toml_path.exists():
            for line in toml_path.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("version"):
                    APP_VERSION = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
            else:
                APP_VERSION = "dev"
        else:
            APP_VERSION = "dev"
    except Exception:
        APP_VERSION = "dev"
