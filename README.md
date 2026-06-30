# reasonix-send-message

向飞书和微信等客户端agent发送文本消息的 Reasonix Skill。

## 快速开始

### 1. 配置飞书/微信机器人

确保你已通过 Reasonix 完成飞书和微信的机器人扫码登录。登录后 Reasonix 会自动在 `~/.reasonix/` 下生成所需的配置文件和 Token。

### 2. 安装 Skill

#### 方式一：手动安装

将本项目放到 Reasonix 项目的 skills 目录：

```bash
cp -r reasonix-send-message /path/to/your-project/.reasonix/skills/reasonix-send-message/
```

#### 方式二：AI 自动安装（推荐）

让 AI 读取 `AI_INSTALL.md` 并根据指引自行完成安装，无需手动操作。

直接对 AI 说：

> 请根据 AI_INSTALL.md 安装 reasonix-send-message skill

AI 会自动读取 `AI_INSTALL.md` 并执行安装步骤。

### 3. 发送消息

```bash
/send-message 你好，这是一条测试消息
```

---

## 使用方式

### 直接调用

```bash
/send-message 消息内容
```

### 从其他 Skill 调用

```javascript
run_skill({ name: "send-message", arguments: "消息内容" })
```

### 命令行调试

```bash
python send.py "消息内容"
```

---

## 文件结构

```
reasonix-send-message/
├── send.py                  # 入口
├── send_message/            # Python 包
│   ├── __init__.py          # SENDERS 注册表
│   ├── config.py            # 配置读取
│   ├── feishu.py            # 飞书
│   └── weixin.py            # 微信
├── SKILL.md                 # Reasonix 技能定义
├── AI_INSTALL.md            # AI 安装指南
└── README.md
```

---

## 扩展

支持飞书、微信以外的平台（如 QQ、Telegram）。详情见 `send_message/__init__.py` 中的扩展指南。

---

## 依赖

- Python 3.8+
- TOML 解析：
  - Python 3.11+ 内置 `tomllib`
  - Python 3.8–3.10 需安装 `tomli`（`pip install tomli`）
