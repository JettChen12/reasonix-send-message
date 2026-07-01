"""QQ 官方 Bot API v2 消息发送模块。

使用 QQ 开放 API 发送文本消息到用户（C2C）或群聊。
参考 DeepSeek-Reasonix 的 ``internal/bot/qq/`` Go 实现。

API 文档: https://bot.q.qq.com/wiki/develop/api/
"""

import json
import os
import urllib.error
import urllib.request
import logging
from typing import Any, Dict, Optional

from send_message._retry import retry as _retry
from send_message.config import ConfigError, find_chat_id_from_connections

logger = logging.getLogger(__name__)

# ---------- 模块元数据 ----------

CHANNEL_NAME = "QQ"
"""渠道显示名称。"""

REQUIRED_KEYS = {"app_id", "chat_id"}
""":attr:`cfg[qq]` 中必须存在的字段。

.. note::
   chat_id 来自 ``[[bot.connections]]`` 中 ``provider = "qq"`` 的连接，
   而非 ``[bot.qq]``。Go 原生 ``QQBotConfig`` 无 ``chat_id`` 字段。
   目前 Go 桌面端的 ``DiagnoseBotConnection()`` 暂不支持 QQ 发送测试，
   但本模块保留完整的发送能力。
"""

# ---------- API 常量 ----------

QQ_TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
QQ_BASE_URL = "https://api.sgroup.qq.com"
QQ_SANDBOX_URL = "https://sandbox.api.sgroup.qq.com"
REQUEST_TIMEOUT = 15


class QQError(Exception):
    """QQ API 错误。"""


# ==============================================================
#  配置解析（满足 sender 模块接口规范）
# ==============================================================


def resolve_config(
    bot_cfg: Dict[str, Any], toml_data: Dict[str, Any]
) -> Dict[str, Any]:
    """从 TOML 解析 QQ 配置。

    读取 ``~/.reasonix/config.toml``::

        [bot.qq]
        app_id = "<QQ Bot App ID>"
        app_secret_env = "QQ_BOT_APP_SECRET"    # 可选，默认 QQ_BOT_APP_SECRET
        sandbox = false                           # 可选，沙箱模式

    chat_id 来源（与 Go 的 ``[[bot.connections]]`` 模式一致）:
    ``[[bot.connections]]`` → ``provider = "qq"`` → ``session_mappings[0].remote_id``

    注意: Go ``QQBotConfig`` 没有 ``chat_id`` 字段，也没有 ``chat_type``。
    ``chat_type`` 由连接中的 ``session_mappings[0].chat_type`` 确定。
    """
    data: Dict[str, Any] = {}
    qq_toml = bot_cfg.get("qq")
    if isinstance(qq_toml, dict):
        data["enabled"] = True
        data["app_id"] = qq_toml.get("app_id", "")
        data["app_secret_env"] = qq_toml.get("app_secret_env", "QQ_BOT_APP_SECRET")
        data["sandbox"] = bool(qq_toml.get("sandbox", False))

        # chat_id 和 chat_type 来自 connections
        data["chat_id"] = find_chat_id_from_connections(toml_data, "qq") or ""
        data["chat_type"] = _find_chat_type_from_connections(toml_data) or "c2c"
    return data


def _find_chat_type_from_connections(toml_data: Dict[str, Any]) -> Optional[str]:
    """从 ``[[bot.connections]]`` 中查找 QQ 连接的 ``session_mappings[0].chat_type``。"""
    try:
        connections = toml_data.get("bot", {}).get("connections", [])
    except AttributeError:
        return None
    for conn in connections:
        if not isinstance(conn, dict):
            continue
        conn_provider = conn.get("provider") or conn.get("type") or ""
        if conn_provider.lower() != "qq":
            continue
        mappings = conn.get("session_mappings", [])
        if mappings and isinstance(mappings[0], dict):
            chat_type = mappings[0].get("chat_type", "")
            if chat_type:
                return chat_type
    return None


# ==============================================================
#  内部工具
# ==============================================================


def _get_app_secret(cfg: Dict[str, Any]) -> str:
    """从环境变量获取 QQ App Secret。"""
    env_key = cfg.get("qq", {}).get("app_secret_env", "QQ_BOT_APP_SECRET")
    secret = os.environ.get(env_key)
    if not secret:
        # fallback — 与 Go 实现兼容
        secret = os.environ.get("QQ_SECRET", "")
    if not secret:
        raise ConfigError(
            f"环境变量 {env_key} 未设置或为空。\n"
            f"请将其设置为 QQ Bot App Secret，"
            f"或检查 Reasonix .env 文件中是否包含此变量。"
        )
    return secret


def _api_base_url(cfg: Dict[str, Any]) -> str:
    """根据 sandbox 标志返回对应的 API base URL。"""
    qq_cfg = cfg.get("qq", {})
    if qq_cfg.get("sandbox", False):
        return QQ_SANDBOX_URL
    return QQ_BASE_URL


# ==============================================================
#  HTTP 请求
# ==============================================================


def _request(
    url: str,
    data: Optional[bytes] = None,
    headers: Optional[Dict[str, str]] = None,
    method: str = "POST",
) -> Dict[str, Any]:
    """发送 HTTP 请求并解析 JSON 响应（自动重试）。"""

    def _do() -> Dict[str, Any]:
        req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise QQError(f"HTTP {e.code}: {body[:500]}") from e
        except urllib.error.URLError as e:
            raise QQError(f"网络错误: {e.reason}") from e
        except (json.JSONDecodeError, OSError, ValueError) as e:
            raise QQError(f"响应解析失败: {e}") from e

    return _retry(
        _do,
        label="QQ API 请求",
        retryable_exceptions=(QQError, OSError, urllib.error.URLError),
    )


# ==============================================================
#  Token 获取
# ==============================================================


def _get_access_token(app_id: str, app_secret: str) -> str:
    """调用 QQ Bot API 获取 access_token。"""
    payload = json.dumps(
        {"appId": app_id, "clientSecret": app_secret}, ensure_ascii=False
    ).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    result = _request(QQ_TOKEN_URL, data=payload, headers=headers)
    token = result.get("access_token")
    if not token:
        raise QQError(f"获取 access_token 失败: {result}")
    logger.info("QQ access_token 获取成功（app_id=%s）", app_id[:8])
    return token


# ==============================================================
#  发送
# ==============================================================


def send(text: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """发送文本消息到 QQ。

    Args:
        text: 消息文本内容。
        cfg: 完整配置（由 ``resolve_config()`` 聚合）。

    Returns:
        ``{"ok": True, "code": "0", "msg": "success", ...}``
        或 ``{"ok": False, "code": "...", "msg": "错误描述"}``
    """
    qq_cfg = cfg.get("qq", {})
    if not qq_cfg.get("enabled", False):
        return {"ok": False, "code": "skipped", "msg": "QQ 发送已禁用"}

    # 获取 secret
    try:
        app_secret = _get_app_secret(cfg)
    except ConfigError as e:
        return {"ok": False, "code": "config_error", "msg": str(e)}

    # 获取 token
    try:
        token = _get_access_token(qq_cfg["app_id"], app_secret)
    except QQError as e:
        return {"ok": False, "code": "token_error", "msg": str(e)}

    # 发送消息
    return _do_send(text, qq_cfg, token)


def _do_send(text: str, qq_cfg: Dict[str, Any], token: str) -> Dict[str, Any]:
    """执行 QQ 消息发送。"""
    chat_id = qq_cfg["chat_id"]
    chat_type = qq_cfg.get("chat_type", "c2c")

    if chat_type == "group":
        url = f"{_api_base_url({'qq': qq_cfg})}/v2/groups/{chat_id}/messages"
    else:
        url = f"{_api_base_url({'qq': qq_cfg})}/v2/users/{chat_id}/messages"

    payload = json.dumps(
        {"content": text, "msg_type": 0},
        ensure_ascii=False,
    ).encode("utf-8")

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Authorization": f"QQBot {token}",
        "X-Union-Appid": qq_cfg["app_id"],
    }

    try:
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            body = resp.read().decode("utf-8")
            result = json.loads(body)
            message_id = result.get("id", "")
            logger.info("QQ 消息发送成功（chat_type=%s, msg_id=%s）", chat_type, message_id)
            return {
                "ok": resp.status == 200,
                "code": "0" if resp.status == 200 else str(resp.status),
                "msg": "发送成功",
                "message_id": message_id,
                "status": resp.status,
            }
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.error("QQ API HTTP %d: %s", e.code, body[:200])
        return {"ok": False, "code": f"http_{e.code}", "msg": body[:500], "status": e.code}
    except urllib.error.URLError as e:
        logger.error("QQ 网络错误: %s", e.reason)
        return {"ok": False, "code": "network_error", "msg": str(e.reason)}
    except (OSError, ValueError, json.JSONDecodeError) as e:
        logger.error("QQ 发送异常: %s", e)
        return {"ok": False, "code": "request_error", "msg": str(e)}
