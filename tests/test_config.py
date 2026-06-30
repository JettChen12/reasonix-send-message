"""config.py 的单元测试。"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from send_message.config import (
    read_dotenv,
    load_dotenv_into_environ,
    find_chat_id_from_connections,
)


class TestReadDotenv(unittest.TestCase):
    """read_dotenv() 测试。"""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".env", delete=False, encoding="utf-8"
        )
        self.path = Path(self.tmp.name)

    def tearDown(self):
        try:
            self.tmp.close()
        except Exception:
            pass
        self.path.unlink(missing_ok=True)

    def test_empty_file(self):
        self.tmp.write("")
        self.tmp.close()
        result = read_dotenv(self.path)
        self.assertEqual(result, {})

    def test_simple_key_value(self):
        self.tmp.write("KEY=value\n")
        self.tmp.close()
        result = read_dotenv(self.path)
        self.assertEqual(result, {"KEY": "value"})

    def test_quoted_value(self):
        self.tmp.write('KEY="quoted value"\n')
        self.tmp.close()
        result = read_dotenv(self.path)
        self.assertEqual(result, {"KEY": "quoted value"})

    def test_comments_and_blanks(self):
        self.tmp.write("# comment\n\nKEY=val\n")
        self.tmp.close()
        result = read_dotenv(self.path)
        self.assertEqual(result, {"KEY": "val"})

    def test_missing_file(self):
        result = read_dotenv(Path("/nonexistent/.env"))
        self.assertEqual(result, {})

    def test_export_prefix(self):
        self.tmp.write("export FOO=bar\n")
        self.tmp.close()
        result = read_dotenv(self.path)
        self.assertEqual(result, {"FOO": "bar"})


class TestLoadDotenvIntoEnviron(unittest.TestCase):
    """load_dotenv_into_environ() 测试。"""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".env", delete=False, encoding="utf-8"
        )
        self.path = Path(self.tmp.name)

    def tearDown(self):
        try:
            self.tmp.close()
        except Exception:
            pass
        self.path.unlink(missing_ok=True)

    @patch("send_message.config.DOTENV_FILE")
    def test_loads_and_does_not_overwrite(self, mock_dotenv):
        self.tmp.write("EXISTING_KEY=from_file\nNEW_KEY=from_file\n")
        self.tmp.close()
        mock_dotenv.__fspath__ = lambda self: str(self)
        mock_dotenv.exists.return_value = True

        with patch("send_message.config.DOTENV_FILE", self.path):
            with patch.dict(os.environ, {"EXISTING_KEY": "from_env"}, clear=True):
                load_dotenv_into_environ()
                self.assertEqual(os.environ["EXISTING_KEY"], "from_env")
                self.assertEqual(os.environ["NEW_KEY"], "from_file")


class TestFindChatIdFromConnections(unittest.TestCase):
    """find_chat_id_from_connections() 测试。"""

    def test_finds_correct_provider(self):
        toml = {
            "bot": {
                "connections": [
                    {"provider": "feishu", "session_mappings": [{"remote_id": "oc_feishu"}]},
                    {"provider": "weixin", "session_mappings": [{"remote_id": "wx_user"}]},
                    {"provider": "qq", "session_mappings": [{"remote_id": "qq_user"}]},
                ]
            }
        }
        self.assertEqual(
            find_chat_id_from_connections(toml, "feishu"), "oc_feishu"
        )
        self.assertEqual(
            find_chat_id_from_connections(toml, "weixin"), "wx_user"
        )
        self.assertEqual(
            find_chat_id_from_connections(toml, "qq"), "qq_user"
        )

    def test_fallback_type_field(self):
        """兼容旧版 ``type`` 字段名。"""
        toml = {
            "bot": {
                "connections": [
                    {"type": "feishu", "session_mappings": [{"remote_id": "oc_type"}]},
                ]
            }
        }
        self.assertEqual(
            find_chat_id_from_connections(toml, "feishu"), "oc_type"
        )

    def test_provider_takes_precedence_over_type(self):
        """``provider`` 字段优先于 ``type``。"""
        toml = {
            "bot": {
                "connections": [
                    {
                        "provider": "weixin",
                        "type": "feishu",
                        "session_mappings": [{"remote_id": "correct_wx"}],
                    },
                ]
            }
        }
        self.assertEqual(
            find_chat_id_from_connections(toml, "weixin"), "correct_wx"
        )
        self.assertIsNone(
            find_chat_id_from_connections(toml, "feishu")
        )

    def test_no_connections_returns_none(self):
        self.assertIsNone(find_chat_id_from_connections({}, "feishu"))
        self.assertIsNone(
            find_chat_id_from_connections({"bot": {"connections": []}}, "feishu")
        )

    def test_no_matching_provider_returns_none(self):
        toml = {
            "bot": {
                "connections": [
                    {"provider": "feishu", "session_mappings": [{"remote_id": "oc"}]},
                ]
            }
        }
        self.assertIsNone(find_chat_id_from_connections(toml, "qq"))


if __name__ == "__main__":
    unittest.main()
