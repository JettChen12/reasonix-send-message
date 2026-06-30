"""qq.py 的单元测试。"""

import json
import os
import unittest
from unittest.mock import patch

from send_message.qq import resolve_config, send, _get_access_token, QQ_TOKEN_URL


class TestQQResolveConfig(unittest.TestCase):
    """resolve_config() 测试。

    注意: Go ``QQBotConfig`` 没有 ``chat_id`` 字段。
    chat_id 只来自 ``[[bot.connections]]``。
    """

    def test_enabled_with_basic_fields(self):
        bot_cfg = {"qq": {"app_id": "test_app"}}
        result = resolve_config(bot_cfg, {})
        self.assertTrue(result["enabled"])
        self.assertEqual(result["app_id"], "test_app")
        self.assertEqual(result["chat_id"], "")       # 无 connections
        self.assertEqual(result["chat_type"], "c2c")   # 默认

    def test_chat_id_from_connections(self):
        bot_cfg = {"qq": {"app_id": "test_app", "chat_type": "c2c"}}
        toml_data = {
            "bot": {
                "connections": [
                    {
                        "provider": "qq",
                        "session_mappings": [{"remote_id": "qq_user_xxx"}],
                    }
                ]
            }
        }
        result = resolve_config(bot_cfg, toml_data)
        self.assertEqual(result["chat_id"], "qq_user_xxx")

    def test_chat_type_from_connections(self):
        bot_cfg = {"qq": {"app_id": "test_app"}}
        toml_data = {
            "bot": {
                "connections": [
                    {
                        "provider": "qq",
                        "session_mappings": [
                            {"remote_id": "qq_group_xxx", "chat_type": "group"}
                        ],
                    }
                ]
            }
        }
        result = resolve_config(bot_cfg, toml_data)
        self.assertEqual(result["chat_type"], "group")

    def test_sandbox_mode(self):
        bot_cfg = {"qq": {"app_id": "test_app", "sandbox": True}}
        result = resolve_config(bot_cfg, {})
        self.assertTrue(result["sandbox"])

    def test_chat_id_fallback_type_field(self):
        """兼容旧版 ``type`` 字段名。"""
        bot_cfg = {"qq": {"app_id": "test_app"}}
        toml_data = {
            "bot": {
                "connections": [
                    {
                        "type": "qq",
                        "session_mappings": [{"remote_id": "qq_type_xxx"}],
                    }
                ]
            }
        }
        result = resolve_config(bot_cfg, toml_data)
        self.assertEqual(result["chat_id"], "qq_type_xxx")


class TestQQGetAccessToken(unittest.TestCase):
    """_get_access_token() 测试。"""

    @patch("send_message.qq._request")
    def test_success(self, mock_request):
        mock_request.return_value = {
            "access_token": "test_token",
            "expires_in": 7200,
        }
        token = _get_access_token("app_id", "secret")
        self.assertEqual(token, "test_token")

    @patch("send_message.qq._request")
    def test_failure(self, mock_request):
        mock_request.return_value = {"error": "invalid credentials"}
        with self.assertRaises(Exception):
            _get_access_token("app_id", "wrong")


class TestQQSend(unittest.TestCase):
    """send() 测试。"""

    def test_disabled(self):
        result = send("hello", {"qq": {"enabled": False}})
        self.assertEqual(result["code"], "skipped")

    def test_missing_secret(self):
        cfg = {
            "qq": {
                "enabled": True,
                "app_id": "test_app",
                "chat_id": "user_xxx",
            }
        }
        with patch.dict(os.environ, {}, clear=True):
            result = send("hello", cfg)
            self.assertEqual(result["code"], "config_error")


if __name__ == "__main__":
    unittest.main()
