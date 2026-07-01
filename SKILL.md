---
name: send-message
description: 向飞书、微信 Bot 和 QQ Bot 发送文本消息。从 Reasonix 权威配置源解析参数，不依赖本地 config.json。
---

# send-message

向飞书、微信 Bot 和 QQ Bot 发送文本消息的 Reasonix Skill。
采用插件化 sender 架构，新增平台无需修改 CLI 和 config 模块。

## 项目架构

```
reasonix-send-message/
├── send.py                    # CLI 入口
├── send_message/              # Python 包
│   ├── __init__.py            # SENDERS 插件注册表
│   ├── config.py              # 配置加载（TOML + .env）
│   ├── _retry.py              # HTTP 指数退避重试
│   ├── setup.py               # 自助配置引导（OAuth / 扫码）
│   ├── feishu.py              # 飞书 sender
│   ├── weixin.py              # 微信 sender
│   └── qq.py                  # QQ sender
├── tests/                     # 单元测试
├── SKILL.md                   # 本文件
├── AI_INSTALL.md              # AI 安装指南
└── README.md
```

### 架构设计

- **插件注册表**：`__init__.py` 中的 `SENDERS` dict 统一管理所有平台模块。
- **接口规范**：每个 sender 模块必须暴露 `CHANNEL_NAME`、`REQUIRED_KEYS`、`resolve_config()`、`send()`。
- **配置遍历**：`config.py` 的 `resolve_config()` 遍历 `SENDERS` 调用各模块的解析器，无需手动维护两份配置注册表。
- **重试机制**：`_retry.py` 提供指数退避重试（默认 3 次），飞书和 QQ 模块内部使用。

## 调用方式

### 命令行

```shell
# 发送到所有已启用渠道
python "{SKILL_DIR}/send.py" "消息内容"

# 指定渠道（可重复使用）
python "{SKILL_DIR}/send.py" -c weixin "消息内容"
python "{SKILL_DIR}/send.py" -c weixin -c feishu "消息内容"

# 调试模式（输出详细日志）
python "{SKILL_DIR}/send.py" -v "消息内容"
python "{SKILL_DIR}/send.py" -v -c weixin "消息内容"
```

### 作为 Skill 调用

```
/send-message 消息内容
/send-message -c weixin 消息内容
```

### 从其他 Skill 调用

```
run_skill({{ name: "send-message", arguments: "消息内容" }})
```

### 参数说明

| 参数 | 说明 |
|------|------|
| `text` | 消息文本内容（位置参数） |
| `-c`, `--channel` | 指定发送渠道，可选 `feishu` / `weixin` / `qq`，可重复使用。不指定则发送所有已启用渠道 |
| `-v`, `--verbose` | 输出 DEBUG 级别日志 |

## 完整执行流程

```
send.py main()
  │
  ├─ 1. ensure_bot_config()
  │     ├─ 检查 config.toml 是否存在且包含任一平台配置
  │     ├─ 有配置 → 直接返回 True
  │     └─ 无配置 → 进入自助配置引导（见下方）
  │
  ├─ 2. resolve_config()
  │     ├─ 读取 config.toml（%APPDATA%/reasonix/ 或 ~/.reasonix/）
  │     ├─ 加载 .env 到 os.environ（不覆盖已存在的变量）
  │     └─ 遍历 SENDERS 注册表，调用各模块的 resolve_config(bot_cfg, toml_data)
  │         ├─ feishu: app_id + chat_id（来自 connections）+ app_secret_env
  │         ├─ weixin: account_id + chat_id（来自 connections）+ token
  │         └─ qq: app_id + chat_id + chat_type（来自 connections）+ sandbox
  │
  ├─ 3. 遍历 SENDERS 发送
  │     ├─ --channel 过滤（指定则只发选中渠道）
  │     ├─ 检查 enabled 状态
  │     ├─ 校验 REQUIRED_KEYS
  │     └─ sender.send(text, cfg)
  │         ├─ feishu: env secret → tenant_access_token → POST /im/v1/messages
  │         ├─ weixin: 主 token → iLink /ilink/bot/sendmessage
  │         └─ qq: env secret → access_token → POST /v2/users|groups/{id}/messages
  │
  └─ 4. _print_report() — 汇总打印 ✅/❌/⏭️
```

## 配置来源

本 Skill **不自带任何本地配置**，所有参数均从 Reasonix 桌面端存储的权威数据源读取。

配置路径自动适配各平台：
- **Windows**: `%APPDATA%/reasonix/config.toml` + `.env`
- **macOS**: `~/.reasonix/config.toml` + `.env`
- **Linux**: `$XDG_CONFIG_HOME/reasonix/` 或 `~/.reasonix/`

> 如果桌面端路径下配置不存在，会自动回退到 `~/.reasonix/`。

### 飞书

| 配置键 | 数据源 |
|--------|--------|
| `feishu.app_id` | `config.toml` → `[bot.feishu].app_id` |
| `feishu.app_secret` | `.env` → `FEISHU_BOT_APP_SECRET`（环境变量名由 `app_secret_env` 指定） |
| `feishu.chat_id` | `config.toml` → `[[bot.connections]]` → `provider = "feishu"` → `session_mappings[0].remote_id` |

飞书发送流程：从 `.env` 读 App Secret → 调用 `/auth/v3/tenant_access_token/internal` 获取 tenant token → 调用 `/im/v1/messages` 发送。

### 微信

| 配置键 | 数据源 |
|--------|--------|
| `weixin.account_id` | `config.toml` → `[bot.weixin].account_id`（默认 `"default"`） |
| `weixin.chat_id` | `config.toml` → `[[bot.connections]]` → `provider = "weixin"` → `session_mappings[0].remote_id` |
| 微信 Token | `WEIXIN_BOT_TOKEN` 环境变量 或 `{REASONIX_DIR}/weixin/accounts/{id}.json` |
| 微信常量 | 代码内硬编码（`api_base`=`https://ilinkai.weixin.qq.com`、`channel_version`=`2.2.0`、`app_id`=`bot`、`client_version`=`131584`） |

微信发送流程：读取主 bot token（环境变量 → 账号文件）→ 调用 iLink `/ilink/bot/sendmessage`。

> **⚠️ 主 token 说明**：本 Skill 直接使用主 bot token 发送消息（不再使用 context token，避免过期问题）。使用主 token 调用 `/ilink/bot/sendmessage` 时，API 返回 `ret=-1, errcode=-1` 是**正常现象**，消息已成功送达。这与使用 context token 时返回 `ret=0, errcode=0` 不同，**不是错误**。

### QQ

| 配置键 | 数据源 |
|--------|--------|
| `qq.app_id` | `config.toml` → `[bot.qq].app_id` |
| `qq.app_secret` | `.env` → `QQ_BOT_APP_SECRET`（或回退 `QQ_SECRET`） |
| `qq.chat_id` | `config.toml` → `[[bot.connections]]` → `provider = "qq"` → `session_mappings[0].remote_id` |
| `qq.chat_type` | `[[bot.connections]]` → `session_mappings[0].chat_type`（默认 `c2c`，可选 `group`） |
| `qq.sandbox` | `[bot.qq].sandbox`（是否使用 QQ 沙箱 API，默认 `false`） |

QQ 发送流程：从 `.env` 读 App Secret → 调用 `/app/getAppAccessToken` 获取 access_token → 根据 chat_type 调用 `/v2/users/{id}/messages`（C2C）或 `/v2/groups/{id}/messages`（群聊）。

> 如果数据源缺失或字段不存在，会抛出明确的错误信息。

## 自助配置

如果用户还没有配置 Bot，`/send-message` 会自动进入配置引导：

```
==================================================
🤖 Reasonix Send-Message Skill
==================================================

未检测到 Bot 配置。请选择一种方式开始：

  1) 飞书扫码登录（自动配置）
  2) 微信扫码登录（自动配置）
  3) 手动输入配置（QQ 或已有凭据）
  4) 退出
```

- **选项 1**：飞书 OAuth 设备码流程 → 打印二维码 URL → 手机扫码授权 → 自动保存 `app_id`/`app_secret` 到 `config.toml` 和 `.env`
- **选项 2**：微信 iLink Bot 扫码 → 打印二维码 URL → 微信扫码 → 自动保存 token 到 `weixin/accounts/{id}.json` 和 `config.toml`
- **选项 3**：手动输入各平台配置，保存到 `config.toml` 和 `.env`

## 依赖

- Python 3.8+
- TOML 解析库：
  - Python 3.11+：使用内置 `tomllib`
  - Python 3.8–3.10：需安装 `tomli`（`pip install tomli`）

## 扩展新平台

添加新平台只需 **2 步**，`config.py` 和 `send.py` 不需要任何修改：

1. 新建 `send_message/<platform>.py`，实现以下模块级接口：

```python
CHANNEL_NAME = "显示名称"
REQUIRED_KEYS = {"field1", "field2"}

def resolve_config(bot_cfg: dict, toml_data: dict) -> dict:
    """从 config.toml 解析本平台配置，返回包含 enabled 字段的 dict"""

def send(text: str, cfg: dict) -> dict:
    """发送消息，返回 {"ok": bool, "code": str, "msg": str, ...}"""
```

2. 在 `send_message/__init__.py` 的 `_register()` 中添加一项：

```python
from send_message import new_platform

_register({
    # ...existing...
    "new_platform": new_platform,
})
```
