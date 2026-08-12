import json
import os
import shutil
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


class TeamIndexTests(unittest.TestCase):
    """Cover Agent team indexing: configs, member sessions, cascade and queries."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.projects = os.path.join(self.temp.name, "projects")
        self.teams = os.path.join(self.temp.name, "teams")
        self.record_id = "D--TeamRecord"
        self.record_dir = os.path.join(self.projects, self.record_id)
        os.makedirs(self.record_dir)
        self.cwd = os.path.join(self.temp.name, "team-project")
        os.makedirs(self.cwd)
        self.db = os.path.join(self.temp.name, "index.sqlite3")
        self.lead_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        self.member_hex = "a1b2c3d4e5f60718"
        self.member_agent_id = "aindexer-" + self.member_hex
        self._write_lead_session(self.lead_uuid, "组织团队任务", "team-lead@lead-1")
        self._write_member("indexer", self.member_hex, "demo-team", self.cwd)
        self._write_team_config("demo-team", name="Demo Team", members=[
            {"agentId": "team-lead@lead-1", "name": "team-lead",
             "joinedAt": "2026-08-01T09:00:00", "cwd": self.cwd},
            {"agentId": "indexer@member-1", "name": "indexer",
             "joinedAt": "2026-08-01T09:01:00", "cwd": self.cwd,
             "color": "#00aa00", "agentType": "indexer"},
        ])
        self.first_stats = v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)

    def tearDown(self):
        self.temp.cleanup()

    def _write_lead_session(self, lead_uuid, title, agent_id, record_dir=None):
        record_dir = record_dir or self.record_dir
        path = os.path.join(record_dir, lead_uuid + ".jsonl")
        with open(path, "w", encoding="utf-8") as stream:
            for entry in [
                {
                    "type": "user", "uuid": "u-" + lead_uuid, "timestamp": 1700000000000,
                    "cwd": self.cwd, "entrypoint": "cli", "agentId": agent_id,
                    "message": {"role": "user", "content": title},
                },
                {"type": "ai-title", "aiTitle": title},
            ]:
                stream.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _write_member(self, name, hex_part, team_name, cwd, lead_uuid=None, record_dir=None):
        lead_uuid = lead_uuid or self.lead_uuid
        record_dir = record_dir or self.record_dir
        agent_id = "a" + name + "-" + hex_part
        base = os.path.join(record_dir, lead_uuid, "subagents")
        os.makedirs(base, exist_ok=True)
        log_path = os.path.join(base, "agent-" + agent_id + ".jsonl")
        with open(log_path, "w", encoding="utf-8") as stream:
            for entry in [
                {
                    "type": "user", "uuid": "u-" + name + "-1", "timestamp": 1700000004000,
                    "cwd": cwd, "isSidechain": True, "agentId": agent_id,
                    "sessionId": lead_uuid,
                    "message": {"role": "user", "content": [
                        {"type": "text", "text": "请处理团队成员任务"},
                    ]},
                },
                {
                    "type": "assistant", "timestamp": 1700000005000, "cwd": cwd,
                    "isSidechain": True, "sessionId": lead_uuid,
                    "message": {"role": "assistant", "model": "deepseek-v4-pro",
                                "content": [{"type": "text", "text": "处理完成"}],
                                "usage": {"input_tokens": 50, "output_tokens": 10}},
                },
            ]:
                stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
        meta_path = log_path[:-6] + ".meta.json"
        with open(meta_path, "w", encoding="utf-8") as stream:
            json.dump({
                "agentType": name, "name": name, "description": "成员 " + name,
                "color": "#3366ff", "taskKind": "in_process_teammate",
                "teamName": team_name, "model": "deepseek-v4-pro",
            }, stream)
        return log_path, meta_path

    def _write_team_config(self, team_id, name="Team", members=None, lead_session_id=None,
                           lead_agent_id="team-lead@lead-1"):
        team_dir = os.path.join(self.teams, team_id)
        os.makedirs(team_dir, exist_ok=True)
        config = {
            "name": name,
            "createdAt": 1700000000000,
            "leadAgentId": lead_agent_id,
            "leadSessionId": lead_session_id or self.lead_uuid,
            "members": members or [],
        }
        path = os.path.join(team_dir, "config.json")
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(config, stream, ensure_ascii=False)
        return path

    def _member(self, team_id, name):
        return next(
            member for member in v2_index.team_detail(self.db, team_id)["members"]
            if member["name"] == name
        )

    def test_first_scan_builds_teams_members_and_session_columns(self):
        self.assertEqual(self.first_stats["indexed"], 2)
        teams = v2_index.list_teams(self.db)
        self.assertEqual(teams["total"], 1)
        team = teams["items"][0]
        self.assertEqual(team["id"], "demo-team")
        self.assertEqual(team["name"], "Demo Team")
        # privacy: config member cwd is display-only, never persisted; the
        # listing derives a display cwd from the indexed lead session
        self.assertEqual(team["cwd"], self.cwd)
        conn = v2_index.connect(self.db)
        try:
            stored = conn.execute("SELECT cwd FROM teams WHERE id = 'demo-team'").fetchone()
            self.assertEqual(stored["cwd"], "")
        finally:
            conn.close()
        self.assertEqual(team["lead_agent_id"], "team-lead@lead-1")
        self.assertEqual(team["lead_session_id"], self.lead_uuid)
        self.assertNotEqual(team["created_at"], "")
        self.assertEqual(team["config_error"], 0)
        # aggregates: lead (1 msg, 0 tokens) + indexer (2 msgs, 60 tokens)
        self.assertEqual(team["member_count"], 2)
        self.assertEqual(team["session_count"], 2)
        self.assertEqual(team["total_msgs"], 3)
        self.assertEqual(team["total_tokens"], 60)

        detail = v2_index.team_detail(self.db, "demo-team")
        self.assertEqual(detail["lead"]["agent_id"], "team-lead@lead-1")
        # display-only cwd derived from the indexed lead session, not the config
        self.assertEqual(detail["team"]["cwd"], self.cwd)
        lead_session = detail["lead"]["session"]
        self.assertIsNotNone(lead_session)
        self.assertEqual(lead_session["id"], self.lead_uuid)
        self.assertEqual(lead_session["team_id"], "demo-team")
        self.assertEqual(lead_session["team_confidence"], "lead_session")

        members = {member["name"]: member for member in detail["members"]}
        self.assertIn("indexer", members)
        self.assertIn("team-lead", members)
        indexer = members["indexer"]
        self.assertEqual(indexer["agent_id"], "indexer@member-1")
        self.assertEqual(indexer["agent_type"], "indexer")
        self.assertEqual(indexer["color"], "#00aa00")
        self.assertEqual(indexer["confidence"], "meta_scope")
        self.assertIsNotNone(indexer["session"])
        self.assertEqual(indexer["session"]["agent_id"], self.member_agent_id)
        self.assertEqual(indexer["session"]["team_id"], "demo-team")
        self.assertEqual(indexer["session"]["team_confidence"], "meta_scope")
        self.assertEqual(indexer["session"]["task_kind"], "in_process_teammate")
        self.assertEqual(indexer["session"]["session_kind"], "subagent")
        self.assertEqual(indexer["record_project_id"], self.record_id)
        self.assertEqual(indexer["logical_project_id"], self.record_id)
        # the lead member row links to the lead session via exact agent match,
        # but the lead session itself is not marked as a teammate
        self.assertEqual(members["team-lead"]["session"]["id"], self.lead_uuid)
        self.assertEqual(members["team-lead"]["confidence"], "exact")
        self.assertEqual(members["team-lead"]["session"]["task_kind"], "")

        # dashboard counts teams; search exposes kind and team name
        self.assertEqual(v2_index.dashboard(self.db)["stats"]["total_teams"], 1)
        session_rows = [row for row in v2_index.search(self.db, "团队成员任务")["items"]
                        if row["type"] == "session" and row["session_kind"] == "subagent"]
        self.assertEqual(len(session_rows), 1)
        self.assertEqual(session_rows[0]["task_kind"], "in_process_teammate")
        self.assertEqual(session_rows[0]["team_name"], "Demo Team")

    def test_unchanged_refresh_reuses_file_index(self):
        guarded_reader = mock.Mock(side_effect=AssertionError("unchanged JSONL must not be parsed again"))
        stats = v2_index.scan_incremental(self.db, self.projects, guarded_reader, fix_text)
        self.assertEqual(stats["indexed"], 0)
        self.assertEqual(stats["sessions"], 2)
        guarded_reader.assert_not_called()
        self.assertEqual(v2_index.list_teams(self.db)["total"], 1)

    def test_config_only_change_updates_teams_without_reindexing(self):
        config_path = os.path.join(self.teams, "demo-team", "config.json")
        with open(config_path, "r", encoding="utf-8") as stream:
            config = json.load(stream)
        config["members"].append({
            "agentId": "helper@member-2", "name": "helper",
            "joinedAt": "2026-08-02T09:00:00", "cwd": self.cwd,
        })
        with open(config_path, "w", encoding="utf-8") as stream:
            json.dump(config, stream)
        stats = v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        self.assertEqual(stats["indexed"], 0)
        team = v2_index.list_teams(self.db)["items"][0]
        self.assertEqual(team["member_count"], 3)
        self.assertEqual(len(v2_index.team_detail(self.db, "demo-team")["members"]), 3)

    def test_lead_log_removal_keeps_member_team_but_drops_parent(self):
        os.remove(os.path.join(self.record_dir, self.lead_uuid + ".jsonl"))
        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        detail = v2_index.team_detail(self.db, "demo-team")
        self.assertIsNone(detail["lead"]["session"])
        indexer = self._member("demo-team", "indexer")
        self.assertIsNotNone(indexer["session"])
        self.assertEqual(indexer["session"]["team_id"], "demo-team")
        self.assertEqual(indexer["session"]["parent_session_id"], "")

    def test_member_without_log_has_no_session(self):
        self._write_team_config("ghost-team", name="Ghost Team", members=[
            {"agentId": "team-lead@lead-2", "name": "team-lead",
             "joinedAt": "2026-08-01T09:00:00", "cwd": self.cwd},
            {"agentId": "ghost@member-3", "name": "ghost",
             "joinedAt": "2026-08-01T09:01:00", "cwd": self.cwd},
        ], lead_session_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            lead_agent_id="team-lead@lead-2")
        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        detail = v2_index.team_detail(self.db, "ghost-team")
        self.assertIsNotNone(detail)
        self.assertIsNone(detail["lead"]["session"])
        ghost = self._member("ghost-team", "ghost")
        self.assertIsNone(ghost["session"])
        self.assertEqual(ghost["logical_project_id"], "")
        self.assertEqual(ghost["record_project_id"], "")

    def test_member_log_removal_drops_session_and_team_count(self):
        log_path = os.path.join(
            self.record_dir, self.lead_uuid, "subagents",
            "agent-" + self.member_agent_id + ".jsonl",
        )
        os.remove(log_path)
        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        team = v2_index.list_teams(self.db)["items"][0]
        self.assertEqual(team["session_count"], 1)
        self.assertIsNone(self._member("demo-team", "indexer")["session"])

    def test_team_dir_removal_clears_teams_and_session_links(self):
        shutil.rmtree(os.path.join(self.teams, "demo-team"))
        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        self.assertEqual(v2_index.list_teams(self.db)["total"], 0)
        conn = v2_index.connect(self.db)
        try:
            rows = conn.execute(
                "SELECT id, team_id, team_confidence FROM sessions WHERE team_id != ''"
            ).fetchall()
            self.assertEqual(len(rows), 0)
        finally:
            conn.close()

    def test_team_name_scope_isolates_same_named_members(self):
        lead_a = "11111111-1111-1111-1111-111111111111"
        lead_b = "22222222-2222-2222-2222-222222222222"
        self._write_lead_session(lead_a, "团队 A 的任务", "team-lead@a")
        self._write_lead_session(lead_b, "团队 B 的任务", "team-lead@b")
        self._write_member("indexer", "aaaa0000aaaa0001", "team-a", self.cwd, lead_uuid=lead_a)
        self._write_member("indexer", "bbbb0000bbbb0002", "team-b", self.cwd, lead_uuid=lead_b)
        self._write_team_config("team-a", name="Team A", members=[
            {"agentId": "team-lead@a", "name": "team-lead",
             "joinedAt": "2026-08-01T09:00:00", "cwd": self.cwd},
            {"agentId": "indexer@a", "name": "indexer",
             "joinedAt": "2026-08-01T09:01:00", "cwd": self.cwd},
        ], lead_session_id=lead_a, lead_agent_id="team-lead@a")
        self._write_team_config("team-b", name="Team B", members=[
            {"agentId": "team-lead@b", "name": "team-lead",
             "joinedAt": "2026-08-01T09:00:00", "cwd": self.cwd},
            {"agentId": "indexer@b", "name": "indexer",
             "joinedAt": "2026-08-01T09:01:00", "cwd": self.cwd},
        ], lead_session_id=lead_b, lead_agent_id="team-lead@b")
        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)

        indexer_a = self._member("team-a", "indexer")
        indexer_b = self._member("team-b", "indexer")
        self.assertIsNotNone(indexer_a["session"])
        self.assertIsNotNone(indexer_b["session"])
        self.assertNotEqual(indexer_a["session"]["id"], indexer_b["session"]["id"])
        self.assertEqual(indexer_a["session"]["team_id"], "team-a")
        self.assertEqual(indexer_b["session"]["team_id"], "team-b")
        self.assertEqual(indexer_a["agent_id"], "indexer@a")
        self.assertEqual(indexer_b["agent_id"], "indexer@b")

    def test_lead_dir_links_meta_less_member_but_not_unrelated_subagents(self):
        # replace the member log with one that has no .meta.json
        original = os.path.join(
            self.record_dir, self.lead_uuid, "subagents",
            "agent-" + self.member_agent_id + ".jsonl",
        )
        os.remove(original)
        os.remove(original[:-6] + ".meta.json")
        base = os.path.dirname(original)
        new_agent = "aindexer-9f8e7d6c5b4a3210"
        with open(os.path.join(base, "agent-" + new_agent + ".jsonl"), "w", encoding="utf-8") as stream:
            for entry in [
                {
                    "type": "user", "uuid": "u-meta-less-1", "timestamp": 1700000004000,
                    "cwd": self.cwd, "isSidechain": True, "agentId": new_agent,
                    "sessionId": self.lead_uuid,
                    "message": {"role": "user", "content": "无 meta 的成员任务"},
                },
            ]:
                stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
        # an unrelated regular subagent under the lead dir must not join the team
        with open(os.path.join(base, "agent-ahelper-0011223344556677.jsonl"), "w", encoding="utf-8") as stream:
            for entry in [
                {
                    "type": "user", "uuid": "u-helper-1", "timestamp": 1700000004000,
                    "cwd": self.cwd, "agentId": "ahelper-0011223344556677",
                    "message": {"role": "user", "content": "普通子代理任务"},
                },
            ]:
                stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)

        indexer = self._member("demo-team", "indexer")
        self.assertIsNotNone(indexer["session"])
        self.assertEqual(indexer["session"]["agent_id"], new_agent)
        self.assertEqual(indexer["session"]["team_id"], "demo-team")
        self.assertEqual(indexer["session"]["team_confidence"], "lead_dir")
        self.assertEqual(indexer["confidence"], "lead_dir")
        # member-level links backfill task_kind, so the meta-less member shows
        # up in teammate listings while the unrelated helper stays out
        self.assertEqual(indexer["session"]["task_kind"], "in_process_teammate")
        teammates = v2_index.list_sessions(self.db, kind="teammate")
        self.assertEqual(teammates["total"], 1)
        self.assertEqual(teammates["items"][0]["agent_id"], new_agent)
        self.assertEqual(teammates["items"][0]["task_kind"], "in_process_teammate")
        self.assertEqual(teammates["items"][0]["team_name"], "Demo Team")

        # team stats cover lead + member only; the helper subagent is excluded
        team = v2_index.list_teams(self.db)["items"][0]
        self.assertEqual(team["session_count"], 2)
        conn = v2_index.connect(self.db)
        try:
            helper = conn.execute(
                "SELECT team_id, team_confidence FROM sessions WHERE agent_id = ?",
                ("ahelper-0011223344556677",),
            ).fetchone()
            self.assertIsNotNone(helper)
            self.assertEqual(helper["team_id"], "")
            self.assertEqual(helper["team_confidence"], "")
        finally:
            conn.close()

    def test_stale_lead_session_is_not_tagged_as_teammate(self):
        lead_new = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
        self._write_lead_session(lead_new, "第二次团队任务", "team-lead@lead-1")
        config_path = os.path.join(self.teams, "demo-team", "config.json")
        with open(config_path, "r", encoding="utf-8") as stream:
            config = json.load(stream)
        config["leadSessionId"] = lead_new
        with open(config_path, "w", encoding="utf-8") as stream:
            json.dump(config, stream)
        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)

        conn = v2_index.connect(self.db)
        try:
            old_lead = conn.execute(
                "SELECT task_kind, team_id, team_confidence FROM sessions WHERE id = ?",
                (self.lead_uuid,),
            ).fetchone()
            self.assertIsNotNone(old_lead)
            self.assertEqual(old_lead["task_kind"], "")
            self.assertEqual(old_lead["team_id"], "")
            self.assertEqual(old_lead["team_confidence"], "")
            new_lead = conn.execute(
                "SELECT task_kind, team_id, team_confidence FROM sessions WHERE id = ?",
                (lead_new,),
            ).fetchone()
            self.assertEqual(new_lead["team_id"], "demo-team")
            self.assertEqual(new_lead["team_confidence"], "lead_session")
            self.assertEqual(new_lead["task_kind"], "")
        finally:
            conn.close()

        teammates = v2_index.list_sessions(self.db, kind="teammate")
        self.assertEqual(teammates["total"], 1)
        self.assertNotIn(self.lead_uuid, [row["id"] for row in teammates["items"]])

        detail = v2_index.team_detail(self.db, "demo-team")
        self.assertEqual(detail["lead"]["session"]["id"], lead_new)
        lead_member = next(member for member in detail["members"] if member["name"] == "team-lead")
        self.assertEqual(lead_member["session"]["id"], lead_new)

    def test_meta_only_change_updates_member_columns_without_rereading_log(self):
        meta_path = os.path.join(
            self.record_dir, self.lead_uuid, "subagents",
            "agent-" + self.member_agent_id + ".meta.json",
        )
        with open(meta_path, "r", encoding="utf-8") as stream:
            meta = json.load(stream)
        meta["agentType"] = "renamed-indexer"
        meta["color"] = "#ff0000"
        with open(meta_path, "w", encoding="utf-8") as stream:
            json.dump(meta, stream)
        guarded_reader = mock.Mock(side_effect=AssertionError("unchanged JSONL must not be parsed again"))
        stats = v2_index.scan_incremental(self.db, self.projects, guarded_reader, fix_text)
        self.assertEqual(stats["indexed"], 0)
        guarded_reader.assert_not_called()
        indexer = self._member("demo-team", "indexer")
        self.assertIsNotNone(indexer["session"])
        self.assertEqual(indexer["session"]["agent_type"], "renamed-indexer")
        self.assertEqual(indexer["session"]["agent_color"], "#ff0000")
        self.assertEqual(indexer["session"]["team_id"], "demo-team")
        self.assertEqual(indexer["session"]["task_kind"], "in_process_teammate")

    def test_exact_claimed_primary_detaches_when_member_leaves(self):
        # a member's own main session carrying the config agent id is claimed
        # via the exact level, then must detach when the member leaves
        primary_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        path = os.path.join(self.record_dir, primary_id + ".jsonl")
        with open(path, "w", encoding="utf-8") as stream:
            for entry in [
                {
                    "type": "user", "uuid": "u-main-1", "timestamp": 1700000000000,
                    "cwd": self.cwd, "entrypoint": "cli", "agentId": "indexer@member-1",
                    "message": {"role": "user", "content": "成员主会话"},
                },
                {"type": "ai-title", "aiTitle": "成员主会话"},
            ]:
                stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        conn = v2_index.connect(self.db)
        try:
            row = conn.execute(
                "SELECT task_kind, team_id, team_confidence FROM sessions WHERE id = ?",
                (primary_id,),
            ).fetchone()
            self.assertEqual(row["team_id"], "demo-team")
            self.assertEqual(row["team_confidence"], "exact")
            self.assertEqual(row["task_kind"], "in_process_teammate")
        finally:
            conn.close()

        config_path = os.path.join(self.teams, "demo-team", "config.json")
        with open(config_path, "r", encoding="utf-8") as stream:
            config = json.load(stream)
        config["members"] = [member for member in config["members"] if member["name"] != "indexer"]
        with open(config_path, "w", encoding="utf-8") as stream:
            json.dump(config, stream)
        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        conn = v2_index.connect(self.db)
        try:
            row = conn.execute(
                "SELECT task_kind, team_id, team_confidence FROM sessions WHERE id = ?",
                (primary_id,),
            ).fetchone()
            self.assertEqual(row["team_id"], "")
            self.assertEqual(row["task_kind"], "")
            self.assertEqual(row["team_confidence"], "")
        finally:
            conn.close()

    def test_list_teams_pagination_and_query(self):
        self._write_team_config("alpha-team", name="Alpha", members=[], lead_session_id="")
        self._write_team_config("beta-team", name="Beta", members=[], lead_session_id="")
        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        teams = v2_index.list_teams(self.db)
        self.assertEqual(teams["total"], 3)
        page = v2_index.list_teams(self.db, limit=1, offset=1)
        self.assertEqual(len(page["items"]), 1)
        self.assertEqual(page["total"], 3)
        filtered = v2_index.list_teams(self.db, q="demo")
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["items"][0]["id"], "demo-team")

    def test_list_sessions_teammate_kind(self):
        data = v2_index.list_sessions(self.db, kind="teammate")
        self.assertEqual(data["kind"], "teammate")
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["teammate_total"], 1)
        self.assertEqual(data["items"][0]["task_kind"], "in_process_teammate")
        self.assertEqual(data["items"][0]["team_id"], "demo-team")
        self.assertEqual(data["items"][0]["team_name"], "Demo Team")

        all_data = v2_index.list_sessions(self.db, kind="all")
        self.assertEqual(all_data["total"], 2)
        self.assertEqual(all_data["primary_total"], 1)
        self.assertEqual(all_data["automatic_all_total"], 1)
        self.assertEqual(all_data["teammate_total"], 1)
        self.assertEqual({row["session_kind"] for row in all_data["items"]}, {"primary", "subagent"})
        teammate_row = next(
            row for row in all_data["items"] if row["task_kind"] == "in_process_teammate"
        )
        self.assertEqual(teammate_row["team_name"], "Demo Team")

    def test_team_detail_resolves_cross_project_member(self):
        other_record = "D--OtherRecord"
        other_dir = os.path.join(self.projects, other_record)
        other_cwd = os.path.join(self.temp.name, "other-project")
        os.makedirs(other_cwd)
        self._write_member("helper", "c3d4e5f60718a1b2", "demo-team", other_cwd,
                           lead_uuid="cccccccc-cccc-cccc-cccc-cccccccccccc",
                           record_dir=other_dir)
        config_path = os.path.join(self.teams, "demo-team", "config.json")
        with open(config_path, "r", encoding="utf-8") as stream:
            config = json.load(stream)
        config["members"].append({
            "agentId": "helper@member-4", "name": "helper",
            "joinedAt": "2026-08-02T10:00:00", "cwd": other_cwd,
        })
        with open(config_path, "w", encoding="utf-8") as stream:
            json.dump(config, stream)
        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)

        helper = self._member("demo-team", "helper")
        indexer = self._member("demo-team", "indexer")
        self.assertIsNotNone(helper["session"])
        self.assertEqual(helper["record_project_id"], other_record)
        self.assertEqual(helper["logical_project_id"], other_record)
        self.assertNotEqual(helper["session"]["project_id"], indexer["session"]["project_id"])

    def test_malformed_config_marks_error_without_raising_or_deleting(self):
        config_path = os.path.join(self.teams, "demo-team", "config.json")
        with open(config_path, "w", encoding="utf-8") as stream:
            stream.write("{ this is not valid json")
        v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        team = v2_index.list_teams(self.db)["items"][0]
        self.assertEqual(team["id"], "demo-team")
        self.assertEqual(team["config_error"], 1)
        self.assertEqual(team["name"], "Demo Team")
        self.assertEqual(team["member_count"], 2)
        indexer = self._member("demo-team", "indexer")
        self.assertIsNotNone(indexer["session"])

    def test_malformed_config_on_first_scan_creates_error_row(self):
        fresh_db = os.path.join(self.temp.name, "fresh.sqlite3")
        config_path = os.path.join(self.teams, "demo-team", "config.json")
        with open(config_path, "w", encoding="utf-8") as stream:
            stream.write("not json at all")
        stats = v2_index.scan_incremental(fresh_db, self.projects, read_jsonl, fix_text)
        self.assertEqual(stats["indexed"], 2)
        team = v2_index.list_teams(fresh_db)["items"][0]
        self.assertEqual(team["id"], "demo-team")
        self.assertEqual(team["config_error"], 1)
        self.assertEqual(team["member_count"], 0)

    def test_missing_teams_dir_leaves_empty_team_tables(self):
        shutil.rmtree(self.teams)
        stats = v2_index.scan_incremental(self.db, self.projects, read_jsonl, fix_text)
        self.assertEqual(stats["sessions"], 2)
        self.assertEqual(v2_index.list_teams(self.db)["total"], 0)
        conn = v2_index.connect(self.db)
        try:
            count = conn.execute("SELECT COUNT(*) AS c FROM team_members").fetchone()["c"]
            self.assertEqual(count, 0)
            rows = conn.execute(
                "SELECT id FROM sessions WHERE team_id != '' OR task_kind != ''"
            ).fetchall()
            self.assertEqual(len(rows), 0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
