import json
import os
import tempfile
import unittest
from unittest import mock

import app


class ApiConfigMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.current = os.path.join(self.temp.name, "desktop", "data", "api-config.json")
        self.legacy = os.path.join(self.temp.name, "data", "api-config.json")
        os.makedirs(os.path.dirname(self.current), exist_ok=True)
        os.makedirs(os.path.dirname(self.legacy), exist_ok=True)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _write(path, value):
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)

    def test_empty_desktop_key_recovers_legacy_config_and_keeps_launch_preferences(self):
        self._write(self.current, {
            "provider": "deepseek",
            "api_key": "",
            "ql_path": "D:/current-workspace",
            "ql_perm": "std",
        })
        self._write(self.legacy, {
            "provider": "anthropic",
            "api_key": "legacy-secret-1234",
            "api_endpoint": "https://example.invalid/messages",
            "api_model": "claude-haiku-4-5-20251001",
        })

        config = app.load_api_config(self.current, [self.legacy])

        self.assertEqual(config["api_key"], "legacy-secret-1234")
        self.assertEqual(config["provider"], "anthropic")
        self.assertEqual(config["ql_path"], "D:/current-workspace")
        with open(self.current, encoding="utf-8") as stream:
            persisted = json.load(stream)
        self.assertEqual(persisted["api_key"], "legacy-secret-1234")
        self.assertFalse(os.path.exists(self.current + ".tmp"))

    def test_existing_desktop_key_is_not_overwritten(self):
        self._write(self.current, {"api_key": "desktop-secret-5678"})
        self._write(self.legacy, {"api_key": "legacy-secret-1234"})

        config = app.load_api_config(self.current, [self.legacy])

        self.assertEqual(config["api_key"], "desktop-secret-5678")

    def test_key_hint_never_exposes_full_secret(self):
        with mock.patch.object(app, "_ai_config", {"api_key": "secret-value-9876"}):
            hint = app.masked_api_key()
        self.assertEqual(hint, "••••••••9876")
        self.assertNotIn("secret-value", hint)


if __name__ == "__main__":
    unittest.main()
