---
name: send-message
description: 向飞书、微信 Bot 和 QQ Bot 发送文本消息。从 Reasonix 权威配置源解析参数，不依赖本地 config.json。
---

# send-message

向飞书、微信 Bot 和 QQ Bot 发送文本消息。

## 调用方式

- 直接：`/send-message 消息内容`
- 带调试日志：`/send-message -v 消息内容`
- 其他 Skill：`run_skill({ name: "send-message", arguments: "消息内容" })`

## 配置来源

本 Skill **不自带任何本地配置**，所有参数均从 Reasonix 为用户存储的权威数据源读取：

### 飞书

| 配置键 | 数据源 |
|--------|--------|
| `feishu.app_id` | `~/.reasonix/config.toml` → `[bot.feishu].app_id` |
| `feishu.app_secret` | `~/.reasonix/.env` → `FEISHU_BOT_APP_SECRET` |
| `feishu.chat_id` | `~/.reasonix/config.toml` → `[[bot.connections]]` → `provider = "feishu"` → `session_mappings[0].remote_id` |

### 微信

| 配置键 | 数据源 |
|--------|--------|
| `weixin.account_id` | `~/.reasonix/config.toml` → `[bot.weixin].account_id`（默认 `"default"`） |
| `weixin.chat_id` | `~/.reasonix/config.toml` → `[[bot.connections]]` → `provider = "weixin"` → `session_mappings[0].remote_id` |
| 微信 Token | `WEIXIN_BOT_TOKEN` 环境变量 或 `~/.reasonix/weixin/accounts/{id}.json` |
| 微信常量 | 代码内硬编码（`api_base`、`channel_version`、`app_id`、`client_version`） |

### QQ

| 配置键 | 数据源 |
|--------|--------|
| `qq.app_id` | `~/.reasonix/config.toml` → `[bot.qq].app_id` |
| `qq.app_secret` | `~/.reasonix/.env` → `QQ_BOT_APP_SECRET`（默认） |
| `qq.chat_id` | `~/.reasonix/config.toml` → `[[bot.connections]]` → `provider = "qq"` → `session_mappings[0].remote_id` |
| `qq.chat_type` | `[[bot.connections]]` → `session_mappings[0].chat_type`（默认 `c2c`） |
| `qq.sandbox` | `[bot.qq].sandbox`（是否使用 QQ 沙箱 API） |
| QQ Token | 自动通过 QQ Bot API 获取（需要 `app_id` + `app_secret`） |

> 如果数据源缺失或字段不存在，会抛出明确的错误信息。

## 执行步骤

### Step 1: 发送消息

自动完成：配置解析 → 环境变量加载 → 飞书发送 → 微信发送 → QQ 发送 → 结果汇报。

```shell
python "{SKILL_DIR}/send.py" "<TEXT>"
```

### 调试模式

```shell
python "{SKILL_DIR}/send.py" -v "<TEXT>"
```

## 依赖

- Python 3.8+，需要 TOML 解析库：
  - Python 3.11+：使用内置 `tomllib`
  - Python 3.8–3.10：需安装 `tomli`（`pip install tomli`）
