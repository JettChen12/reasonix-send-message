"""weixin.py 的单元测试。"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from send_message.weixin import resolve_config, send, _get_token


class TestWeixinResolveConfig(unittest.TestCase):
    """resolve_config() 测试。

    注意: Go ``WeixinBotConfig`` 没有 ``to_user_id`` 字段。
    chat_id 只来自 ``[[bot.connections]]``。
    ``[bot.allowlist].weixin_users`` 仅用于入站访问控制。
    """

    def test_enabled_with_defaults(self):
        bot_cfg = {"weixin": {}}
        result = resolve_config(bot_cfg, {})
        self.assertTrue(result["enabled"])
        self.assertEqual(result["account_id"], "default")
        self.assertEqual(result["chat_id"], "")  # 无 connections
        self.assertEqual(result["token_env"], "WEIXIN_BOT_TOKEN")

    def test_chat_id_from_connections(self):
        bot_cfg = {"weixin": {"account_id": "my_bot"}}
        toml_data = {
            "bot": {
                "connections": [
                    {
                        "provider": "weixin",
                        "session_mappings": [{"remote_id": "wx_user_xxx"}],
                    }
                ]
            }
        }
        result = resolve_config(bot_cfg, toml_data)
        self.assertEqual(result["chat_id"], "wx_user_xxx")

    def test_allowlist_not_used_for_chat_id(self):
        """allowlist 不影响 chat_id。"""
        bot_cfg = {
            "weixin": {},
            "allowlist": {"weixin_users": ["should_not_use"]},
        }
        result = resolve_config(bot_cfg, {})
        self.assertEqual(result["chat_id"], "")

    def test_token_env_from_config(self):
        """token_env 从 TOML 配置读取。"""
        bot_cfg = {"weixin": {"account_id": "my_bot", "token_env": "MY_WX_TOKEN"}}
        result = resolve_config(bot_cfg, {})
        self.assertEqual(result["token_env"], "MY_WX_TOKEN")

    def test_hardcoded_defaults(self):
        bot_cfg = {"weixin": {}}
        result = resolve_config(bot_cfg, {})
        self.assertEqual(result["api_base"], "https://ilinkai.weixin.qq.com")


class TestWeixinGetToken(unittest.TestCase):
    """_get_token() 测试。"""

    def test_from_env(self):
        with patch.dict(os.environ, {"WEIXIN_BOT_TOKEN": "env_token"}):
            token = _get_token("default")
            self.assertEqual(token, "env_token")

    def test_from_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            accounts_dir = Path(tmpdir) / "accounts"
            accounts_dir.mkdir(parents=True)
            token_file = accounts_dir / "default.json"
            with open(token_file, "w") as f:
                json.dump({"token": "file_token"}, f)

            with patch.dict(os.environ, {}, clear=True):
                with patch(
                    "send_message.weixin.WEIXIN_ACCOUNTS_DIR", accounts_dir
                ):
                    token = _get_token("default")
                    self.assertEqual(token, "file_token")

    def test_no_token_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            accounts_dir = Path(tmpdir) / "accounts"
            accounts_dir.mkdir(parents=True)
            with patch.dict(os.environ, {}, clear=True):
                with patch(
                    "send_message.weixin.WEIXIN_ACCOUNTS_DIR", accounts_dir
                ):
                    token = _get_token("nonexistent")
                    self.assertIsNone(token)


class TestWeixinSend(unittest.TestCase):
    """send() 测试。"""

    def test_disabled(self):
        result = send("hello", {"weixin": {"enabled": False}})
        self.assertEqual(result["code"], "skipped")

    def test_no_token(self):
        cfg = {
            "weixin": {
                "enabled": True, "account_id": "test", "chat_id": "user_xxx",
            }
        }
        with patch.dict(os.environ, {}, clear=True):
            with patch("send_message.weixin.WEIXIN_ACCOUNTS_DIR", Path("/nonexistent")):
                result = send("hello", cfg)
                self.assertEqual(result["code"], "no_token")

    @patch("send_message.weixin.urllib.request.urlopen")
    def test_successful_send(self, mock_urlopen):
        cfg = {
            "weixin": {
                "enabled": True, "account_id": "test", "chat_id": "wx_user",
                "api_base": "https://ilinkai.weixin.qq.com",
                "channel_version": "2.2.0",
                "app_id": "bot",
                "client_version": 131584,
            }
        }
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'{"ret": 0, "errcode": 0, "errmsg": "", "message_id": "wx_msg_xxx"}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        with patch.dict(os.environ, {"WEIXIN_BOT_TOKEN": "test_token"}):
            result = send("hello", cfg)
            self.assertTrue(result["ok"])
            self.assertEqual(result["message_id"], "wx_msg_xxx")
            self.assertEqual(result["ret"], 0)
            self.assertEqual(result["errcode"], 0)


if __name__ == "__main__":
    unittest.main()
