# reasonix-send-message

向飞书、微信 Bot 和 QQ Bot 等客户端发送文本消息的 Reasonix Skill。

## 安装

### 方式一：手动安装

```bash
# 1. 克隆仓库
git clone https://github.com/JettChen12/reasonix-send-message.git

# 2. 将项目复制到 Reasonix 项目的 skills 目录
#    找到你的 Reasonix 项目根目录（含有 .reasonix/ 的目录），然后：
cp -r reasonix-send-message /path/to/your-project/.reasonix/skills/reasonix-send-message/

# 3. （可选）完成后可删除克隆的临时目录
rm -rf reasonix-send-message
```

> **小贴士**：也可以用符号链接代替复制，方便后续更新：
> ```bash
> ln -s /absolute/path/to/reasonix-send-message /path/to/your-project/.reasonix/skills/
> ```

**依赖说明**：本项目仅使用 Python 标准库，无需 `pip install`。如果 Python 版本低于 3.11，需安装 TOML 解析库：
```bash
python --version  # 确认版本
pip install tomli  # Python < 3.11 才需要
```

---

### 方式二：AI 自动安装（推荐）

如果你在使用 **Claude Code** 或其他 AI 编程助手，可以直接让 AI 帮你完成安装：

1. 在 Reasonix 项目根目录下运行 AI 助手
2. 对 AI 说：

> 请帮我安装 send-message skill：https://github.com/JettChen12/reasonix-send-message

AI 会读取 `AI_INSTALL.md`，自动完成克隆、复制、环境检查等全部步骤。

> **原理**：AI 通过读取 [`AI_INSTALL.md`](AI_INSTALL.md) 中的详细指引，一步步执行安装操作。用户只需提供 GitHub 仓库地址即可。

---

### 验证安装

检查 Skill 是否可用：

```bash
cd /path/to/your-project
python .reasonix/skills/reasonix-send-message/send.py --help
```

正常应输出：
```
usage: send.py [-h] [-v] [text]

向飞书、微信、QQ 等 Bot 发送文本消息
```

---

### 首次配置

**无需预先配置 Bot**：如果还没有配置，首次发送消息时自动进入配置引导：

```bash
cd /path/to/your-project
python .reasonix/skills/reasonix-send-message/send.py "Hello World"
```

然后按提示选择扫码登录或手动输入即可完成自动配置。

---

### 发送消息

在 Reasonix 中运行以下命令发送消息：

```bash
/send-message 你好，这是一条测试消息
```

---

## 使用方式

### 直接调用

```bash
/send-message 消息内容
```

### 调试模式

```bash
/send-message -v 消息内容
```

### 从其他 Skill 调用

```javascript
run_skill({ name: "send-message", arguments: "消息内容" })
```

### 命令行调试

```bash
python send.py "消息内容"
```

```bash
python send.py -v "消息内容"   # 带调试日志
```

---

## 文件结构

```
reasonix-send-message/
├── send.py                  # CLI 入口
├── send_message/            # Python 包
│   ├── __init__.py          # SENDERS 注册表
│   ├── config.py            # 配置读取
│   ├── feishu.py            # 飞书
│   ├── weixin.py            # 微信
│   ├── qq.py                # QQ（新增）
│   └── _retry.py            # HTTP 重试工具
├── tests/                   # 单元测试
│   ├── test_config.py
│   ├── test_feishu.py
│   ├── test_weixin.py
│   └── test_qq.py
├── SKILL.md                 # Reasonix 技能定义
├── AI_INSTALL.md            # AI 安装指南
└── README.md
```

---

## 扩展

支持飞书、微信、QQ 以外的平台（如 Telegram）。详情见 `send_message/__init__.py` 中的扩展指南。

---

## 配置来源

所有参数均从 Reasonix 权威数据源读取：

| 平台 | 配置文件 | 主要字段 |
|------|----------|----------|
| 飞书 | `~/.reasonix/config.toml` → `[bot.feishu]` | `app_id`, `app_secret_env`, `chat_id` |
| 微信 | `~/.reasonix/config.toml` → `[bot.weixin]` + `[bot.allowlist]` | `account_id`, `to_user_id` |
| QQ | `~/.reasonix/config.toml` → `[bot.qq]` + `[bot.allowlist]` | `app_id`, `chat_id`, `chat_type` |

密钥通过环境变量或 `~/.reasonix/.env` 提供。

---

## 依赖

- Python 3.8+
- TOML 解析：
  - Python 3.11+ 内置 `tomllib`
  - Python 3.8–3.10 需安装 `tomli`（`pip install tomli`）
