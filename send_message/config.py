"""配置加载——基础设施，不包含任何平台特有逻辑。

提供 TOML 解析、.env 加载等公共服务。
``resolve_config()`` 通过 ``SENDERS`` 注册表发现各平台的配置解析器并调用之。
"""

import os
import re
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

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
            data = tomllib.load(f)
        logger.info("TOML 配置加载成功: %s", path)
        return data
    except Exception as e:
        raise ConfigSourceError(f"解析 TOML 文件失败 ({path}): {e}")


# ==============================================================
#  .env 解析器
# ==============================================================


def read_dotenv(path: Path) -> Dict[str, str]:
    """解析 .env 文件为键值对（简单实现，无外部依赖）。"""
    if not path.exists():
        logger.debug(".env 文件不存在: %s", path)
        return {}
    env: Dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            line = line.removeprefix("export ")
            m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(.*?)\s*$", line)
            if m:
                key = m.group(1)
                val = m.group(2).strip()
                if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                    val = val[1:-1]
                env[key] = val
    logger.info(".env 文件加载完毕: %s（%d 个变量）", path, len(env))
    return env


def load_dotenv_into_environ() -> None:
    """将 ``~/.reasonix/.env`` 中的变量加载到 ``os.environ``（不覆盖已存在的）。"""
    env_vars = read_dotenv(DOTENV_FILE)
    loaded = 0
    skipped = 0
    for key, val in env_vars.items():
        if key not in os.environ:
            os.environ[key] = val
            loaded += 1
        else:
            skipped += 1
    if loaded:
        logger.info("已加载 %d 个环境变量（%d 个已存在，跳过）", loaded, skipped)


# ==============================================================
#  连接查找（Go 源码 `BotConnectionConfig` 的 TOML 字段为 ``provider``）
# ==============================================================


def find_chat_id_from_connections(
    toml_data: Dict[str, Any], provider_name: str
) -> Optional[str]:
    """从 ``[[bot.connections]]`` 中查找指定平台的首个 ``session_mappings[0].remote_id``。

    根据 DeepSeek-Reasonix Go 源码 ``BotConnectionConfig`` 结构:
    - 平台身份字段是 ``provider``（``toml:"provider"``）
    - chat_id 来自首个 enabled connection 的 ``session_mappings[0].remote_id``

    与 Go 桌面端的 ``DiagnoseBotConnection()`` 查找逻辑一致:
    ``target = firstSessionRemoteID(conn.SessionMappings)``

    Args:
        toml_data: 完整 TOML 配置字典。
        provider_name: 平台标识（如 ``"feishu"``, ``"weixin"``, ``"qq"``）。

    Returns:
        remote_id 或 None。
    """
    try:
        connections: List[Dict[str, Any]] = (
            toml_data.get("bot", {}).get("connections", [])
        )
    except AttributeError:
        return None

    for conn in connections:
        if not isinstance(conn, dict):
            continue
        # Go 源码字段为 ``provider``，兼容旧版 ``type``
        conn_provider = conn.get("provider") or conn.get("type") or ""
        if conn_provider.lower() != provider_name.lower():
            continue
        if not conn.get("enabled", True):
            continue
        mappings = conn.get("session_mappings", [])
        if mappings and isinstance(mappings[0], dict):
            remote_id = mappings[0].get("remote_id")
            if remote_id:
                return remote_id
    return None


# ==============================================================
#  配置验证
# ==============================================================


def _validate_common_cfg(cfg: Dict[str, Any]) -> None:
    """检查各平台必需配置项是否存在。"""
    from send_message import SENDERS  # 延迟 import 避免循环

    for name, sender in SENDERS.items():
        platform_cfg = cfg.get(name, {})
        if not platform_cfg.get("enabled", False):
            continue
        missing = [
            k for k in getattr(sender, "REQUIRED_KEYS", set()) if not platform_cfg.get(k)
        ]
        if missing:
            logger.warning(
                "%s 缺少必填配置项: %s",
                getattr(sender, "CHANNEL_NAME", name),
                ", ".join(missing),
            )


# ==============================================================
#  公开 API
# ==============================================================


def resolve_config() -> Dict[str, Any]:
    """从 Reasonix 权威数据源解析完整配置。

    遍历 ``SENDERS`` 注册表，调用每个 sender module 的 ``resolve_config()``
    方法，将返回的配置按平台名聚合。

    返回结构::

        {
            "text_source": "argument",
            "text_file": "",
            "feishu": {"enabled": bool, "app_id": str, "chat_id": str, ...},
            "weixin": {"enabled": bool, "account_id": str, "chat_id": str, ...},
            "qq":     {"enabled": bool, "app_id": str, "chat_id": str, ...},
        }

    chat_id 来自 ``[[bot.connections]]``，而非各平台的 per-platform config。
    这与 Go 原生的 ``FeishuBotConfig``/``QQBotConfig``/``WeixinBotConfig``
    均无 ``chat_id``/``to_user_id`` 字段的事实一致。

    Raises:
        ConfigError: 当必填数据源缺失时。
    """
    from send_message import SENDERS  # 延迟 import 避免循环依赖

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
            try:
                result = resolver(bot_cfg, toml_data)
                if result:
                    cfg[name] = result
                    if result.get("enabled", False):
                        logger.info(
                            "%s 配置已加载",
                            getattr(sender, "CHANNEL_NAME", name),
                        )
            except Exception as e:
                logger.error(
                    "加载 %s 配置失败: %s",
                    getattr(sender, "CHANNEL_NAME", name),
                    e,
                )
                cfg[name] = {"enabled": False, "error": str(e)}

    _validate_common_cfg(cfg)
    return cfg


def get_text_source(cfg: Dict[str, Any]) -> Dict[str, str]:
    """获取文本来源配置。"""
    source = cfg.get("text_source", "argument")
    if source == "file":
        return {"source": "file", "path": cfg.get("text_file", "")}
    return {"source": "argument"}
