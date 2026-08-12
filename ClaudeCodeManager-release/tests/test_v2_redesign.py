"""v2.1.0 redesign tests: schema v6, the kind decision tree, facet-driven
list_sessions, session_detail slimming and the orphan restore guarantee.

Fixtures are built exclusively from synthetic data in tempfile dirs — no
real session content, member cwd or machine paths appear anywhere here.
"""

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


class RedesignIndexTests(unittest.TestCase):
    """One synthetic project covering all five kinds plus team configs.

    Sessions: lead (primary), job (jobs registry), sdk (entrypoint sdk-cli),
    helper (plain subagent), indexer (teammate via .meta.json),
    planner (teammate via config member prefix), researcher (teammate whose
    teamName resolves by display name only).
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = self.temp.name
        self.projects = os.path.join(root, "projects")
        self.record_id = "D--Redesign"
        self.record_dir = os.path.join(self.projects, self.record_id)
        self.cwd = os.path.join(root, "redesign-project")
        os.makedirs(self.record_dir)
        os.makedirs(self.cwd)
        self.db = os.path.join(root, "index.sqlite3")

        self.lead_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        self.job_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        self.sdk_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
        self.helper_agent = "ahelper-0011223344556677"
        self.helper_id = self.lead_id + "--agent-" + self.helper_agent
        self.indexer_agent = "aindexer-a1b2c3d4e5f60718"
        self.indexer_id = self.lead_id + "--agent-" + self.indexer_agent
        self.planner_agent = "aplanner-9f8e7d6c5b4a3210"
        self.planner_id = self.lead_id + "--agent-" + self.planner_agent
        self.researcher_agent = "aresearcher-777788889999aaaa"
        self.researcher_id = self.lead_id + "--agent-" + self.researcher_agent
        self.team_id = "demo-team"
        self.team_name = "Demo Team"

        self._write_top("主会话标题", self.lead_id, agent_id="team-lead@lead-1")
        self._write_top("后台任务标题", self.job_id, entrypoint=None)
        self._write_top("SDK 自动任务标题", self.sdk_id, entrypoint="sdk-cli")
        state_path = os.path.join(root, "jobs", "job-1", "state.json")
        os.makedirs(os.path.dirname(state_path))
        with open(state_path, "w", encoding="utf-8") as stream:
            json.dump({"sessionId": self.job_id}, stream)

        self._write_nested(self.helper_agent, "普通子代理任务")
        self._write_nested(self.indexer_agent, "成员任务", meta={
            "agentType": "indexer", "name": "indexer", "description": "成员 indexer",
            "color": "#3366ff", "taskKind": "in_process_teammate",
            "teamName": self.team_id, "model": "deepseek-v4-pro",
        })
        self._write_nested(self.planner_agent, "规划任务")
        self._write_nested(self.researcher_agent, "研究任务", meta={
            "agentType": "researcher", "name": "researcher",
            "taskKind": "in_process_teammate", "teamName": self.team_name,
        })
        self._write_team_config()

        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        self.logical_id = v2_index.list_projects(self.db)["items"][0]["id"]

    def tearDown(self):
        self.temp.cleanup()

    # -- helpers --------------------------------------------------------------

    def _write_jsonl(self, path, rows):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _write_top(self, title, session_id, entrypoint="cli", agent_id=""):
        row = {
            "type": "user", "uuid": session_id, "timestamp": 1700000000000,
            "cwd": self.cwd, "entrypoint": entrypoint,
            "message": {"role": "user", "content": title},
        }
        if agent_id:
            row["agentId"] = agent_id
        self._write_jsonl(
            os.path.join(self.record_dir, session_id + ".jsonl"),
            [row, {"type": "ai-title", "aiTitle": title}],
        )

    def _write_nested(self, agent_id, text, meta=None):
        base = os.path.join(self.record_dir, self.lead_id, "subagents")
        log_path = os.path.join(base, "agent-" + agent_id + ".jsonl")
        self._write_jsonl(log_path, [
            {
                "type": "user", "uuid": "u-" + agent_id, "timestamp": 1700000004000,
                "cwd": self.cwd, "isSidechain": True, "agentId": agent_id,
                "sessionId": self.lead_id,
                "message": {"role": "user", "content": text},
            },
            {
                "type": "assistant", "timestamp": 1700000005000, "cwd": self.cwd,
                "message": {"role": "assistant", "model": "deepseek-v4-pro",
                            "content": "回复",
                            "usage": {"input_tokens": 50, "output_tokens": 10}},
            },
        ])
        if meta:
            with open(log_path[:-6] + ".meta.json", "w", encoding="utf-8") as stream:
                json.dump(meta, stream, ensure_ascii=False)
        return log_path

    def _write_team_config(self, team_id=None, name=None):
        team_id = team_id or self.team_id
        config = {
            "name": name or self.team_name,
            "createdAt": 1700000000000,
            "leadAgentId": "team-lead@lead-1",
            "leadSessionId": self.lead_id,
            "members": [
                {"agentId": "team-lead@lead-1", "name": "team-lead",
                 "joinedAt": "2026-08-01T09:00:00", "cwd": self.cwd},
                {"agentId": "indexer@member-1", "name": "indexer",
                 "joinedAt": "2026-08-01T09:01:00", "cwd": self.cwd,
                 "color": "#3366ff", "agentType": "indexer"},
                {"agentId": "planner@member-2", "name": "planner",
                 "joinedAt": "2026-08-01T09:02:00", "cwd": self.cwd},
            ],
        }
        path = os.path.join(self.temp.name, "teams", team_id, "config.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(config, stream, ensure_ascii=False)
        return path

    def _session_row(self, session_id):
        conn = v2_index.connect(self.db)
        try:
            return dict(conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone())
        finally:
            conn.close()

    # -- schema v6 ------------------------------------------------------------

    def test_schema_v6_columns_and_version(self):
        conn = v2_index.connect(self.db)
        try:
            v2_index.init_db(conn)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
            for column in ("kind", "meta_json", "link_source", "jsonl_rel_path"):
                self.assertIn(column, columns)
            member_columns = {row["name"] for row in conn.execute("PRAGMA table_info(team_members)")}
            self.assertIn("role", member_columns)
            version = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
            self.assertEqual(version["value"], "6")
        finally:
            conn.close()

    def test_v5_to_v6_backfill_via_force_rescan(self):
        # Simulate a pre-v6 database: drop the new columns and stamp v5.
        conn = v2_index.connect(self.db)
        try:
            v2_index.init_db(conn)
            for column in ("kind", "meta_json", "link_source", "jsonl_rel_path"):
                conn.execute(f"ALTER TABLE sessions DROP COLUMN {column}")
            conn.execute("ALTER TABLE team_members DROP COLUMN role")
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', '5')")
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('relation_index_version', '5')")
            conn.commit()
        finally:
            conn.close()
        v2_index._SCHEMA_READY.clear()
        stats = v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        self.assertEqual(stats["indexed"], 7)
        conn = v2_index.connect(self.db)
        try:
            v2_index.init_db(conn)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
            for column in ("kind", "meta_json", "link_source", "jsonl_rel_path"):
                self.assertIn(column, columns)
            version = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
            self.assertEqual(version["value"], "6")
            job = self._row(self.db, "SELECT kind FROM sessions WHERE id = ?", self.job_id)
            self.assertEqual(job["kind"], "job")
            indexer = self._row(
                self.db,
                "SELECT kind, link_source, meta_json FROM sessions WHERE id = ?",
                self.indexer_id,
            )
            self.assertEqual(indexer["kind"], "teammate")
            self.assertEqual(indexer["link_source"], "meta")
            self.assertNotEqual(indexer["meta_json"], "")
        finally:
            conn.close()

    @staticmethod
    def _row(db_path, sql, *params):
        conn = v2_index.connect(db_path)
        try:
            return dict(conn.execute(sql, params).fetchone())
        finally:
            conn.close()

    # -- kind decision tree (§3.1) --------------------------------------------

    def test_decision_tree_top_level_job_sdk_primary(self):
        for session_id, expected in (
            (self.lead_id, "primary"),
            (self.job_id, "job"),
            (self.sdk_id, "sdk"),
        ):
            row = self._session_row(session_id)
            self.assertEqual(row["kind"], expected)
            self.assertEqual(row["link_source"], "")
            self.assertEqual(row["parent_session_id"], "")

    def test_decision_tree_nested_meta_teammate(self):
        row = self._session_row(self.indexer_id)
        self.assertEqual(row["kind"], "teammate")
        self.assertEqual(row["link_source"], "meta")
        self.assertEqual(row["team_id"], self.team_id)
        self.assertEqual(row["task_kind"], "in_process_teammate")
        # transition backfill keeps the historical nested value
        self.assertEqual(row["session_kind"], "subagent")

    def test_decision_tree_nested_config_teammate(self):
        row = self._session_row(self.planner_id)
        self.assertEqual(row["kind"], "teammate")
        self.assertEqual(row["link_source"], "config")
        self.assertEqual(row["team_id"], self.team_id)
        self.assertEqual(row["team_confidence"], "lead_dir")
        self.assertEqual(row["task_kind"], "in_process_teammate")

    def test_decision_tree_nested_plain_subagent(self):
        row = self._session_row(self.helper_id)
        self.assertEqual(row["kind"], "subagent")
        self.assertEqual(row["link_source"], "exact")
        self.assertEqual(row["parent_session_id"], self.lead_id)
        self.assertEqual(row["team_id"], "")
        self.assertEqual(row["task_kind"], "")

    def test_link_source_name_only_for_team_resolved_by_display_name(self):
        row = self._session_row(self.researcher_id)
        self.assertEqual(row["kind"], "teammate")
        self.assertEqual(row["link_source"], "name_only")
        self.assertEqual(row["team_id"], self.team_id)
        self.assertEqual(row["team_confidence"], "team_name")

    def test_job_inferred_parent_sets_inferred_link_source(self):
        primary_id = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
        job_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        shared = ["s-" + str(idx) for idx in range(4)]
        self._write_jsonl(os.path.join(self.record_dir, primary_id + ".jsonl"), [
            {
                "type": "user", "uuid": uuid, "timestamp": 1700000100000 + idx,
                "cwd": self.cwd, "entrypoint": "cli",
                "message": {"role": "user", "content": "克隆源消息 " + uuid},
            }
            for idx, uuid in enumerate(shared)
        ])
        self._write_jsonl(os.path.join(self.record_dir, job_id + ".jsonl"), [
            {
                "type": "user", "uuid": uuid, "timestamp": 1700000200000 + idx,
                "cwd": self.cwd,
                "message": {"role": "user", "content": "克隆任务消息 " + uuid},
            }
            for idx, uuid in enumerate(shared + ["s-extra"])
        ])
        state_path = os.path.join(self.temp.name, "jobs", "job-2", "state.json")
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as stream:
            json.dump({"sessionId": job_id}, stream)
        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        row = self._session_row(job_id)
        self.assertEqual(row["kind"], "job")
        self.assertEqual(row["parent_session_id"], primary_id)
        self.assertEqual(row["link_source"], "inferred")
        self.assertEqual(row["relation_confidence"], "high")

    # -- meta_json / jsonl_rel_path -------------------------------------------

    def test_meta_json_folds_agent_fields_without_paths(self):
        row = self._session_row(self.indexer_id)
        payload = json.loads(row["meta_json"])
        self.assertEqual(payload, {
            "type": "indexer", "name": "indexer",
            "description": "成员 indexer", "color": "#3366ff",
        })
        # invariant 7.8: member cwd and any path never enter meta_json
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn(self.cwd, serialized)
        self.assertNotIn("\\", serialized)
        self.assertNotIn("/", serialized)
        # the old agent_* columns keep mirroring the folded payload
        self.assertEqual(row["agent_type"], payload["type"])
        self.assertEqual(row["agent_name"], payload["name"])
        self.assertEqual(row["agent_description"], payload["description"])
        self.assertEqual(row["agent_color"], payload["color"])
        # non-teammate rows keep an empty payload
        self.assertEqual(self._session_row(self.lead_id)["meta_json"], "")

    def test_jsonl_rel_path_is_relative_and_stays_internal(self):
        conn = v2_index.connect(self.db)
        try:
            rows = conn.execute("SELECT id, jsonl_rel_path FROM sessions").fetchall()
        finally:
            conn.close()
        by_id = {row["id"]: row["jsonl_rel_path"] for row in rows}
        self.assertEqual(
            by_id[self.lead_id], "projects/" + self.record_id + "/" + self.lead_id + ".jsonl"
        )
        self.assertEqual(
            by_id[self.helper_id],
            "projects/{}/{}/subagents/agent-{}.jsonl".format(
                self.record_id, self.lead_id, self.helper_agent
            ),
        )
        for path in by_id.values():
            self.assertTrue(path.startswith("projects/"), path)
            self.assertNotIn("\\", path)
            self.assertFalse(os.path.isabs(path), path)
        # invariant 7.3: responses never leak the physical columns
        data = v2_index.list_sessions(self.db, kind="all")
        for item in data["items"]:
            self.assertNotIn("jsonl_rel_path", item)
            self.assertNotIn("file_path", item)
            self.assertNotIn("record_project_id", item)

    def test_meta_only_change_updates_meta_json_and_kind_without_reread(self):
        meta_path = os.path.join(
            self.record_dir, self.lead_id, "subagents",
            "agent-" + self.indexer_agent + ".meta.json",
        )
        with open(meta_path, "r", encoding="utf-8") as stream:
            meta = json.load(stream)
        meta["agentType"] = "renamed-indexer"
        meta["color"] = "#ff0000"
        with open(meta_path, "w", encoding="utf-8") as stream:
            json.dump(meta, stream, ensure_ascii=False)
        guarded_reader = mock.Mock(side_effect=AssertionError("unchanged JSONL must not be parsed again"))
        stats = v2_index.scan_incremental(self.db, self.projects, guarded_reader, fix_text)
        self.assertEqual(stats["indexed"], 0)
        guarded_reader.assert_not_called()
        row = self._session_row(self.indexer_id)
        self.assertEqual(row["kind"], "teammate")
        self.assertEqual(row["link_source"], "meta")
        payload = json.loads(row["meta_json"])
        self.assertEqual(payload["type"], "renamed-indexer")
        self.assertEqual(payload["color"], "#ff0000")
        self.assertEqual(row["agent_type"], "renamed-indexer")
        # removing the sidecar flips the tree to the config branch; the
        # display fields are then backfilled from the roster member row
        os.remove(meta_path)
        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        row = self._session_row(self.indexer_id)
        self.assertEqual(row["kind"], "teammate")
        self.assertEqual(row["link_source"], "config")
        payload = json.loads(row["meta_json"])
        self.assertEqual(payload, {
            "type": "indexer", "name": "indexer", "description": "", "color": "#3366ff",
        })
        self.assertNotIn(self.cwd, json.dumps(payload, ensure_ascii=False))

    # -- list_sessions contract (§4.1 / §4.2) ---------------------------------

    def test_list_sessions_item_matches_contract_fields(self):
        data = v2_index.list_sessions(self.db, kind="all")
        indexer = next(item for item in data["items"] if item["id"] == self.indexer_id)
        required = {
            "id", "kind", "project_id", "project_name", "title", "cwd", "first_ts",
            "last_ts", "total_msgs", "total_tokens", "parent_session_id", "parent_title",
            "team_id", "team_name", "agent", "link_source", "jsonl_available",
            "descendant_count",
        }
        self.assertTrue(required <= set(indexer), required - set(indexer))
        self.assertEqual(indexer["project_id"], self.logical_id)
        self.assertEqual(indexer["kind"], "teammate")
        self.assertEqual(indexer["team_name"], self.team_name)
        self.assertEqual(indexer["agent"], {
            "type": "indexer", "name": "indexer",
            "description": "成员 indexer", "color": "#3366ff",
        })
        self.assertEqual(indexer["link_source"], "meta")
        self.assertEqual(indexer["parent_title"], "主会话标题")
        self.assertEqual(indexer["first_ts"], indexer["created_at"])
        self.assertEqual(indexer["last_ts"], indexer["last_active"])
        self.assertTrue(indexer["jsonl_available"])

    def test_items_carry_descendant_count_for_cascade_confirm(self):
        # E1: every row exposes its descendant count (invariant #7)
        data = v2_index.list_sessions(self.db, kind="all")
        by_id = {item["id"]: item for item in data["items"]}
        self.assertEqual(by_id[self.lead_id]["descendant_count"], 4)
        self.assertEqual(by_id[self.helper_id]["descendant_count"], 0)
        self.assertEqual(by_id[self.indexer_id]["descendant_count"], 0)
        self.assertEqual(by_id[self.job_id]["descendant_count"], 0)
        self.assertTrue(all(isinstance(item["descendant_count"], int) for item in data["items"]))

    def test_descendant_counts_isolate_same_id_across_records(self):
        # P2-2: a cloned session id in two record dirs must keep its own
        # descendant count instead of merging with the other clone's.
        shared_id = "cccccccc-dddd-eeee-ffff-cccccccccccc"
        for record_id, child_count, title in (
            ("D--CloneA", 2, "克隆甲"),
            ("D--CloneB", 1, "克隆乙"),
        ):
            record_dir = os.path.join(self.projects, record_id)
            self._write_jsonl(os.path.join(record_dir, shared_id + ".jsonl"), [
                {
                    "type": "user", "uuid": shared_id, "timestamp": 1700000000000,
                    "cwd": self.cwd, "entrypoint": "cli",
                    "message": {"role": "user", "content": title},
                },
                {"type": "ai-title", "aiTitle": title},
            ])
            base = os.path.join(record_dir, shared_id, "subagents")
            for idx in range(child_count):
                agent_id = "ahelper-{:016x}".format(idx)
                self._write_jsonl(os.path.join(base, "agent-" + agent_id + ".jsonl"), [
                    {
                        "type": "user", "uuid": "u-{}-{}".format(record_id[-1], idx),
                        "timestamp": 1700000004000, "cwd": self.cwd,
                        "agentId": agent_id,
                        "message": {"role": "user", "content": "克隆子代理指令"},
                    },
                ])
        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        data = v2_index.list_sessions(self.db, kind="primary")
        clones = [item for item in data["items"] if item["id"] == shared_id]
        self.assertEqual(len(clones), 2)
        by_title = {item["title"]: item["descendant_count"] for item in clones}
        self.assertEqual(by_title, {"克隆甲": 2, "克隆乙": 1})

    def test_jsonl_available_flips_false_after_file_removal(self):
        os.remove(os.path.join(
            self.record_dir, self.lead_id, "subagents",
            "agent-" + self.helper_agent + ".jsonl",
        ))
        data = v2_index.list_sessions(self.db, kind="all")
        helper = next(item for item in data["items"] if item["id"] == self.helper_id)
        self.assertFalse(helper["jsonl_available"])
        lead = next(item for item in data["items"] if item["id"] == self.lead_id)
        self.assertTrue(lead["jsonl_available"])

    def test_list_sessions_by_kind_facet_counts_every_branch(self):
        data = v2_index.list_sessions(self.db, kind="all")
        self.assertEqual(
            data["by_kind"],
            {"primary": 1, "job": 1, "sdk": 1, "subagent": 1, "teammate": 3},
        )

    def test_scope_project_filters_to_one_logical_project(self):
        data = v2_index.list_sessions(self.db, kind="all", scope="project:" + self.logical_id)
        self.assertEqual(data["total"], 7)
        self.assertEqual(data["by_kind"]["teammate"], 3)
        wrong = v2_index.list_sessions(self.db, kind="all", scope="project:cwd-0000000000000000")
        self.assertEqual(wrong["total"], 0)

    def test_scope_team_filters_by_team_membership(self):
        data = v2_index.list_sessions(self.db, kind="all", scope="team:" + self.team_id)
        self.assertEqual(data["total"], 4)
        self.assertEqual(data["by_kind"], {
            "primary": 1, "job": 0, "sdk": 0, "subagent": 0, "teammate": 3,
        })
        ids = {item["id"] for item in data["items"]}
        self.assertEqual(
            ids,
            {self.lead_id, self.indexer_id, self.planner_id, self.researcher_id},
        )

    def test_scope_parent_lists_direct_children_only(self):
        data = v2_index.list_sessions(self.db, kind="all", scope="parent:" + self.lead_id)
        self.assertEqual(data["total"], 4)
        ids = {item["id"] for item in data["items"]}
        self.assertEqual(
            ids,
            {self.helper_id, self.indexer_id, self.planner_id, self.researcher_id},
        )
        self.assertEqual(data["by_kind"], {
            "primary": 0, "job": 0, "sdk": 0, "subagent": 1, "teammate": 3,
        })

    def test_automatic_preset_sums_the_four_non_primary_kinds(self):
        data = v2_index.list_sessions(self.db, kind="automatic")
        self.assertEqual(data["kind"], "automatic")
        self.assertEqual(data["total"], 6)
        kinds = {item["kind"] for item in data["items"]}
        self.assertEqual(kinds, {"job", "sdk", "subagent", "teammate"})
        self.assertNotIn("primary", kinds)

    def test_aliases_derive_from_the_same_facet(self):
        data = v2_index.list_sessions(self.db, kind="all", scope="project:" + self.logical_id)
        self.assertEqual(data["primary_total"], data["by_kind"]["primary"])
        self.assertEqual(data["teammate_total"], data["by_kind"]["teammate"])
        expected_automatic = 1 + 1 + 1 + 3
        self.assertEqual(data["automatic_total"], expected_automatic)
        self.assertEqual(data["automatic_all_total"], expected_automatic)
        self.assertEqual(data["related_total"], 4)  # nested sessions in scope
        for item in data["items"]:
            self.assertEqual(item["session_kind"], item["kind"])

    def test_all_kind_values_accepted_and_unknown_falls_back_to_all(self):
        for kind, expected in (
            ("all", 7), ("primary", 1), ("job", 1), ("sdk", 1),
            ("subagent", 1), ("teammate", 3), ("automatic", 6),
        ):
            data = v2_index.list_sessions(self.db, kind=kind)
            self.assertEqual(data["kind"], kind)
            self.assertEqual(data["total"], expected)
        data = v2_index.list_sessions(self.db, kind="bogus")
        self.assertEqual(data["kind"], "all")
        self.assertEqual(data["total"], 7)

    def test_teammate_filter_reads_kind_column_not_task_kind(self):
        conn = v2_index.connect(self.db)
        try:
            conn.execute("UPDATE sessions SET task_kind = '' WHERE id = ?", (self.planner_id,))
            conn.commit()
        finally:
            conn.close()
        data = v2_index.list_sessions(self.db, kind="teammate")
        self.assertEqual(data["total"], 3)
        self.assertIn(self.planner_id, {item["id"] for item in data["items"]})

    # -- session_detail slim contract (§4.3) ----------------------------------

    def test_session_detail_slim_contract_descendant_count_and_no_children(self):
        detail = v2_index.session_detail(self.db, self.logical_id, self.lead_id)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["session"]["descendant_count"], 4)
        self.assertNotIn("children", detail["session"])
        self.assertIsNone(detail["session"]["parent"])
        self.assertEqual(detail["session"]["kind"], "primary")

        helper = v2_index.session_detail(self.db, self.logical_id, self.helper_id)
        self.assertEqual(helper["session"]["descendant_count"], 0)
        self.assertNotIn("children", helper["session"])
        self.assertEqual(helper["session"]["parent"]["id"], self.lead_id)
        self.assertEqual(helper["session"]["kind"], "subagent")

    # -- orphan restore guarantee (C3) ----------------------------------------

    def test_orphan_restore_reorphan_and_explicit_removal(self):
        orphan_id = "dddddddd-dddd-dddd-dddd-dddddddddddd"
        history_path = os.path.join(self.temp.name, "history.jsonl")
        with open(history_path, "w", encoding="utf-8") as stream:
            stream.write(json.dumps({
                "sessionId": orphan_id,
                "project": self.cwd,
                "timestamp": 1700000000000,
                "display": "请检查并完成这个项目中的关键功能",
            }, ensure_ascii=False) + "\n")
        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        self.assertEqual(v2_index.list_orphan_history_sessions(self.db)["total"], 1)

        # Indexing the transcript restores it: the orphan listing drops the
        # record but its history row survives for a later re-orphan (C3).
        self._write_top("找回的任务", orphan_id)
        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        self.assertEqual(v2_index.list_orphan_history_sessions(self.db)["total"], 0)
        conn = v2_index.connect(self.db)
        try:
            kept = conn.execute(
                "SELECT is_orphan FROM orphan_history_sessions WHERE session_id = ?",
                (orphan_id,),
            ).fetchone()
            self.assertIsNotNone(kept)
            self.assertEqual(kept["is_orphan"], 0)
        finally:
            conn.close()

        # Removing the transcript orphans it again without a history re-read.
        os.remove(os.path.join(self.record_dir, orphan_id + ".jsonl"))
        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        self.assertEqual(v2_index.list_orphan_history_sessions(self.db)["total"], 1)

        # Only the explicit removal deletes the record, and only while the
        # session is not indexed (C3).
        removed = v2_index.remove_orphan_history_sessions(self.db, [orphan_id])
        self.assertEqual(removed, 1)
        self.assertEqual(v2_index.list_orphan_history_sessions(self.db)["total"], 0)
        conn = v2_index.connect(self.db)
        try:
            gone = conn.execute(
                "SELECT 1 FROM orphan_history_sessions WHERE session_id = ?", (orphan_id,)
            ).fetchone()
            self.assertIsNone(gone)
            tomb = conn.execute(
                "SELECT removed_at FROM orphan_tombstones WHERE session_id = ?", (orphan_id,)
            ).fetchone()
            self.assertIsNotNone(tomb)
            self.assertNotEqual(tomb["removed_at"], "")
        finally:
            conn.close()
        # A re-scan with no history change must not resurrect the record.
        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        self.assertEqual(v2_index.list_orphan_history_sessions(self.db)["total"], 0)

        # Tombstone (P1): a changed history.jsonl forces a full rebuild, but
        # the explicitly removed record must not resurrect, while untouched
        # records keep their normal orphan cycle.
        second_id = "99999999-9999-9999-9999-999999999999"
        with open(history_path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps({
                "sessionId": second_id,
                "project": self.cwd,
                "timestamp": 1700000005000,
                "display": "第二条历史记录对应的任务",
            }, ensure_ascii=False) + "\n")
        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        self.assertEqual(v2_index.list_orphan_history_sessions(self.db)["total"], 1)
        items = v2_index.list_orphan_history_sessions(self.db)["items"]
        self.assertEqual([item["session_id"] for item in items], [second_id])
        # idempotent removal: nothing left to delete, tombstone stays
        again = v2_index.remove_orphan_history_sessions(self.db, [orphan_id])
        self.assertEqual(again, 0)
        self.assertEqual(v2_index.list_orphan_history_sessions(self.db)["total"], 1)
        # the untouched record still restores when its transcript is indexed
        self._write_top("第二条找回的任务", second_id)
        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        self.assertEqual(v2_index.list_orphan_history_sessions(self.db)["total"], 0)
        os.remove(os.path.join(self.record_dir, second_id + ".jsonl"))
        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        self.assertEqual(v2_index.list_orphan_history_sessions(self.db)["total"], 1)

    # -- facet-derived stats (§3.4) -------------------------------------------

    def test_dashboard_and_project_cards_expose_kind_facet(self):
        expected = {"primary": 1, "job": 1, "sdk": 1, "subagent": 1, "teammate": 3}
        stats = v2_index.dashboard(self.db)["stats"]
        self.assertEqual(stats["by_kind"], expected)
        self.assertEqual(stats["total_sessions"], 1)
        self.assertEqual(stats["total_automatic_sessions"], 6)
        self.assertEqual(stats["total_all_sessions"], 7)
        projects = v2_index.list_projects(self.db)["items"]
        self.assertEqual(len(projects), 1)
        project = projects[0]
        self.assertEqual(project["by_kind"], expected)
        self.assertEqual(project["automatic_session_count"], 6)
        self.assertEqual(project["all_session_count"], 7)

    def test_team_roles_and_team_facet(self):
        detail = v2_index.team_detail(self.db, self.team_id)
        roles = {member["agent_id"]: member["role"] for member in detail["members"]}
        self.assertEqual(roles, {
            "team-lead@lead-1": "lead",
            "indexer@member-1": "member",
            "planner@member-2": "member",
        })
        expected = {"primary": 1, "job": 0, "sdk": 0, "subagent": 0, "teammate": 3}
        self.assertEqual(detail["team"]["by_kind"], expected)
        teams = v2_index.list_teams(self.db)
        self.assertEqual(teams["items"][0]["by_kind"], expected)


if __name__ == "__main__":
    unittest.main()
