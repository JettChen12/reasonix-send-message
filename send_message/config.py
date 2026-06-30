"""配置加载——基础设施，不包含任何平台特有逻辑。

提供 TOML 解析、.env 加载等公共服务。
``resolve_config()`` 通过 ``SENDERS`` 注册表发现各平台的配置解析器并调用之。
"""

import os
import re
from pathlib import Path
from typing import Any, Dict

# ---------- 路径常量 ----------

REASONIX_DIR = Path.home() / ".reasonix"
CONFIG_TOML = REASONIX_DIR / "config.toml"
DOTENV_FILE = REASONIX_DIR / ".env"


class ConfigError(Exception):
    """配置相关错误的基类。"""


class ConfigSourceError(ConfigError):
    """某个数据源缺失或不可读。"""


# ==============================================================
#  TOML 解析器（兼容 Python 3.8+）
# ==============================================================

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # pip install tomli
    except ImportError:
        tomllib = None  # type: ignore[assignment]


def _check_toml_lib() -> None:
    """检查 TOML 解析库是否可用。"""
    if tomllib is None:
        raise ConfigSourceError(
            "需要 TOML 解析库，但当前 Python 环境未提供。\n"
            "  - Python 3.11+ 已内置 tomllib\n"
            "  - 旧版本请执行: pip install tomli"
        )


def read_toml(path: Path) -> Dict[str, Any]:
    """读取并解析 TOML 配置文件。"""
    _check_toml_lib()
    if not path.exists():
        raise ConfigSourceError(
            f"Reasonix 配置文件不存在：{path}\n"
            f"请先通过 Reasonix 完成飞书/微信的扫码登录配置。"
        )
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception as e:
        raise ConfigSourceError(f"解析 TOML 文件失败 ({path}): {e}")


# ==============================================================
#  .env 解析器
# ==============================================================

def read_dotenv(path: Path) -> Dict[str, str]:
    """解析 .env 文件为键值对（简单实现，无外部依赖）。"""
    if not path.exists():
        return {}
    env: Dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(.*?)\s*$', line)
            if m:
                key = m.group(1)
                val = m.group(2).strip()
                if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                    val = val[1:-1]
                env[key] = val
    return env


def load_dotenv_into_environ() -> None:
    """将 ``~/.reasonix/.env`` 中的变量加载到 ``os.environ``（不覆盖已存在的）。"""
    env_vars = read_dotenv(DOTENV_FILE)
    for key, val in env_vars.items():
        if key not in os.environ:
            os.environ[key] = val


# ==============================================================
#  公开 API
# ==============================================================

def resolve_config() -> Dict[str, Any]:
    """从 Reasonix 权威数据源解析完整配置。

    遍历 ``SENDERS`` 注册表，调用每个 sender module 的 ``resolve_config()`` 方法，
    将返回的配置按平台名聚合。

    返回结构::

        {
            "text_source": "argument",
            "text_file": "",
            "feishu": {"enabled": bool, "app_id": str, ...},
            "weixin": {"enabled": bool, "account_id": str, ...},
        }

    Raises:
        ConfigError: 当必填数据源缺失时。
    """
    # 延迟 import 避免循环依赖：config.py ← feishu.py ← __init__.py
    from send_message import SENDERS

    toml_data = read_toml(CONFIG_TOML)
    bot_cfg = toml_data.get("bot", {})

    load_dotenv_into_environ()

    cfg: Dict[str, Any] = {
        "text_source": "argument",
        "text_file": "",
    }

    for name, sender in SENDERS.items():
        resolver = getattr(sender, "resolve_config", None)
        if resolver:
            result = resolver(bot_cfg, toml_data)
            if result:
                cfg[name] = result

    return cfg


def get_text_source(cfg: Dict[str, Any]) -> Dict[str, str]:
    """获取文本来源配置。"""
    source = cfg.get("text_source", "argument")
    if source == "file":
        return {"source": "file", "path": cfg.get("text_file", "")}
    return {"source": "argument"}
