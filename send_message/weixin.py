"""微信 iLink Bot 消息发送模块。

使用 iLink Bot API 发送文本消息到微信用户。
"""

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

# ---------- 模块元数据 ----------

CHANNEL_NAME = "微信"
"""渠道显示名称。"""

REQUIRED_KEYS = {"account_id", "to_user_id"}
"""``config.weixin`` 中必须存在的字段。"""

# ---------- 微信常量（固定值，不可配置） ----------

WEIXIN_DEFAULTS = {
    "api_base": "https://ilinkai.weixin.qq.com",
    "channel_version": "2.2.0",
    "app_id": "bot",
    "client_version": 131584,
}

REQUEST_TIMEOUT = 15
WEIXIN_TOKEN_ENV = "WEIXIN_BOT_TOKEN"
WEIXIN_ACCOUNTS_DIR = Path.home() / ".reasonix" / "weixin" / "accounts"


class WeixinError(Exception):
    """微信 API 错误。"""


# ==============================================================
#  配置解析（满足 sender 模块接口规范）
# ==============================================================

def resolve_config(bot_cfg: Dict[str, Any], toml_data: Dict[str, Any]) -> Dict[str, Any]:
    """从 TOML 解析微信配置。"""
    data: Dict[str, Any] = {}
    weixin_toml = bot_cfg.get("weixin", {})
    if isinstance(weixin_toml, dict):
        data["enabled"] = True
        data["account_id"] = weixin_toml.get("account_id", "default")

        allowlist = bot_cfg.get("allowlist", {})
        wx_users = allowlist.get("weixin_users", []) if isinstance(allowlist, dict) else []
        data["to_user_id"] = wx_users[0] if wx_users else ""

        for key, val in WEIXIN_DEFAULTS.items():
            data.setdefault(key, val)
    return data


# ==============================================================
#  Token 获取
# ==============================================================

def _get_token(account_id: str) -> Optional[str]:
    """获取微信 Bot token。

    查找顺序：
    1. 环境变量 ``WEIXIN_BOT_TOKEN``
    2. ``~/.reasonix/weixin/accounts/{account_id}.json``
    3. ``~/.reasonix/weixin/accounts/default.json``

    Returns:
        token 或 None。
    """
    token = os.environ.get(WEIXIN_TOKEN_ENV)
    if token:
        return token

    if not WEIXIN_ACCOUNTS_DIR.exists():
        return None

    for fname in [f"{account_id}.json", "default.json"]:
        p = WEIXIN_ACCOUNTS_DIR / fname
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    token = data.get("token")
                    if token:
                        return token
            except (json.JSONDecodeError, OSError):
                continue

    return None


# ==============================================================
#  发送
# ==============================================================

def send(text: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """发送文本消息到微信。

    Args:
        text: 消息文本内容。
        cfg: 完整配置。

    Returns:
        {"ok": True, "status": 200, "body": "..."}
        或 {"ok": False, "code": "...", "msg": "错误描述"}
    """
    wc = cfg.get("weixin", {})
    if not wc.get("enabled", False):
        return {"ok": False, "code": "skipped", "msg": "微信发送已禁用"}

    token = _get_token(wc["account_id"])
    if not token:
        return {
            "ok": False,
            "code": "no_token",
            "msg": (
                f"未找到微信 Bot token。\n"
                f"请设置环境变量 {WEIXIN_TOKEN_ENV}，"
                f"或确保 ~/.reasonix/weixin/accounts/{wc['account_id']}.json 存在。"
            ),
        }

    client_id = f"reasonix-{int(time.time() * 1000)}"
    payload = json.dumps(
        {
            "base_info": {"channel_version": wc["channel_version"]},
            "msg": {
                "from_user_id": "",
                "to_user_id": wc["to_user_id"],
                "client_id": client_id,
                "message_type": 2,
                "message_state": 2,
                "item_list": [{"type": 1, "text_item": {"text": text}}],
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")

    url = f"{wc['api_base']}/ilink/bot/sendmessage"
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "AuthorizationType": "ilink_bot_token",
        "Authorization": f"Bearer {token}",
        "iLink-App-Id": wc["app_id"],
        "iLink-App-ClientVersion": str(wc["client_version"]),
    }

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            body = resp.read().decode("utf-8")
            return {"ok": resp.status == 200, "status": resp.status, "body": body[:500]}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"ok": False, "code": f"http_{e.code}", "msg": body[:500], "status": e.code}
    except urllib.error.URLError as e:
        return {"ok": False, "code": "network_error", "msg": str(e.reason)}
    except (OSError, ValueError) as e:
        return {"ok": False, "code": "request_error", "msg": str(e)}
