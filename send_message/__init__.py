"""reasonix-send-message Python 包 — 插件化 sender 架构。

所有 sender 模块遵循同一接口规范，通过 ``SENDERS`` 注册表统一调度。
``config.py`` 的 ``resolve_config()`` 自动遍历 ``SENDERS`` 调用各模块的
``resolve_config()``，无需手动维护两份注册表。

扩展指南
--------
添加新平台只需 **2 步**：

1. 新建 ``send_message/<new_platform>.py``，实现以下模块级接口::

    CHANNEL_NAME = "<显示名称>"                   # 显示名称
    REQUIRED_KEYS = {"field1", "field2"}          # 必填配置字段

    def resolve_config(bot_cfg: dict, toml_data: dict) -> dict:
        \"""从 ``~/.reasonix/config.toml`` 解析本平台配置。\"""

    def send(text: str, cfg: dict) -> dict:
        \"""发送消息。返回 {"ok": bool, "code": str, "msg": str, ...}\"""

2. 在本文件底部 ``_register()`` 中加一项

``config.py`` 和 ``send.py`` **不需要任何修改**。
"""

from typing import Any, Dict

from send_message import feishu
from send_message import weixin
from send_message import qq

# sender 模块注册表
# key: 配置中的平台名，value: 模块对象
# 每个模块必须暴露 CHANNEL_NAME, REQUIRED_KEYS, resolve_config(), send()
SENDERS: Dict[str, Any] = {}


def _register(senders: Dict[str, Any]) -> None:
    """注册 sender 模块到全局注册表。"""
    SENDERS.update(senders)


_register({
    "feishu": feishu,
    "weixin": weixin,
    "qq": qq,
})
