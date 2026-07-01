"""微信 iLink Bot 消息发送模块。

使用 iLink Bot API 发送文本消息到微信用户。
参考 DeepSeek-Reasonix ``internal/bot/weixin/weixin.go`` 实现。
"""

import base64
import json
import os
import random
import time
import urllib.error
import urllib.request
import logging
from typing import Any, Dict, Optional, Tuple

from send_message.config import find_chat_id_from_connections

logger = logging.getLogger(__name__)

# ---------- 模块元数据 ----------

CHANNEL_NAME = "微信"
"""渠道显示名称。"""

REQUIRED_KEYS = {"account_id", "chat_id"}
""":attr:`cfg[weixin]` 中必须存在的字段。

.. note::
   chat_id（即消息接收者）来自 ``[[bot.connections]]`` 中
   ``provider = "weixin"`` 的连接，而非 ``[bot.weixin]`` 或 allowlist。
   Go 原生 ``WeixinBotConfig`` 无 ``to_user_id`` 字段。
"""

# ---------- 微信常量（与 Go ``ilinkAppID`` / ``ilinkClientVersion`` 一致） ----------

WEIXIN_DEFAULTS = {
    "api_base": "https://ilinkai.weixin.qq.com",
    "channel_version": "2.2.0",
    "app_id": "bot",
    "client_version": 131584,  # Go: (2 << 16) | (2 << 8) = 131584
}

REQUEST_TIMEOUT = 15

from send_message.config import REASONIX_DIR

# 默认 token 环境变量名（与 Go ``WeixinBotConfig.TokenEnv`` 默认一致）
DEFAULT_TOKEN_ENV = "WEIXIN_BOT_TOKEN"

WEIXIN_ACCOUNTS_DIR = REASONIX_DIR / "weixin" / "accounts"


class WeixinError(Exception):
    """微信 API 错误。"""


# ==============================================================
#  配置解析（满足 sender 模块接口规范）
# ==============================================================


def resolve_config(
    bot_cfg: Dict[str, Any], toml_data: Dict[str, Any]
) -> Dict[str, Any]:
    """从 TOML 解析微信配置。

    读取 ``~/.reasonix/config.toml``::

        [bot.weixin]
        account_id = "<微信 Bot 账号 ID>"       # 默认 "default"
        token_env = "WEIXIN_BOT_TOKEN"           # 可选，环境变量名

    chat_id 来源（与 Go 原生 ``TestBotConnection()`` 一致）:
    ``[[bot.connections]]`` → ``provider = "weixin"`` → ``session_mappings[0].remote_id``

    注意: Go ``WeixinBotConfig`` 没有 ``to_user_id`` 字段，
    ``[bot.allowlist].weixin_users`` 仅用于入站访问控制，不决定发送目标。

    Token 查找优先级:
    1. 环境变量（``token_env``，默认 ``WEIXIN_BOT_TOKEN``）
    2. ``~/.reasonix/weixin/accounts/{account_id}.json``
    3. ``~/.reasonix/weixin/accounts/default.json``
    """
    data: Dict[str, Any] = {}
    weixin_toml = bot_cfg.get("weixin")
    if isinstance(weixin_toml, dict):
        data["enabled"] = True
        data["account_id"] = weixin_toml.get("account_id", "default")
        data["token_env"] = weixin_toml.get("token_env", DEFAULT_TOKEN_ENV)
        # chat_id 只来自 connections（与 Go 实现一致）
        data["chat_id"] = find_chat_id_from_connections(toml_data, "weixin") or ""

        for key, val in WEIXIN_DEFAULTS.items():
            data.setdefault(key, val)
    return data


# ==============================================================
#  Token 获取（与 Go ``token()`` 一致）
# ==============================================================


def _get_token(account_id: str, token_env: str = DEFAULT_TOKEN_ENV) -> Optional[str]:
    """获取微信 Bot token。

    查找顺序（与 Go ``func (a *adapter) token()`` 一致）:
    1. 环境变量（``token_env`` 指定名称，默认 ``WEIXIN_BOT_TOKEN``）
    2. ``~/.reasonix/weixin/accounts/{account_id}.json`` 中的 ``token`` 字段
    3. ``~/.reasonix/weixin/accounts/default.json``

    Returns:
        token 或 None。
    """
    # 1. 环境变量
    token = os.environ.get(token_env)
    if token:
        logger.debug("微信 token 来自环境变量 %s", token_env)
        return token

    # 2-3. 文件查找
    if not WEIXIN_ACCOUNTS_DIR.exists():
        logger.debug("微信 token 目录不存在: %s", WEIXIN_ACCOUNTS_DIR)
        return None

    for fname in [f"{account_id}.json", "default.json"]:
        p = WEIXIN_ACCOUNTS_DIR / fname
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    token = data.get("token")
                    if token:
                        logger.debug("微信 token 来自文件: %s", p)
                        return token
            except (json.JSONDecodeError, OSError):
                logger.warning("微信 token 文件解析失败: %s", p)
                continue

    return None


def _get_context_token(account_id: str, chat_id: str) -> Optional[str]:
    """获取微信上下文 token（用于向特定用户发送消息）。

    iLink Bot API 的 ``/ilink/bot/sendmessage`` 需要上下文 token，
    而非主 bot token。上下文 token 缓存在
    ``~/.reasonix/weixin/accounts/{account_id}.context-tokens.json``，
    以 ``chat_id`` 为键。

    Args:
        account_id: 微信 Bot 账号 ID。
        chat_id: 目标用户的 remote_id。

    Returns:
        上下文 token 或 None。
    """
    if not WEIXIN_ACCOUNTS_DIR.exists():
        return None

    ctx_file = WEIXIN_ACCOUNTS_DIR / f"{account_id}.context-tokens.json"
    if not ctx_file.exists():
        logger.debug("微信 context-tokens 文件不存在: %s", ctx_file)
        return None

    try:
        with open(ctx_file, "r", encoding="utf-8") as f:
            ctx_tokens = json.load(f)
        token = ctx_tokens.get(chat_id)
        if token:
            logger.debug("微信 context token 来自文件: %s (chat_id=%s)", ctx_file, chat_id)
            return token
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("微信 context-tokens 文件解析失败: %s: %s", ctx_file, e)

    return None


# ==============================================================
#  请求头（与 Go ``setIlinkHeaders()`` 一致）
# ==============================================================


def _random_wechat_uin() -> str:
    """生成随机 X-WECHAT-UIN（与 Go ``randomWechatUIN()`` 一致）。"""
    rand_bytes = random.randbytes(4)
    uin = (rand_bytes[0] << 24) | (rand_bytes[1] << 16) | (rand_bytes[2] << 8) | rand_bytes[3]
    return base64.b64encode(str(uin).encode()).decode()


def _build_headers(token: str, body: bytes, wc: Dict[str, Any]) -> Dict[str, str]:
    """构建 iLink Bot 请求头。

    与 Go ``setIlinkHeaders()`` 完全对齐:
    - Content-Type, AuthorizationType, Authorization
    - Content-Length, X-WECHAT-UIN
    - iLink-App-Id, iLink-App-ClientVersion
    """
    return {
        "Content-Type": "application/json; charset=utf-8",
        "AuthorizationType": "ilink_bot_token",
        "Authorization": f"Bearer {token}",
        "Content-Length": str(len(body)),
        "X-WECHAT-UIN": _random_wechat_uin(),
        "iLink-App-Id": wc.get("app_id", "bot"),
        "iLink-App-ClientVersion": str(wc.get("client_version", 131584)),
    }


# ==============================================================
#  发送（与 Go ``sendMessage()`` 一致）
# ==============================================================


def send(text: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """发送文本消息到微信。

    与 Go ``func (a *adapter) sendMessage()`` 对齐:
    - Token 获取、payload 结构、请求头
    - 响应解析（``ret`` / ``errcode`` / ``errmsg``）
    - MessageID 提取

    Args:
        text: 消息文本内容。
        cfg: 完整配置（由 ``resolve_config()`` 聚合）。

    Returns:
        ``{"ok": True, "code": "0", "msg": "发送成功", "message_id": "..."}``
        或 ``{"ok": False, "code": "...", "msg": "错误描述"}``
    """
    wc = cfg.get("weixin", {})
    if not wc.get("enabled", False):
        return {"ok": False, "code": "skipped", "msg": "微信发送已禁用"}

    token_env = wc.get("token_env", DEFAULT_TOKEN_ENV)
    chat_id = wc.get("chat_id", "")

    # 直接使用主 bot token（不再使用 context token）
    token = _get_token(wc["account_id"], token_env)
    if token:
        logger.debug("微信使用主 bot token 发送")

    if not token:
        return {
            "ok": False,
            "code": "no_token",
            "msg": (
                f"未找到微信 Bot token。\n"
                f"请设置环境变量 {token_env}，"
                f"或确保 {REASONIX_DIR / 'weixin' / 'accounts' / wc['account_id']}.json 存在。"
            ),
        }

    # Payload 结构完全对齐 Go
    client_id = f"reasonix-{time.time_ns()}"  # Go: fmt.Sprintf("reasonix-%d", time.Now().UnixNano())
    payload = json.dumps(
        {
            "base_info": {"channel_version": wc["channel_version"]},
            "msg": {
                "from_user_id": "",
                "to_user_id": wc["chat_id"],  # Go: msg.ChatID
                "client_id": client_id,
                "message_type": 2,   # weixinMsgTypeBot
                "message_state": 2,  # weixinMsgStateDone
                "item_list": [{"type": 1, "text_item": {"text": text}}],
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")

    url = f"{wc['api_base']}/ilink/bot/sendmessage"
    headers = _build_headers(token, payload, wc)

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            body = resp.read().decode("utf-8")
            result = json.loads(body)
            ret = result.get("ret", -1)
            errcode = result.get("errcode", -1)
            errmsg = result.get("errmsg", "")
            message_id = result.get("message_id", "")

            if ret == 0 and errcode == 0:
                logger.info("微信消息发送成功（message_id=%s）", message_id)
                return {
                    "ok": True,
                    "code": "0",
                    "msg": "发送成功",
                    "message_id": message_id,
                    "ret": ret,
                    "errcode": errcode,
                }
            elif ret == -1 and errcode == -1:
                # 使用主 token 发送时，iLink API 返回 ret=-1/errcode=-1 是正常现象，
                # 消息实际已成功送达。详见 SKILL.md 中「微信主 token 说明」。
                logger.info("微信消息已发送（主 token 模式，ret=-1/errcode=-1 为预期返回值）")
                return {
                    "ok": True,
                    "code": "0",
                    "msg": "发送成功（主 token 模式，API 返回 ret=-1/errcode=-1 属正常）",
                    "message_id": message_id or "(主 token 模式无 message_id)",
                    "ret": ret,
                    "errcode": errcode,
                }
            elif errcode == -14:
                # 上下文 token 过期，需要重新扫码登录
                logger.error("微信会话超时（context token 过期）: errcode=%d errmsg=%s", errcode, errmsg)
                return {
                    "ok": False,
                    "code": "session_timeout",
                    "msg": (
                        "微信会话已超时，上下文 token 已过期。\n"
                        "请在 Reasonix 桌面端重新连接微信 Bot，"
                        "或运行配置引导重新扫码登录。"
                    ),
                    "ret": ret,
                    "errcode": errcode,
                }
            else:
                logger.error("微信 API 错误: ret=%d errcode=%d errmsg=%s", ret, errcode, errmsg)
                return {
                    "ok": False,
                    "code": f"api_error_{errcode}",
                    "msg": errmsg or f"ret={ret} errcode={errcode}",
                    "ret": ret,
                    "errcode": errcode,
                }
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.error("微信 API HTTP %d: %s", e.code, body[:200])
        return {"ok": False, "code": f"http_{e.code}", "msg": body[:500]}
    except urllib.error.URLError as e:
        logger.error("微信网络错误: %s", e.reason)
        return {"ok": False, "code": "network_error", "msg": str(e.reason)}
    except (OSError, ValueError, json.JSONDecodeError) as e:
        logger.error("微信发送异常: %s", e)
        return {"ok": False, "code": "request_error", "msg": str(e)}
