"""Bot 自助配置模块。

当配置文件不存在或缺少 bot 配置时，
通过 OAuth 设备码流程让用户扫码授权，自动保存配置。

参考 DeepSeek-Reasonix Go 源码：
  - desktop/bot_connection_app.go → postFeishuInstallForm / pollFeishuConnectionInstall
  - internal/bot/weixin/weixin_login.go → StartLogin / PollLogin
"""

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from send_message.config import REASONIX_DIR, CONFIG_TOML, DOTENV_FILE

logger = logging.getLogger(__name__)

WEIXIN_ACCOUNTS_DIR = REASONIX_DIR / "weixin" / "accounts"

# ==============================================================
#  飞书 OAuth 设备码流程
#  参考 Go: postFeishuInstallForm() + pollFeishuConnectionInstall()
# ==============================================================

FEISHU_ACCOUNTS = {
    "feishu": "https://accounts.feishu.cn",
    "lark": "https://accounts.larksuite.com",
}

FEISHU_REGISTRATION_URL = "/oauth/v1/app/registration"


def feishu_begin_install(domain: str = "feishu") -> Dict[str, Any]:
    """发起飞书 OAuth 设备码授权。

    对应 Go: postFeishuInstallForm() + bot_connection_app.go:439-453

    Returns:
        {"device_code": str, "verification_uri_complete": str,
         "user_code": str, "interval": int, "expires_in": int}
    """
    base = FEISHU_ACCOUNTS.get(domain, FEISHU_ACCOUNTS["feishu"])
    data = urllib.parse.urlencode({
        "action": "begin",
        "archetype": "PersonalAgent",
        "auth_method": "client_secret",
        "request_user_info": "open_id",
    }).encode()

    req = urllib.request.Request(
        f"{base}{FEISHU_REGISTRATION_URL}",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        raise RuntimeError(f"飞书授权请求失败: {e}") from e

    errors = result.get("error") or result.get("error_description")
    if errors:
        raise RuntimeError(f"飞书授权错误: {errors}")

    return {
        "device_code": result["device_code"],
        "verification_uri_complete": result["verification_uri_complete"],
        "user_code": result.get("user_code", ""),
        "interval": int(result.get("interval", 5)),
        "expires_in": int(result.get("expires_in", result.get("expire_in", 300))),
    }


def feishu_poll_install(device_code: str, domain: str = "feishu") -> Optional[Dict[str, Any]]:
    """轮询等待用户扫码授权。

    对应 Go: pollFeishuConnectionInstall()

    Returns:
        None（等待中）或 {"app_id": str, "app_secret": str, "user_id": str, "domain": str}
    """
    base = FEISHU_ACCOUNTS.get(domain, FEISHU_ACCOUNTS["feishu"])
    data = urllib.parse.urlencode({
        "action": "poll",
        "device_code": device_code,
    }).encode()

    req = urllib.request.Request(
        f"{base}{FEISHU_REGISTRATION_URL}",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        raise RuntimeError(f"飞书轮询请求失败: {e}") from e

    # 检查错误
    err = result.get("error", "")
    if err == "authorization_pending" or err == "slow_down":
        return None  # 还在等待
    if err:
        raise RuntimeError(f"飞书授权错误: {err}: {result.get('error_description', '')}")

    # 检查是否 Lark
    actual_domain = domain
    user_info = result.get("user_info", {})
    if isinstance(user_info, dict):
        tenant_brand = user_info.get("tenant_brand", "")
        if tenant_brand and tenant_brand.lower() == "lark":
            actual_domain = "lark"
        # 如果之前用的是 feishu 但 Lark 返回了凭据，需用 Lark 域重试
        if actual_domain != domain and not result.get("client_id"):
            return None  # 需要切换域名重新轮询

    app_id = result.get("client_id")
    app_secret = result.get("client_secret")
    if not app_id or not app_secret:
        return None  # 尚未完成

    user_id = ""
    if isinstance(user_info, dict):
        user_id = user_info.get("open_id", user_info.get("union_id", ""))

    return {
        "app_id": app_id,
        "app_secret": app_secret,
        "user_id": user_id,
        "domain": actual_domain,
    }


def feishu_full_setup(domain: str = "feishu") -> Dict[str, Any]:
    """完整的飞书扫码配置流程（发起→等待→保存）。

    Args:
        domain: "feishu" 或 "lark"

    Returns:
        {"app_id": str, "domain": str}
    """
    print(f"\n🔗 正在获取飞书{'/Lark' if domain == 'lark' else ''}授权二维码...")

    begin = feishu_begin_install(domain)
    qr_url = begin["verification_uri_complete"]
    print(f"📱 请用飞书扫码登录（或在浏览器打开）:")
    print(f"   {qr_url}")
    print()

    # 轮询
    interval = max(begin["interval"], 3)
    expires = begin["expires_in"]
    deadline = time.time() + expires
    poll_domain = domain

    while time.time() < deadline:
        print(f"⏳ 等待授权中（每 {interval}s 检查一次，剩余 {int(deadline - time.time())}s）...")
        time.sleep(interval)

        result = feishu_poll_install(begin["device_code"], poll_domain)

        if result is None:
            continue

        # 如果检测到是 Lark 但之前用 feishu 域名，切换后重试
        if result.get("domain") and result["domain"] != poll_domain:
            if poll_domain == "feishu" and result["domain"] == "lark":
                print("🔁 检测到 Lark 租户，切换授权域名...")
                poll_domain = "lark"
                # 用 lark 域名重新 poll 一次（设备码不变）
                continue

        # 授权成功，保存配置
        return _save_feishu_config(result)

    raise TimeoutError("飞书授权超时，请重新尝试。")


def _save_feishu_config(result: Dict[str, Any]) -> Dict[str, Any]:
    """保存飞书配置到 ~/.reasonix/。

    对应 Go: pollFeishuConnectionInstall() 中的 upsertBotConnection + upsertDotEnv
    """
    domain = result.get("domain", "feishu")
    secret_env = "LARK_BOT_APP_SECRET" if domain == "lark" else "FEISHU_BOT_APP_SECRET"

    # 1. 保存 secret 到 .env
    _ensure_reasonix_dir()
    env_vars = _load_dotenv()
    env_vars[secret_env] = result["app_secret"]
    _save_dotenv(env_vars)

    # 2. 也设置到当前进程环境变量
    os.environ[secret_env] = result["app_secret"]

    # 3. 更新 config.toml
    config = _load_toml_safe()
    bot = config.setdefault("bot", {})

    bot.setdefault("feishu", {})
    bot["feishu"]["enabled"] = True
    bot["feishu"]["app_id"] = result["app_id"]
    bot["feishu"]["app_secret_env"] = secret_env
    bot["feishu"]["mode"] = "websocket"
    bot["feishu"]["require_mention"] = True
    if domain == "lark":
        bot["feishu"]["domain"] = "lark"

    bot.setdefault("allowlist", {})
    if result.get("user_id"):
        allowlist = bot["allowlist"]
        feishu_users = allowlist.setdefault("feishu_users", [])
        if result["user_id"] not in feishu_users:
            feishu_users.append(result["user_id"])

    _save_toml(config)

    print(f"✅ 飞书{'/Lark' if domain == 'lark' else ''}配置已保存到 {CONFIG_TOML}")
    return {"app_id": result["app_id"], "domain": domain}


# ==============================================================
#  微信扫码配置（使用 iLink Bot 登录协议）
#  参考 Go: internal/bot/weixin/weixin_login.go
# ==============================================================

# 微信 iLink 登录 API 地址
WEIXIN_LOGIN_API = "https://ilinkai.weixin.qq.com"
WEIXIN_LOGIN_PATH = "/ilink/bot/get_bot_qrcode"
WEIXIN_POLL_PATH = "/ilink/bot/get_qrcode_status"


def weixin_start_login() -> Dict[str, str]:
    """发起微信 iLink Bot 扫码登录。

    对应 Go: weixin.StartLogin()

    Returns:
        {"qrcode_url": str, "qrcode": str, "session_id": str}
    """
    # 模拟 Go 的 getBotQR
    req = urllib.request.Request(
        f"{WEIXIN_LOGIN_API}{WEIXIN_LOGIN_PATH}",
        headers={
            "iLink-App-Id": "bot",
            "iLink-App-ClientVersion": "131584",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        raise RuntimeError(f"微信登录请求失败: {e}") from e

    # Go 源码返回 {"qrcode": "...", "qrcode_url": "...", "session_id": "..."}
    return {
        "qrcode_url": result.get("qrcode_url", result.get("qrcode", "")),
        "qrcode": result.get("qrcode", ""),
        "session_id": result.get("session_id", ""),
    }


def weixin_poll_login(session_id: str) -> Optional[Dict[str, Any]]:
    """轮询等待微信扫码结果。

    对应 Go: weixin.PollLogin()

    Returns:
        None（等待中）或 {"account_id": str, "token": str, "user_id": str, "base_url": str}
    """
    req = urllib.request.Request(
        f"{WEIXIN_LOGIN_API}{WEIXIN_POLL_PATH}/{session_id}",
        headers={
            "iLink-App-Id": "bot",
            "iLink-App-ClientVersion": "131584",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        raise RuntimeError(f"微信轮询请求失败: {e}") from e

    status = result.get("status", "")

    if status in ("waiting", "scaned"):
        return None  # 还在等待

    if status == "confirmed" or status == "done":
        return {
            "account_id": result.get("account_id", "default"),
            "token": result.get("token", ""),
            "user_id": result.get("user_id", ""),
            "base_url": result.get("base_url", WEIXIN_LOGIN_API),
        }

    # Go 源码可能还有 scaned_but_redirect 等状态
    if status == "scaned_but_redirect":
        return None  # 需要切换节点

    raise RuntimeError(f"微信登录异常状态: {status}")


def weixin_full_setup() -> Dict[str, Any]:
    """完整的微信扫码配置流程。"""
    print("\n🔗 正在获取微信授权二维码...")

    session = weixin_start_login()
    qr_url = session.get("qrcode_url") or session.get("qrcode", "")
    if qr_url:
        print(f"📱 请用微信扫码登录:")
        print(f"   {qr_url}")
    print()

    # 轮询
    deadline = time.time() + 120  # 2 分钟超时
    while time.time() < deadline:
        print(f"⏳ 等待微信扫码中（剩余 {int(deadline - time.time())}s）...")
        time.sleep(3)

        result = weixin_poll_login(session["session_id"])
        if result is None:
            continue

        return _save_weixin_config(result)

    raise TimeoutError("微信授权超时，请重新尝试。")


def _save_weixin_config(result: Dict[str, Any]) -> Dict[str, Any]:
    """保存微信配置到 ~/.reasonix/。

    对应 Go: upsertBotConnection() + 写入 weixin/accounts/
    """
    account_id = result.get("account_id", "default")
    _ensure_reasonix_dir()

    # 1. 保存 token 到 weixin/accounts/{account_id}.json
    WEIXIN_ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    account_file = WEIXIN_ACCOUNTS_DIR / f"{account_id}.json"
    with open(account_file, "w", encoding="utf-8") as f:
        json.dump({"token": result["token"], "account_id": account_id,
                     "base_url": result.get("base_url", WEIXIN_LOGIN_API),
                     "user_id": result.get("user_id", "")}, f, ensure_ascii=False)
    print(f"✅ 微信 token 已保存到 {account_file}")

    # 2. 更新 config.toml
    config = _load_toml_safe()
    bot = config.setdefault("bot", {})

    bot.setdefault("weixin", {})
    bot["weixin"]["enabled"] = True
    bot["weixin"]["account_id"] = account_id
    bot["weixin"]["token_env"] = "WEIXIN_BOT_TOKEN"

    if result.get("base_url"):
        bot["weixin"]["api_base"] = result["base_url"]

    bot.setdefault("allowlist", {})
    if result.get("user_id"):
        allowlist = bot["allowlist"]
        wx_users = allowlist.setdefault("weixin_users", [])
        if result["user_id"] not in wx_users:
            wx_users.append(result["user_id"])

    _save_toml(config)

    print(f"✅ 微信配置已保存到 {CONFIG_TOML}")
    return {"account_id": account_id}


# ==============================================================
#  配置读写工具
# ==============================================================

def _ensure_reasonix_dir() -> None:
    """确保 ~/.reasonix/ 目录存在。"""
    REASONIX_DIR.mkdir(parents=True, exist_ok=True)


def _load_toml_safe() -> Dict[str, Any]:
    """安全加载 TOML 配置，不存在则返回空字典。"""
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError:
            tomllib = None

    if CONFIG_TOML.exists():
        try:
            with open(CONFIG_TOML, "rb") as f:
                return dict(tomllib.load(f)) if tomllib else {}
        except Exception:
            return {}
    return {}


def _save_toml(config: Dict[str, Any]) -> None:
    """保存配置到 config.toml。

    简单的 TOML 序列化（只覆盖常见字段，不依赖第三方 TOML 写入库）。
    如需完整保留注释，建议用 toml 库（pip install toml）。
    """
    _ensure_reasonix_dir()

    # 构建 TOML 文本
    lines = [
        "# Reasonix Bot 配置（由 send-message skill 自动生成）\n",
    ]

    bot = config.get("bot", {})
    lines.append("[bot]\n")
    lines.append(f"enabled = {str(bot.get('enabled', True)).lower()}\n")
    lines.append(f'model = "{bot.get("model", "")}"\n')

    # 飞书
    feishu = bot.get("feishu", {})
    if feishu:
        lines.append("\n[bot.feishu]\n")
        for k, v in feishu.items():
            if isinstance(v, bool):
                lines.append(f"{k} = {str(v).lower()}\n")
            elif isinstance(v, (int, float)):
                lines.append(f"{k} = {v}\n")
            else:
                lines.append(f'{k} = "{v}"\n')

    # 微信
    weixin = bot.get("weixin", {})
    if weixin:
        lines.append("\n[bot.weixin]\n")
        for k, v in weixin.items():
            if isinstance(v, bool):
                lines.append(f"{k} = {str(v).lower()}\n")
            else:
                lines.append(f'{k} = "{v}"\n')

    # QQ
    qq = bot.get("qq", {})
    if qq:
        lines.append("\n[bot.qq]\n")
        for k, v in qq.items():
            if isinstance(v, bool):
                lines.append(f"{k} = {str(v).lower()}\n")
            else:
                lines.append(f'{k} = "{v}"\n')

    # allowlist
    allowlist = bot.get("allowlist", {})
    if allowlist:
        lines.append("\n[bot.allowlist]\n")
        for k, v in allowlist.items():
            if isinstance(v, list):
                items = ", ".join(f'"{x}"' for x in v)
                lines.append(f"{k} = [{items}]\n")
            elif isinstance(v, bool):
                lines.append(f"{k} = {str(v).lower()}\n")
            else:
                lines.append(f'{k} = "{v}"\n')

    # connections
    connections = bot.get("connections", [])
    if connections:
        for conn in connections:
            lines.append("\n[[bot.connections]]\n")
            for k, v in conn.items():
                if k == "session_mappings" and isinstance(v, list):
                    mappings = ", ".join(
                        f'{{{" ".join(f'{sk} = "{sv}"' for sk, sv in m.items())}}}'
                        for m in v
                    )
                    lines.append(f"session_mappings = [{mappings}]\n")
                elif isinstance(v, bool):
                    lines.append(f"{k} = {str(v).lower()}\n")
                elif isinstance(v, (int, float)):
                    lines.append(f"{k} = {v}\n")
                elif isinstance(v, str):
                    lines.append(f'{k} = "{v}"\n')

    with open(CONFIG_TOML, "w", encoding="utf-8") as f:
        f.writelines(lines)

    logger.info("配置已保存到 %s", CONFIG_TOML)


def _load_dotenv() -> Dict[str, str]:
    """加载现有的 .env 文件。"""
    if DOTENV_FILE.exists():
        env = {}
        with open(DOTENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip("\"'")
        return env
    return {}


def _save_dotenv(env: Dict[str, str]) -> None:
    """保存环境变量到 .env。"""
    _ensure_reasonix_dir()
    with open(DOTENV_FILE, "w", encoding="utf-8") as f:
        for k, v in sorted(env.items()):
            f.write(f'{k}="{v}"\n')
    logger.info("环境变量已保存到 %s", DOTENV_FILE)


# ==============================================================
#  统一的配置检查 + 自助配置入口
# ==============================================================

def ensure_bot_config() -> bool:
    """检查是否有可用的 bot 配置，没有则引导用户自助配置。

    Returns:
        True 表示配置可用，False 表示用户跳过。
    """
    has_config = CONFIG_TOML.exists()
    has_bot = False

    if has_config:
        try:
            data = _load_toml_safe()
            bot = data.get("bot", {})
            has_bot = bool(
                bot.get("feishu", {}).get("app_id")
                or bot.get("weixin", {}).get("account_id")
                or bot.get("qq", {}).get("app_id")
            )
        except Exception:
            pass

    if has_bot:
        return True

    # 无配置，提供引导
    print("=" * 50)
    print("🤖 Reasonix Send-Message Skill")
    print("=" * 50)
    print()
    print("未检测到 Bot 配置。请选择一种方式开始：")
    print()
    print("  1) 飞书扫码登录（自动配置）")
    print("  2) 微信扫码登录（自动配置）")
    print("  3) 手动输入配置（QQ 或已有凭据）")
    print("  4) 退出")
    print()

    choice = input("请输入选项 (1/2/3/4): ").strip()

    if choice == "1":
        feishu_full_setup()
        return True
    elif choice == "2":
        weixin_full_setup()
        return True
    elif choice == "3":
        _manual_setup()
        return True
    elif choice == "4":
        print("已跳过配置。下次运行时可以重新配置。")
        return False
    else:
        print("无效选项。")
        return ensure_bot_config()


def _manual_setup() -> None:
    """手动输入配置"""
    print("\n📝 手动配置")
    print("支持的平台: feishu, weixin, qq")
    print("配置将保存到 Reasonix 配置目录（config.toml）")
    print()

    config = _load_toml_safe()
    bot = config.setdefault("bot", {})
    bot.setdefault("allowlist", {})

    while True:
        print("\n当前已配置:", ", ".join(
            k for k in ("feishu", "weixin", "qq") if bot.get(k, {}).get("app_id") or bot.get(k, {}).get("account_id")
        ) or "无")
        print("  1) 配置飞书")
        print("  2) 配置微信")
        print("  3) 配置 QQ")
        print("  4) 保存并退出")
        c = input("请选择: ").strip()

        if c == "1":
            bot.setdefault("feishu", {})
            bot["feishu"]["enabled"] = True
            bot["feishu"]["app_id"] = input("  飞书 App ID: ").strip()
            secret = input("  飞书 App Secret: ").strip()
            if secret:
                env = _load_dotenv()
                env["FEISHU_BOT_APP_SECRET"] = secret
                _save_dotenv(env)
                os.environ["FEISHU_BOT_APP_SECRET"] = secret
            print("  ✅ 飞书配置完成")

        elif c == "2":
            bot.setdefault("weixin", {})
            bot["weixin"]["enabled"] = True
            bot["weixin"]["account_id"] = input("  微信 Account ID (默认 default): ").strip() or "default"
            weixin_chat_id = input("  微信 chat_id (即消息接收者 ID): ").strip()
            if weixin_chat_id:
                connections = bot.setdefault("connections", [])
                if not any(c.get("provider") == "weixin" for c in connections):
                    connections.append({
                        "provider": "weixin",
                        "session_mappings": [{"remote_id": weixin_chat_id}]
                    })
            print("  ✅ 微信配置完成")

        elif c == "3":
            bot.setdefault("qq", {})
            bot["qq"]["enabled"] = True
            bot["qq"]["app_id"] = input("  QQ Bot App ID: ").strip()
            secret = input("  QQ Bot App Secret: ").strip()
            if secret:
                env = _load_dotenv()
                env["QQ_BOT_APP_SECRET"] = secret
                _save_dotenv(env)
                os.environ["QQ_BOT_APP_SECRET"] = secret
            qq_chat_id = input("  QQ chat_id (用户 openid): ").strip()
            if qq_chat_id:
                connections = bot.setdefault("connections", [])
                if not any(c.get("provider") == "qq" for c in connections):
                    connections.append({
                        "provider": "qq",
                        "session_mappings": [{"remote_id": qq_chat_id, "chat_type": "c2c"}]
                    })
            print("  ✅ QQ 配置完成")

        elif c == "4":
            _save_toml(config)
            print(f"✅ 配置已保存到 {CONFIG_TOML}")
            break
