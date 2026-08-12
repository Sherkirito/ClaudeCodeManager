import json
import os
import tempfile
import unittest
from unittest import mock

import v2_index


def read_jsonl(path, max_entries=None):
    rows = []
    with open(path, encoding="utf-8") as stream:
        for line in stream:
            rows.append(json.loads(line))
            if max_entries and len(rows) >= max_entries:
                break
    return rows


def fix_text(value):
    return value


class LogicalProjectIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.projects = os.path.join(self.temp.name, "projects")
        self.record_id = "D--Work-----"
        self.record_dir = os.path.join(self.projects, self.record_id)
        os.makedirs(self.record_dir)
        self.real_a = os.path.join(self.temp.name, "项目甲")
        os.makedirs(self.real_a)
        self.missing_b = os.path.join(self.temp.name, "项目乙")
        self.db = os.path.join(self.temp.name, "index.sqlite3")
        self._write_session("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", self.real_a, "甲任务")
        self._write_session("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", self.missing_b, "乙任务")

    def tearDown(self):
        self.temp.cleanup()

    def _write_session(self, session_id, cwd, title):
        path = os.path.join(self.record_dir, session_id + ".jsonl")
        rows = [
            {
                "type": "user",
                "uuid": session_id,
                "timestamp": 1700000000000,
                "cwd": cwd,
                "entrypoint": "cli",
                "message": {"role": "user", "content": title},
            },
            {"type": "ai-title", "aiTitle": title},
        ]
        with open(path, "w", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    def test_colliding_record_folder_is_split_by_initial_cwd(self):
        stats = v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        self.assertEqual(stats["indexed"], 2)
        projects = v2_index.list_projects(self.db, limit=20)["items"]
        self.assertEqual(len(projects), 2)
        by_path = {row["cwd"]: row for row in projects}
        self.assertEqual(by_path[self.real_a]["path_exists"], 1)
        self.assertEqual(by_path[self.missing_b]["path_exists"], 0)
        self.assertEqual(by_path[self.real_a]["grouping_reason"], "cwd_collision")
        self.assertNotEqual(by_path[self.real_a]["id"], self.record_id)

        sessions_a = v2_index.list_sessions(self.db, project_id=by_path[self.real_a]["id"])
        self.assertEqual(sessions_a["total"], 1)
        self.assertEqual(sessions_a["items"][0]["title"], "甲任务")
        self.assertEqual(sessions_a["items"][0]["record_project_id"], self.record_id)

    def test_unchanged_refresh_reuses_file_index(self):
        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        guarded_reader = mock.Mock(side_effect=AssertionError("unchanged JSONL must not be parsed again"))
        stats = v2_index.scan_incremental(self.db, self.projects, guarded_reader, fix_text)
        self.assertEqual(stats["indexed"], 0)
        self.assertEqual(stats["sessions"], 2)
        guarded_reader.assert_not_called()

    def test_unchanged_refresh_updates_path_existence_without_full_rebuild(self):
        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        os.rmdir(self.real_a)
        stats = v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        self.assertEqual(stats["indexed"], 0)
        projects = v2_index.list_projects(self.db, limit=20)["items"]
        by_path = {row["cwd"]: row for row in projects}
        self.assertEqual(by_path[self.real_a]["path_exists"], 0)

    def test_unchanged_refresh_removes_stale_project_rows(self):
        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        conn = v2_index.connect(self.db)
        try:
            v2_index.init_db(conn)
            conn.execute(
                "INSERT INTO projects(id, name, cwd) VALUES('ghost-project', 'ghost', 'ghost')"
            )
            conn.commit()
        finally:
            conn.close()
        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        ids = {row["id"] for row in v2_index.list_projects(self.db, limit=20)["items"]}
        self.assertNotIn("ghost-project", ids)

    def test_history_metadata_is_persistent_and_reconciled_without_reread(self):
        orphan_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
        history_path = os.path.join(self.temp.name, "history.jsonl")
        with open(history_path, "w", encoding="utf-8") as stream:
            stream.write(json.dumps({
                "sessionId": orphan_id,
                "project": self.real_a,
                "timestamp": 1700000000000,
                "display": "请检查并完成这个项目中的关键功能",
            }, ensure_ascii=False) + "\n")

        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        self.assertEqual(v2_index.list_orphan_history_sessions(self.db)["total"], 1)

        self._write_session(orphan_id, self.real_a, "恢复后的任务")
        real_open = open

        def guarded_open(path, *args, **kwargs):
            if os.path.realpath(path) == os.path.realpath(history_path):
                raise AssertionError("unchanged history.jsonl must not be read again")
            return real_open(path, *args, **kwargs)

        with mock.patch("builtins.open", side_effect=guarded_open):
            v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        self.assertEqual(v2_index.list_orphan_history_sessions(self.db)["total"], 0)


class AutomaticSessionIndexTests(unittest.TestCase):
    """Cover job / sdk / subagent sessions: listing, detail, search and stats."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.projects = os.path.join(self.temp.name, "projects")
        self.record_id = "D--Auto"
        self.record_dir = os.path.join(self.projects, self.record_id)
        os.makedirs(self.record_dir)
        self.cwd = os.path.join(self.temp.name, "auto-project")
        os.makedirs(self.cwd)
        self.db = os.path.join(self.temp.name, "index.sqlite3")
        self.primary_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        self.job_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        self.sdk_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
        # The synthetic id is <parent>--<agent file base name>, e.g. ...--agent-0001
        self.agent_name = "agent-0001"
        self.subagent_id = self.primary_id + "--" + self.agent_name

        self._write_session(self.primary_id, "主会话标题")
        self._write_session(self.job_id, "后台任务标题", entrypoint=None)
        self._write_session(self.sdk_id, "SDK 自动任务标题", entrypoint="sdk-cli")

        jobs_dir = os.path.join(self.temp.name, "jobs")
        state_path = os.path.join(jobs_dir, "job-1", "state.json")
        os.makedirs(os.path.dirname(state_path))
        with open(state_path, "w", encoding="utf-8") as stream:
            json.dump({"sessionId": self.job_id}, stream)

        self.subagent_path = os.path.join(
            self.record_dir, self.primary_id, "subagents", self.agent_name + ".jsonl"
        )
        os.makedirs(os.path.dirname(self.subagent_path))
        with open(self.subagent_path, "w", encoding="utf-8") as stream:
            for row in [
                {
                    "type": "user", "timestamp": 1700000004000, "cwd": self.cwd,
                    "message": {"role": "user", "content": "子代理收到的指令"},
                },
                {
                    "type": "assistant", "timestamp": 1700000005000, "cwd": self.cwd,
                    "message": {"role": "assistant", "model": "deepseek-v4-pro", "content": "子代理的回复",
                                "usage": {"input_tokens": 30, "output_tokens": 10}},
                },
            ]:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")

        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        self.logical_id = v2_index.list_projects(self.db)["items"][0]["id"]

    def tearDown(self):
        self.temp.cleanup()

    def _write_session(self, session_id, title, entrypoint="cli"):
        path = os.path.join(self.record_dir, session_id + ".jsonl")
        row = {
            "type": "user", "uuid": session_id, "timestamp": 1700000000000,
            "cwd": self.cwd, "message": {"role": "user", "content": title},
        }
        if entrypoint is not None:
            row["entrypoint"] = entrypoint
        with open(path, "w", encoding="utf-8") as stream:
            for entry in [row, {"type": "ai-title", "aiTitle": title}]:
                stream.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def test_list_sessions_defaults_to_primary_only(self):
        data = v2_index.list_sessions(self.db, project_id=self.logical_id)
        self.assertEqual(data["kind"], "primary")
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["session_kind"], "primary")
        self.assertEqual(data["primary_total"], 1)
        self.assertEqual(data["automatic_all_total"], 3)
        self.assertEqual(data["automatic_total"], 2)
        self.assertEqual(len(data["automatic_items"]), 2)

    def test_list_sessions_kind_primary_returns_only_primaries(self):
        data = v2_index.list_sessions(self.db, project_id=self.logical_id, kind="primary")
        self.assertEqual(data["total"], 1)
        self.assertTrue(all(row["session_kind"] == "primary" for row in data["items"]))

    def test_list_sessions_kind_all_includes_every_automatic_kind(self):
        data = v2_index.list_sessions(self.db, project_id=self.logical_id, kind="all")
        self.assertEqual(data["total"], 4)
        self.assertEqual(
            {row["session_kind"] for row in data["items"]},
            {"primary", "job", "sdk", "subagent"},
        )
        subagent = next(row for row in data["items"] if row["session_kind"] == "subagent")
        self.assertEqual(subagent["parent_session_id"], self.primary_id)
        self.assertEqual(subagent["parent"]["id"], self.primary_id)
        # flat mode must not nest children, so nothing appears twice
        for row in data["items"]:
            self.assertNotIn("children", row)

    def test_list_sessions_kind_automatic_returns_job_sdk_subagent(self):
        data = v2_index.list_sessions(self.db, project_id=self.logical_id, kind="automatic")
        self.assertEqual(data["total"], 3)
        self.assertEqual(
            {row["session_kind"] for row in data["items"]},
            {"job", "sdk", "subagent"},
        )
        job = next(row for row in data["items"] if row["session_kind"] == "job")
        self.assertEqual(job["parent_session_id"], "")
        self.assertIsNone(job["parent"])
        subagent = next(row for row in data["items"] if row["session_kind"] == "subagent")
        self.assertEqual(subagent["parent"]["id"], self.primary_id)

    def test_unknown_kind_falls_back_to_primary(self):
        data = v2_index.list_sessions(self.db, project_id=self.logical_id, kind="bogus")
        self.assertEqual(data["kind"], "primary")
        self.assertEqual(data["total"], 1)

    def test_session_detail_opens_job_session_with_indexed_messages(self):
        detail = v2_index.session_detail(self.db, self.logical_id, self.job_id)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["session"]["session_kind"], "job")
        self.assertEqual(detail["messages_source"], "index")
        self.assertFalse(detail["stats_on_demand"])
        self.assertEqual(detail["total"], 1)
        self.assertEqual(detail["messages"][0]["role"], "user")

    def test_session_detail_reads_subagent_messages_on_demand(self):
        detail = v2_index.session_detail(self.db, self.logical_id, self.subagent_id)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["session"]["session_kind"], "subagent")
        self.assertEqual(detail["messages_source"], "jsonl")
        self.assertTrue(detail["stats_on_demand"])
        self.assertEqual(detail["total"], 2)
        self.assertEqual(detail["messages"][0]["role"], "user")
        self.assertEqual(detail["session"]["parent"]["id"], self.primary_id)
        # stats are recomputed from the full log, not the capped index row
        self.assertEqual(detail["session"]["total_tokens"], 40)
        self.assertEqual(detail["session"]["total_msgs"], 2)

    def test_session_detail_subagent_paginates_on_demand(self):
        detail = v2_index.session_detail(self.db, self.logical_id, self.subagent_id, limit=1, offset=1)
        self.assertEqual(detail["total"], 2)
        self.assertEqual(len(detail["messages"]), 1)
        self.assertEqual(detail["messages"][0]["role"], "assistant")

    def test_session_detail_subagent_missing_file_reports_unavailable(self):
        os.remove(self.subagent_path)
        detail = v2_index.session_detail(self.db, self.logical_id, self.subagent_id)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["messages_source"], "unavailable")
        self.assertEqual(detail["total"], 0)
        self.assertEqual(detail["messages"], [])

    def test_automatic_session_with_and_without_parent_both_resolve(self):
        job = v2_index.session_detail(self.db, self.logical_id, self.job_id)
        self.assertIsNone(job["session"]["parent"])
        subagent = v2_index.session_detail(self.db, self.logical_id, self.subagent_id)
        self.assertEqual(subagent["session"]["parent"]["id"], self.primary_id)

    def test_search_finds_automatic_sessions_with_kind_and_parent(self):
        rows = [row for row in v2_index.search(self.db, "后台任务")["items"] if row["type"] == "session"]
        job = next(row for row in rows if row["session_id"] == self.job_id)
        self.assertEqual(job["session_kind"], "job")
        self.assertEqual(job["project_id"], self.logical_id)
        self.assertEqual(job["record_project_id"], self.record_id)

        rows = [row for row in v2_index.search(self.db, "子代理")["items"] if row["type"] == "session"]
        subagent = next(row for row in rows if row["session_id"] == self.subagent_id)
        self.assertEqual(subagent["session_kind"], "subagent")
        self.assertEqual(subagent["parent_title"], "主会话标题")

    def test_search_result_opens_automatic_session_detail(self):
        rows = [row for row in v2_index.search(self.db, "后台任务")["items"] if row["type"] == "session"]
        job = next(row for row in rows if row["session_id"] == self.job_id)
        self.assertEqual(job["project_id"], self.logical_id)
        detail = v2_index.session_detail(self.db, job["project_id"], job["session_id"])
        self.assertEqual(detail["session"]["id"], self.job_id)
        self.assertEqual(detail["session"]["session_kind"], "job")

    def test_project_counts_keep_primary_and_automatic_separate(self):
        projects = v2_index.list_projects(self.db)["items"]
        self.assertEqual(len(projects), 1)
        project = projects[0]
        self.assertEqual(project["session_count"], 1)
        self.assertEqual(project["automatic_session_count"], 3)
        self.assertEqual(project["all_session_count"], 4)

    def test_dashboard_counts_automatic_sessions(self):
        stats = v2_index.dashboard(self.db)["stats"]
        self.assertEqual(stats["total_sessions"], 1)
        self.assertEqual(stats["total_automatic_sessions"], 3)
        self.assertEqual(stats["total_all_sessions"], 4)


class DashboardStatsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.projects = os.path.join(self.temp.name, "projects")
        self.record_dir = os.path.join(self.projects, "D--Dashboard")
        self.cwd = os.path.join(self.temp.name, "dashboard-project")
        self.db = os.path.join(self.temp.name, "index.sqlite3")
        os.makedirs(self.record_dir)
        os.makedirs(self.cwd)

    def tearDown(self):
        self.temp.cleanup()

    def _write_rows(self, session_id, rows):
        path = os.path.join(self.record_dir, session_id + ".jsonl")
        with open(path, "w", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    def test_dashboard_uses_30_day_deduplicated_api_usage(self):
        self._write_rows("primary-session", [
            {
                "type": "user", "timestamp": "2026-08-01T09:00:00Z", "cwd": self.cwd,
                "entrypoint": "cli", "message": {"role": "user", "content": "第一天"},
            },
            {
                "type": "assistant", "timestamp": "2026-08-01T09:01:00Z", "cwd": self.cwd,
                "message": {"id": "resp-shared", "role": "assistant", "model": "deepseek-v4-pro", "content": "完成", "usage": {
                    "input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 500,
                }},
            },
            {
                "type": "assistant", "timestamp": "2026-08-01T09:01:01Z", "cwd": self.cwd,
                "message": {"id": "resp-shared", "role": "assistant", "model": "deepseek-v4-pro", "content": "同一响应的内容分块", "usage": {
                    "input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 500,
                }},
            },
            {
                "type": "user", "timestamp": "2026-08-02T10:00:00Z", "cwd": self.cwd,
                "message": {"role": "user", "content": "第二天"},
            },
            {
                "type": "assistant", "timestamp": "2026-08-02T10:01:00Z", "cwd": self.cwd,
                "message": {"id": "resp-primary-2", "role": "assistant", "model": "deepseek-v4-flash", "content": "完成", "usage": {
                    "input_tokens": 50, "output_tokens": 10, "cache_creation_input_tokens": 100,
                }},
            },
        ])
        self._write_rows("sdk-session", [
            {
                "type": "user", "timestamp": "2026-08-02T12:00:00Z", "cwd": self.cwd,
                "entrypoint": "sdk-cli", "message": {"role": "user", "content": "自动任务"},
            },
            {
                "type": "assistant", "timestamp": "2026-08-02T12:01:00Z", "cwd": self.cwd,
                "message": {"id": "resp-shared", "role": "assistant", "model": "deepseek-v4-pro", "content": "克隆日志中的同一响应", "usage": {
                    "input_tokens": 10, "output_tokens": 5,
                }},
            },
        ])

        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        data = v2_index.dashboard(self.db, today="2026-08-04")
        stats = data["stats"]

        self.assertEqual(stats["total_sessions"], 1)
        self.assertEqual(stats["total_automatic_sessions"], 1)
        self.assertEqual(stats["total_all_sessions"], 2)
        self.assertEqual(stats["total_primary_messages"], 5)
        self.assertEqual(stats["total_automatic_messages"], 2)
        self.assertEqual(stats["total_all_messages"], 7)
        self.assertEqual(stats["api_unique_responses_30d"], 2)
        self.assertEqual(stats["api_input_output_tokens_30d"], 180)
        self.assertEqual(stats["api_cache_tokens_30d"], 600)
        self.assertEqual(stats["api_tokens_30d"], 780)

        self.assertEqual(data["api_usage_period"], {
            "start": "2026-07-06", "end": "2026-08-04", "days": 30,
        })
        self.assertEqual(data["api_usage"], [
            {
                "model": "deepseek-v4-pro", "unique_responses": 1,
                "input_tokens": 100, "output_tokens": 20,
                "cache_creation_tokens": 0, "cache_read_tokens": 500,
                "total_tokens": 620,
            },
            {
                "model": "deepseek-v4-flash", "unique_responses": 1,
                "input_tokens": 50, "output_tokens": 10,
                "cache_creation_tokens": 100, "cache_read_tokens": 0,
                "total_tokens": 160,
            },
        ])
        self.assertEqual(data["recent_sessions"][0]["total_tokens"], 180)
        self.assertEqual(data["recent_sessions"][0]["cache_tokens"], 600)


if __name__ == "__main__":
    unittest.main()
