"""App-level tests: agent team endpoints and member-agent sidecar cleanup on trash."""

import io
import json
import os
import tempfile
import unittest
import urllib.parse
from unittest import mock

import app
import v2_index


class FakeHandler(app.Handler):
    """Handler stub that captures JSON responses without a real socket."""

    def __init__(self, body=b"{}"):
        self.headers = {"Content-Length": str(len(body))}
        self.rfile = io.BytesIO(body)
        self.responses = []

    def _send_json(self, data, status=200):
        self.responses.append((status, data))


class TeamApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.projects = os.path.join(self.temp.name, "projects")
        self.record_dir = os.path.join(self.projects, "D--TeamRecord")
        os.makedirs(self.record_dir)
        cwd = os.path.join(self.temp.name, "team-project")
        os.makedirs(cwd)

        self.team_id = "demo-team"
        self.team_name = "Demo Team"
        self.lead_id = "dddddddd-dddd-dddd-dddd-dddddddddddd"
        self.lead_agent_id = "team-lead@lead-1"
        self.member_hex = "a1b2c3d4e5f60718"
        self.member_agent_id = "aindexer-" + self.member_hex
        self.config_member_agent_id = "indexer@member-1"
        self.agent_name = "agent-" + self.member_agent_id
        # The synthetic id is <parent>--<agent file base name>.
        self.subagent_id = self.lead_id + "--" + self.agent_name
        self.lead_path = os.path.join(self.record_dir, self.lead_id + ".jsonl")
        self.subagent_path = os.path.join(
            self.record_dir, self.lead_id, "subagents", self.agent_name + ".jsonl"
        )
        os.makedirs(os.path.dirname(self.subagent_path))
        with open(self.lead_path, "w", encoding="utf-8") as stream:
            stream.write(json.dumps({
                "type": "user", "uuid": "u-" + self.lead_id, "timestamp": 1700000000000,
                "cwd": cwd, "entrypoint": "cli", "agentId": self.lead_agent_id,
                "message": {"role": "user", "content": "lead 任务"},
            }, ensure_ascii=False) + "\n")
        with open(self.subagent_path, "w", encoding="utf-8") as stream:
            for entry in [
                {
                    "type": "user", "uuid": "u-indexer-1", "timestamp": 1700000004000,
                    "cwd": cwd, "isSidechain": True, "agentId": self.member_agent_id,
                    "sessionId": self.lead_id,
                    "message": {"role": "user", "content": "请处理团队成员任务"},
                },
                {
                    "type": "assistant", "timestamp": 1700000005000, "cwd": cwd,
                    "isSidechain": True, "sessionId": self.lead_id,
                    "message": {"role": "assistant", "model": "deepseek-v4-pro",
                                "content": "处理完成",
                                "usage": {"input_tokens": 50, "output_tokens": 10}},
                },
            ]:
                stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
        # Member-agent metadata sidecar, canonical naming (jsonl stripped),
        # same convention as v2_index._read_agent_meta.
        self.subagent_meta_path = self.subagent_path[:-6] + ".meta.json"
        with open(self.subagent_meta_path, "w", encoding="utf-8") as stream:
            json.dump({
                "taskKind": "in_process_teammate",
                "teamName": self.team_id,
                "name": "indexer",
                "agentType": "indexer",
                "color": "#3366ff",
            }, stream, ensure_ascii=False)

        teams_dir = os.path.join(self.temp.name, "teams")
        config_path = os.path.join(teams_dir, self.team_id, "config.json")
        os.makedirs(os.path.dirname(config_path))
        with open(config_path, "w", encoding="utf-8") as stream:
            json.dump({
                "name": self.team_name,
                "leadAgentId": self.lead_agent_id,
                "leadSessionId": self.lead_id,
                "createdAt": 1700000000000,
                "members": [
                    {
                        "agentId": self.lead_agent_id,
                        "name": "team-lead",
                        "joinedAt": "2026-08-01T09:00:00",
                        "cwd": cwd,
                    },
                    {
                        "agentId": self.config_member_agent_id,
                        "name": "indexer",
                        "joinedAt": "2026-08-01T09:01:00",
                        "cwd": cwd,
                        "color": "#3366ff",
                        "agentType": "indexer",
                    },
                ],
            }, stream, ensure_ascii=False)
        # A team with a non-ASCII directory name must be reachable too.
        self.unicode_team_id = "中文团队"
        unicode_config_path = os.path.join(teams_dir, self.unicode_team_id, "config.json")
        os.makedirs(os.path.dirname(unicode_config_path))
        with open(unicode_config_path, "w", encoding="utf-8") as stream:
            json.dump({
                "name": self.unicode_team_id,
                "leadAgentId": "",
                "leadSessionId": "",
                "createdAt": 1700000000000,
                "members": [],
            }, stream, ensure_ascii=False)

        self.patches = [
            mock.patch.object(app, "PROJECTS_DIR", self.projects),
            mock.patch.object(app, "TRASH_DIR", os.path.join(self.temp.name, "trash")),
            mock.patch.object(app, "INDEX_DB_FILE", os.path.join(self.temp.name, "index.sqlite3")),
        ]
        for patch in self.patches:
            patch.start()
        app.ensure_v2_index(force=True)
        self.logical_id = v2_index.list_projects(app.INDEX_DB_FILE)["items"][0]["id"]
        # Wrap the real team_detail so 400/404 routing can assert call counts.
        self.detail_wrap = mock.patch.object(v2_index, "team_detail", wraps=v2_index.team_detail)
        self.detail_mock = self.detail_wrap.start()
        self.patches.append(self.detail_wrap)

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.temp.cleanup()

    # -- helpers --------------------------------------------------------------

    def _get(self, path):
        handler = FakeHandler()
        handler._handle_v2_get(path, {})
        return handler.responses[-1]

    def _call(self, method_name, payload):
        handler = FakeHandler(json.dumps(payload).encode("utf-8"))
        getattr(handler, method_name)()
        return handler.responses[-1]

    def _trashed_files(self):
        files = []
        root = os.path.join(self.temp.name, "trash")
        for dirpath, _, names in os.walk(root):
            for name in names:
                files.append(os.path.join(dirpath, name))
        return files

    # -- GET /api/v2/teams and /api/v2/team/<id> ------------------------------

    def test_list_teams(self):
        status, payload = self._get("/api/v2/teams")
        self.assertEqual(status, 200)
        self.assertEqual(payload.get("total"), 2)
        ids = [item.get("id") for item in payload.get("items", [])]
        self.assertIn(self.team_id, ids)
        self.assertIn(self.unicode_team_id, ids)

    def test_team_detail_structure(self):
        status, payload = self._get("/api/v2/team/" + self.team_id)
        self.assertEqual(status, 200)
        self.assertEqual(payload["team"]["id"], self.team_id)
        self.assertEqual(payload["team"]["name"], self.team_name)
        lead = payload["lead"]
        self.assertEqual(lead["agent_id"], self.lead_agent_id)
        self.assertIsNotNone(lead["session"])
        self.assertEqual(lead["session"]["id"], self.lead_id)
        members = payload["members"]
        by_agent_id = {member["agent_id"]: member for member in members}
        self.assertEqual(set(by_agent_id), {self.lead_agent_id, self.config_member_agent_id})
        lead_member = by_agent_id[self.lead_agent_id]
        self.assertIsNotNone(lead_member["session"])
        self.assertEqual(lead_member["session"]["id"], self.lead_id)
        member = by_agent_id[self.config_member_agent_id]
        self.assertIsNotNone(member["session"], "成员会话应经 agent_id 关联")
        self.assertEqual(member["session"]["id"], self.subagent_id)
        self.assertEqual(member["logical_project_id"], self.logical_id)
        self.assertEqual(member["record_project_id"], self.logical_id)

    def test_team_detail_rejects_invalid_id(self):
        status, payload = self._get("/api/v2/team/..\\evil")
        self.assertEqual(status, 400)
        self.assertEqual(payload.get("error"), "invalid team id")
        self.detail_mock.assert_not_called()

    def test_team_detail_rejects_encoded_traversal(self):
        status, payload = self._get("/api/v2/team/..%2Fevil")
        self.assertEqual(status, 400)
        self.assertEqual(payload.get("error"), "invalid team id")
        self.detail_mock.assert_not_called()

    def test_team_detail_rejects_separator_only(self):
        # Decodes to a/b: caught by the _TEAM_ID_REJECT blocklist (path
        # separator), a different rejection path than the ".." check above.
        status, payload = self._get("/api/v2/team/a%2Fb")
        self.assertEqual(status, 400)
        self.assertEqual(payload.get("error"), "invalid team id")
        self.detail_mock.assert_not_called()

    def test_team_detail_accepts_percent_encoded_unicode_id(self):
        path = "/api/v2/team/" + urllib.parse.quote(self.unicode_team_id)
        status, payload = self._get(path)
        self.assertEqual(status, 200)
        self.assertEqual(payload["team"]["id"], self.unicode_team_id)
        self.assertEqual(payload["team"]["name"], self.unicode_team_id)
        self.assertIsNone(payload["lead"]["session"])
        self.assertEqual(payload["members"], [])
        self.detail_mock.assert_called_once_with(app.INDEX_DB_FILE, self.unicode_team_id)

    def test_team_detail_missing_team_returns_404(self):
        status, payload = self._get("/api/v2/team/nonexistent-team")
        self.assertEqual(status, 404)
        self.assertEqual(payload.get("error"), "team not found")
        self.detail_mock.assert_called_once_with(app.INDEX_DB_FILE, "nonexistent-team")

    # -- trash moves the member-agent sidecar along with the JSONL ------------

    def test_trash_member_session_moves_jsonl_and_agent_meta(self):
        status, payload = self._call("_handle_v2_trash_session", {
            "project_id": self.logical_id, "session_id": self.subagent_id,
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"), payload)
        self.assertTrue(os.path.isfile(self.lead_path), "lead 会话不应被移动")
        self.assertFalse(os.path.exists(self.subagent_path))
        self.assertFalse(os.path.exists(self.subagent_meta_path))
        trashed = self._trashed_files()
        jsonls = [p for p in trashed if p.endswith(".jsonl")]
        agent_metas = [p for p in trashed if p.endswith(".agent-meta.json")]
        trash_metas = [p for p in trashed if p.endswith(".jsonl.meta.json")]
        self.assertEqual(len(jsonls), 1)
        self.assertTrue(os.path.basename(jsonls[0]).startswith(self.subagent_id))
        self.assertEqual(len(agent_metas), 1, "成员代理 .meta.json 应移入回收站")
        self.assertEqual(len(trash_metas), 1, "回收站记录元数据仍应写入 dest.meta.json")
        with open(agent_metas[0], encoding="utf-8") as stream:
            self.assertEqual(json.load(stream).get("teamName"), self.team_id)

    def test_batch_trash_moves_agent_meta_sidecar(self):
        status, payload = self._call("_handle_v2_trash_sessions", {
            "project_id": self.logical_id,
            "session_ids": [self.subagent_id],
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"), payload)
        self.assertEqual(payload.get("moved"), 1)
        self.assertTrue(os.path.isfile(self.lead_path), "lead 会话不应被移动")
        self.assertFalse(os.path.exists(self.subagent_path))
        self.assertFalse(os.path.exists(self.subagent_meta_path))
        trashed = self._trashed_files()
        agent_metas = [p for p in trashed if p.endswith(".agent-meta.json")]
        self.assertEqual(len(agent_metas), 1)
        jsonls = [p for p in trashed if p.endswith(".jsonl")]
        self.assertEqual(len(jsonls), 1)


if __name__ == "__main__":
    unittest.main()
