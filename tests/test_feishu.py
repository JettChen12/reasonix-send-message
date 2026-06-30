"""feishu.py 的单元测试。"""

import json
import os
import unittest
from unittest.mock import patch, MagicMock

from send_message.feishu import resolve_config, send, _get_tenant_token


class TestFeishuResolveConfig(unittest.TestCase):
    """resolve_config() 测试。

    注意: Go ``FeishuBotConfig`` 没有 ``chat_id`` 字段。
    chat_id 只来自 ``[[bot.connections]]`` 的 ``provider`` 字段。
    """

    def test_enabled_with_all_fields(self):
        bot_cfg = {
            "feishu": {
                "app_id": "cli_xxx",
                "app_secret_env": "MY_FEISHU_SECRET",
            }
        }
        result = resolve_config(bot_cfg, {})
        self.assertTrue(result["enabled"])
        self.assertEqual(result["app_id"], "cli_xxx")
        self.assertEqual(result["app_secret_env"], "MY_FEISHU_SECRET")
        # chat_id 来自 connections，这里没有 connections，所以为空
        self.assertEqual(result["chat_id"], "")

    def test_disabled_when_no_feishu_section(self):
        result = resolve_config({}, {})
        self.assertEqual(result, {})

    def test_chat_id_from_connections(self):
        bot_cfg = {"feishu": {}}
        toml_data = {
            "bot": {
                "connections": [
                    {
                        "provider": "feishu",  # Go 原生字段名
                        "session_mappings": [{"remote_id": "oc_feishu_xxx"}],
                    }
                ]
            }
        }
        result = resolve_config(bot_cfg, toml_data)
        self.assertEqual(result["chat_id"], "oc_feishu_xxx")

    def test_chat_id_from_connections_fallback_type(self):
        """兼容旧版 ``type`` 字段名。"""
        bot_cfg = {"feishu": {}}
        toml_data = {
            "bot": {
                "connections": [
                    {
                        "type": "feishu",
                        "session_mappings": [{"remote_id": "oc_type_xxx"}],
                    }
                ]
            }
        }
        result = resolve_config(bot_cfg, toml_data)
        self.assertEqual(result["chat_id"], "oc_type_xxx")

    def test_no_connections_empty_chat_id(self):
        """没有 feishu 连接时 chat_id 为空字符串。"""
        bot_cfg = {"feishu": {"app_id": "cli_xxx"}}
        toml_data = {
            "bot": {
                "connections": [
                    {"provider": "weixin", "session_mappings": [{"remote_id": "wx_xxx"}]}
                ]
            }
        }
        result = resolve_config(bot_cfg, toml_data)
        self.assertEqual(result["chat_id"], "")


class TestFeishuGetTenantToken(unittest.TestCase):
    """_get_tenant_token() 测试。"""

    @patch("send_message.feishu._request")
    def test_success(self, mock_request):
        mock_request.return_value = {
            "code": 0,
            "tenant_access_token": "my_token",
            "expire": 7200,
        }
        token = _get_tenant_token("app_id", "secret")
        self.assertEqual(token, "my_token")

    @patch("send_message.feishu._request")
    def test_failure(self, mock_request):
        mock_request.return_value = {"code": 10003, "msg": "invalid app_secret"}
        with self.assertRaises(Exception):
            _get_tenant_token("app_id", "wrong_secret")


class TestFeishuSend(unittest.TestCase):
    """send() 测试。"""

    def test_disabled(self):
        result = send("hello", {"feishu": {"enabled": False}})
        self.assertEqual(result["code"], "skipped")

    def test_missing_secret(self):
        cfg = {
            "feishu": {
                "enabled": True, "app_id": "cli_xxx", "chat_id": "oc_xxx",
            }
        }
        with patch.dict(os.environ, {}, clear=True):
            result = send("hello", cfg)
            self.assertEqual(result["code"], "config_error")

    @patch("send_message.feishu._request")
    def test_successful_send(self, mock_request):
        cfg = {
            "feishu": {
                "enabled": True, "app_id": "cli_xxx", "chat_id": "oc_xxx",
            }
        }
        mock_request.side_effect = [
            {"code": 0, "tenant_access_token": "test_token"},
            {"code": 0, "msg": "success", "data": {"message_id": "om_xxx"}},
        ]
        with patch.dict(os.environ, {"FEISHU_BOT_APP_SECRET": "test_secret"}):
            result = send("测试消息", cfg)
            self.assertTrue(result["ok"])
            self.assertEqual(result["code"], "0")
            self.assertEqual(result["message_id"], "om_xxx")


if __name__ == "__main__":
    unittest.main()
