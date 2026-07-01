# AI Install Guide: reasonix-send-message

本文档供 AI agent 使用。当用户说"帮我装这个 skill"时，按此文档执行。

---

## 1. 项目概览

Reasonix Skill，通过 Python 脚本向飞书、微信 Bot 和 QQ Bot 发送文本消息。
所有配置从 `~/.reasonix/` 读取，**不依赖本地 config.json**。

## 2. 安装步骤

### 2.1 放置文件

将整个 `reasonix-send-message` 目录复制到用户 Reasonix 项目的 skills 目录：

```
目标位置: {project_root}/.reasonix/skills/reasonix-send-message/
```

### 2.2 检查 Python 环境

```
python --version                # 需 >= 3.8
```

如果 Python < 3.11，需安装 TOML 解析库：

```
pip install tomli
```

验证 TOML 库可用：

```
python -c "import tomllib; print('ok')" 2>/dev/null ||
python -c "import tomli; print('ok')" 2>/dev/null ||
echo "需要安装 tomli: pip install tomli"
```

### 2.3 验证 Skill 可执行

```
cd {skill_dir}
python send.py --help
```

正常输出：

```
usage: send.py [-h] [-v] [text]

向飞书、微信、QQ 等 Bot 发送文本消息
```

### 2.4 完整链路测试（无配置时进入自助配置引导）

```
python send.py "test"
```

预期输出：

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

该 Skill 支持自动配置：选择 1 或 2 后，会打印二维码 URL，
用户在手机浏览器打开并扫码授权，配置自动保存到 `~/.reasonix/`。
也可由用户在 Reasonix 桌面端完成 Bot 配置后再使用本 Skill。

---

## 3. 配置参考（AI 读取用）

Sender 模块从 `~/.reasonix/` 下的以下文件读取配置：

### 3.1 `~/.reasonix/config.toml` 结构

```toml
[bot]
  [bot.feishu]
  app_id = "<飞书 App ID>"
  app_secret_env = "FEISHU_BOT_APP_SECRET"

  [bot.weixin]
  account_id = "<微信 Bot 账号 ID>"

  [bot.qq]
  app_id = "<QQ Bot App ID>"
  app_secret_env = "QQ_BOT_APP_SECRET"
  sandbox = false
  chat_type = "c2c"

  [bot.allowlist]
  weixin_users = ["<微信用户 ID>"]
  qq_users = ["<QQ 用户 openid>"]
  qq_groups = ["<QQ 群 openid>"]

  [[bot.connections]]
  provider = "feishu"
  session_mappings = [{remote_id = "<飞书群聊 ID>"}]

  [[bot.connections]]
  provider = "weixin"
  session_mappings = [{remote_id = "<微信用户 ID>"}]

  [[bot.connections]]
  provider = "qq"
  session_mappings = [{remote_id = "<QQ 用户 openid>", chat_type = "c2c"}]
```

| 字段 | 说明 |
|------|------|
| `[bot.feishu].app_id` | 飞书应用的 App ID |
| `[bot.feishu].app_secret_env` | 存 App Secret 的环境变量名（默认 `FEISHU_BOT_APP_SECRET`） |
| `[bot.feishu].chat_id` | 群聊 ID（可选，没有则从 `[[bot.connections]]` 自动查找） |
| `[bot.weixin].account_id` | 微信 Bot 账号 ID（默认 `default`） |
| `[bot.allowlist].weixin_users[0]` | 接收消息的微信用户 ID |
| `[bot.qq].app_id` | QQ Bot App ID |
| `[bot.qq].app_secret_env` | 存 App Secret 的环境变量名（默认 `QQ_BOT_APP_SECRET`） |
| `[bot.qq].sandbox` | 是否使用 QQ 沙箱 API（默认 `false`） |
| `[bot.qq].chat_type` | 消息类型：`c2c`（私聊）或 `group`（群聊）（默认 `c2c`） |
| `[bot.allowlist].qq_users[0]` | QQ chat_id 的备选来源（c2c 模式） |
| `[bot.allowlist].qq_groups[0]` | QQ chat_id 的备选来源（group 模式） |
| `[[bot.connections]]` 中 feishu 连接 → `session_mappings[0].remote_id` | 飞书 chat_id 的备选来源 |

### 3.2 `~/.reasonix/.env`

```
FEISHU_BOT_APP_SECRET=实际secret值
QQ_BOT_APP_SECRET=实际secret值
WEIXIN_BOT_TOKEN=实际token值
```

### 3.3 `~/.reasonix/weixin/accounts/`

Token 文件，以 JSON 格式存放：

```json
{"token": "微信BotToken值"}
```

查找优先级：环境变量 `WEIXIN_BOT_TOKEN` → `~/.reasonix/weixin/accounts/{account_id}.json` → `default.json`

### 3.4 代码内常量（不可配置）

| 字段 | 默认值 |
|------|--------|
| `weixin.api_base` | `https://ilinkai.weixin.qq.com` |
| `weixin.channel_version` | `2.2.0` |
| `weixin.app_id` | `bot` |
| `weixin.client_version` | `131584` |
| `qq.base_url` | `https://api.sgroup.qq.com`（正式）/ `https://sandbox.api.sgroup.qq.com`（沙箱） |
| `qq.token_url` | `https://bots.qq.com/app/getAppAccessToken` |

---

## 4. 配置验证

检查必需文件是否存在：

```bash
ls ~/.reasonix/config.toml || echo "缺少主配置文件"
ls ~/.reasonix/.env || echo "缺少环境变量文件"
ls ~/.reasonix/weixin/accounts/*.json 2>/dev/null || echo "缺少微信 token 文件"
```

检查 Python 能否解析 TOML：

```bash
python -c "
import tomllib
from pathlib import Path
with open(Path.home() / '.reasonix' / 'config.toml', 'rb') as f:
    cfg = tomllib.load(f)
print('TOML 解析成功')
print('飞书 app_id:', cfg.get('bot',{}).get('feishu',{}).get('app_id',''))
print('微信 account_id:', cfg.get('bot',{}).get('weixin',{}).get('account_id',''))
print('QQ app_id:', cfg.get('bot',{}).get('qq',{}).get('app_id',''))
"
```

## 5. 常见问题

### Q: 没有 `~/.reasonix/config.toml`
用户需要通过 Reasonix 完成飞书/微信/QQ 的扫码登录。引导用户使用 Reasonix 的登录功能。

### Q: Python 版本低，没有 tomllib
```bash
pip install tomli
```

### Q: 飞书发送失败，报 config_error
检查 `~/.reasonix/.env` 中有没有 `FEISHU_BOT_APP_SECRET`，或环境变量 `FEISHU_BOT_APP_SECRET` 是否设置：
```bash
# 查看环境变量是否设置
echo $FEISHU_BOT_APP_SECRET
# 或查看 .env 文件
cat ~/.reasonix/.env
```

### Q: 微信发送失败，报 no_token
```bash
# 是否有环境变量
echo $WEIXIN_BOT_TOKEN
# 是否有账号文件
ls ~/.reasonix/weixin/accounts/
```

### Q: QQ 发送失败，报 token_error
```bash
# 检查环境变量
echo $QQ_BOT_APP_SECRET
# 或查看 .env
cat ~/.reasonix/.env
```

---

## 6. 代码结构与扩展

所有 sender 模块遵循同一接口规范，通过 `SENDERS` 注册表统一调度。

平台目录结构：

```
send_message/
├── __init__.py    # SENDERS 注册表
├── config.py      # 配置读取（TOML + .env）
├── feishu.py      # 飞书
├── weixin.py      # 微信
├── qq.py          # QQ（新增）
└── _retry.py      # HTTP 重试工具
```

添加新平台只需 2 步：
1. 新建 `send_message/<new>.py`，实现 `CHANNEL_NAME`、`REQUIRED_KEYS`、`resolve_config()`、`send()`
2. 在 `__init__.py` 的 `_register()` 中加一项
