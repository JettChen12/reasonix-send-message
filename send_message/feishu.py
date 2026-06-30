"""飞书消息发送模块。

使用飞书开放 API 发送文本消息到指定群聊。
"""

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from send_message.config import ConfigError

# ---------- 模块元数据 ----------

CHANNEL_NAME = "飞书"
"""渠道显示名称。"""

REQUIRED_KEYS = {"app_id", "chat_id"}
"""``config.feishu`` 中必须存在的字段。"""

# ---------- API 常量 ----------

AUTH_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
MSG_URL = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
REQUEST_TIMEOUT = 15


class FeishuError(Exception):
    """飞书 API 错误。"""


# ==============================================================
#  配置解析（满足 sender 模块接口规范）
# ==============================================================

def resolve_config(bot_cfg: Dict[str, Any], toml_data: Dict[str, Any]) -> Dict[str, Any]:
    """从 TOML 解析飞书配置。"""
    data: Dict[str, Any] = {}
    feishu_toml = bot_cfg.get("feishu", {})
    if isinstance(feishu_toml, dict):
        data["enabled"] = True
        data["app_id"] = feishu_toml.get("app_id", "")
        data["app_secret_env"] = feishu_toml.get(
            "app_secret_env", "FEISHU_BOT_APP_SECRET"
        )
        chat_id = feishu_toml.get("chat_id") or _find_chat_id(toml_data)
        data["chat_id"] = chat_id or ""
    return data


def _find_chat_id(toml_data: Dict[str, Any]) -> Optional[str]:
    """从 ``[[bot.connections]]`` 中查找飞书连接的 session_mappings[0].remote_id。"""
    try:
        connections: List[Dict[str, Any]] = toml_data.get("bot", {}).get("connections", [])
    except AttributeError:
        return None
    for conn in connections:
        if not isinstance(conn, dict):
            continue
        conn_type = conn.get("type", "")
        if "feishu" in conn_type.lower():
            mappings = conn.get("session_mappings", [])
            if mappings and isinstance(mappings[0], dict):
                return mappings[0].get("remote_id")
    return None


# ==============================================================
#  HTTP 请求
# ==============================================================

def _request(
    url: str,
    data: Optional[bytes] = None,
    headers: Optional[Dict[str, str]] = None,
    method: str = "POST",
) -> Dict[str, Any]:
    """发送 HTTP 请求并解析 JSON 响应。"""
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise FeishuError(f"HTTP {e.code}: {body[:500]}") from e
    except urllib.error.URLError as e:
        raise FeishuError(f"网络错误: {e.reason}") from e
    except (json.JSONDecodeError, OSError, ValueError) as e:
        raise FeishuError(f"响应解析失败: {e}") from e


def _get_tenant_token(app_id: str, app_secret: str) -> str:
    """获取飞书 tenant_access_token。"""
    payload = json.dumps(
        {"app_id": app_id, "app_secret": app_secret},
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    result = _request(AUTH_URL, data=payload, headers=headers)
    token = result.get("tenant_access_token")
    if not token:
        raise FeishuError(
            f"获取 tenant_access_token 失败: code={result.get('code')} "
            f"msg={result.get('msg')}"
        )
    return token


def _get_app_secret(cfg: Dict[str, Any]) -> str:
    """从环境变量获取飞书 App Secret。"""
    env_key = cfg.get("feishu", {}).get("app_secret_env", "FEISHU_BOT_APP_SECRET")
    secret = os.environ.get(env_key)
    if not secret:
        raise ConfigError(
            f"环境变量 {env_key} 未设置或为空。\n"
            f"请将其设置为飞书 App Secret，"
            f"或检查 ~/.reasonix/.env 中是否包含此变量。"
        )
    return secret


# ==============================================================
#  发送
# ==============================================================

def send(text: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """发送文本消息到飞书。

    Args:
        text: 消息文本内容。
        cfg: 完整配置。

    Returns:
        {"ok": True, "code": "0", "msg": "success"}
        或 {"ok": False, "code": "...", "msg": "错误描述"}
    """
    feishu_cfg = cfg.get("feishu", {})
    if not feishu_cfg.get("enabled", False):
        return {"ok": False, "code": "skipped", "msg": "飞书发送已禁用"}

    try:
        app_secret = _get_app_secret(cfg)
    except ConfigError as e:
        return {"ok": False, "code": "config_error", "msg": str(e)}

    try:
        token = _get_tenant_token(feishu_cfg["app_id"], app_secret)

        payload = json.dumps(
            {
                "receive_id": feishu_cfg["chat_id"],
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        }
        result = _request(MSG_URL, data=payload, headers=headers)

        code = result.get("code")
        if code == 0:
            return {"ok": True, "code": "0", "msg": "发送成功"}
        else:
            return {
                "ok": False,
                "code": str(code),
                "msg": result.get("msg", "未知错误"),
            }

    except FeishuError as e:
        return {"ok": False, "code": "api_error", "msg": str(e)}
    except Exception as e:
        return {"ok": False, "code": "unexpected", "msg": f"未预期错误: {e}"}
