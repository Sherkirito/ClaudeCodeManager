import os
import sqlite3
import tempfile
import unittest
from datetime import datetime

import cc_switch_usage


class CCSwitchUsageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.temp.name, "cc-switch.db")
        conn = sqlite3.connect(self.db)
        conn.executescript(
            """
            CREATE TABLE proxy_request_logs (
                request_id TEXT PRIMARY KEY,
                app_type TEXT NOT NULL,
                model TEXT NOT NULL,
                request_model TEXT,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                cache_read_tokens INTEGER NOT NULL DEFAULT 0,
                cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
                total_cost_usd TEXT NOT NULL DEFAULT '0',
                status_code INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                data_source TEXT NOT NULL DEFAULT 'proxy'
            );
            """
        )
        conn.close()

    def tearDown(self):
        self.temp.cleanup()

    def _insert(self, request_id, app_type, model, source, timestamp,
                input_tokens, output_tokens, cache_read, cache_creation, cost, status=200):
        conn = sqlite3.connect(self.db)
        conn.execute(
            """
            INSERT INTO proxy_request_logs(
                request_id, app_type, model, request_model, input_tokens,
                output_tokens, cache_read_tokens, cache_creation_tokens,
                total_cost_usd, status_code, created_at, data_source
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id, app_type, model, model, input_tokens, output_tokens,
                cache_read, cache_creation, cost, status,
                int(datetime.fromisoformat(timestamp).timestamp()), source,
            ),
        )
        conn.commit()
        conn.close()

    def test_reads_only_claude_code_session_billing_rows(self):
        self._insert("pro-1", "claude", "deepseek-v4-pro", "session_log", "2026-08-01T10:00:00", 100, 20, 500, 0, "0.123")
        self._insert("pro-2", "claude", "deepseek-v4-pro", "session_log", "2026-08-02T10:00:00", 50, 10, 100, 0, "0.05", 500)
        self._insert("flash-1", "claude", "deepseek-v4-flash", "session_log", "2026-08-03T10:00:00", 10, 2, 30, 4, "0.01")
        self._insert("proxy-copy", "claude", "deepseek-v4-pro", "proxy", "2026-08-03T11:00:00", 9999, 9999, 9999, 9999, "99")
        self._insert("codex", "codex", "gpt-5", "codex_session", "2026-08-03T12:00:00", 9999, 9999, 9999, 0, "99")
        self._insert("desktop", "claude-desktop", "claude-opus", "proxy", "2026-08-03T13:00:00", 9999, 9999, 9999, 0, "99")
        self._insert("old", "claude", "deepseek-v4-pro", "session_log", "2026-07-01T10:00:00", 9999, 9999, 9999, 0, "99")

        usage = cc_switch_usage.read_claude_code_usage(self.db, today="2026-08-08")

        self.assertEqual(usage["source"]["app_type"], "claude")
        self.assertEqual(usage["source"]["data_source"], "session_log")
        self.assertEqual(usage["source"]["available_sources"], ["proxy", "session_log"])
        self.assertEqual(usage["period"], {"start": "2026-07-10", "end": "2026-08-08", "days": 30})
        self.assertEqual(usage["totals"], {
            "request_count": 3,
            "success_count": 2,
            "input_tokens": 160,
            "output_tokens": 32,
            "cache_read_tokens": 630,
            "cache_creation_tokens": 4,
            "total_tokens": 826,
            "total_cost_usd": "0.183",
        })
        self.assertEqual(usage["items"][0]["model"], "deepseek-v4-pro")
        self.assertEqual(usage["items"][0]["request_count"], 2)
        self.assertEqual(usage["items"][0]["total_tokens"], 780)

        dashboard = {"stats": {}, "last_scan": "123"}
        cc_switch_usage.apply_to_dashboard(dashboard, usage)
        self.assertEqual(dashboard["stats"]["api_tokens_30d"], 826)
        self.assertEqual(dashboard["stats"]["api_request_count_30d"], 3)
        self.assertEqual(dashboard["stats"]["api_cost_usd_30d"], "0.183")
        self.assertEqual(dashboard["usage_source"]["id"], "cc_switch")

    def test_uses_proxy_when_no_session_import_exists(self):
        self._insert("proxy-1", "claude", "deepseek-v4-flash", "proxy", "2026-08-08T08:00:00", 10, 5, 20, 0, "0.02")
        usage = cc_switch_usage.read_claude_code_usage(self.db, today="2026-08-08")
        self.assertEqual(usage["source"]["data_source"], "proxy")
        self.assertEqual(usage["totals"]["total_tokens"], 35)

    def test_missing_database_is_a_clean_fallback(self):
        with self.assertRaises(cc_switch_usage.CCSwitchUsageUnavailable):
            cc_switch_usage.read_claude_code_usage(os.path.join(self.temp.name, "missing.db"))
        dashboard = {"last_scan": "42"}
        cc_switch_usage.mark_local_fallback(dashboard)
        self.assertEqual(dashboard["usage_source"]["id"], "local_index")
        self.assertFalse(dashboard["usage_source"]["exact"])


if __name__ == "__main__":
    unittest.main()
