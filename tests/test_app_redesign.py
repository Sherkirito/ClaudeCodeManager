"""App-level tests for the v2.1.0 API redesign (contract docs/design-v2.1.md §4).

Covers:
- GET /api/v2/sessions: kind/scope passthrough + 400 validation, by_kind in
  the response, no jsonl_rel_path leakage (API never adds it).
- GET /api/v2/project/<id>/sessions: legacy alias mapped to scope=project:<id>.
- GET /api/v2/session/<p>/<s>: detail slim-down — no children/related arrays,
  descendant_count preserved.
- POST /api/v2/trash-session: cascade (default true) moves the target plus all
  nested subagent/teammate logs and their .meta.json sidecars; cascade=false
  moves only the target; nested rows never cascade; trashed list + legacy
  fields (message / trash_path) in the response.
- GET /api/v2/orphan-history-sessions: endpoint unchanged (passthrough).

All fixtures are synthesized under tempfile directories; no real Claude data
is ever read or written.
"""

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


def qs_of(query_string):
    return urllib.parse.parse_qs(query_string)


class SessionsApiTests(unittest.TestCase):
    """GET /api/v2/sessions and /api/v2/project/<id>/sessions (§4.1 / §4.2)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.projects = os.path.join(self.temp.name, "projects")
        os.makedirs(self.projects)
        self.patches = [
            mock.patch.object(app, "PROJECTS_DIR", self.projects),
            mock.patch.object(app, "TRASH_DIR", os.path.join(self.temp.name, "trash")),
            mock.patch.object(app, "INDEX_DB_FILE", os.path.join(self.temp.name, "index.sqlite3")),
            mock.patch.object(app, "SESSION_SUMMARIES_FILE", os.path.join(self.temp.name, "summaries.json")),
        ]
        for patch in self.patches:
            patch.start()
        self.list_patcher = mock.patch.object(v2_index, "list_sessions")
        self.list_mock = self.list_patcher.start()

    def tearDown(self):
        self.list_patcher.stop()
        for patch in self.patches:
            patch.stop()
        self.temp.cleanup()

    def _get(self, path, qs):
        handler = FakeHandler()
        handler._handle_v2_get(path, qs)
        return handler.responses[-1]

    @staticmethod
    def _fake_list_data():
        return {
            "items": [
                {
                    "id": "ssssssss-ssss-ssss-ssss-ssssssssssss",
                    "kind": "subagent",
                    "project_id": "Proj-1",
                    "project_name": "示例项目",
                    "title": "子代理任务",
                    "parent_session_id": "pppppppp-pppp-pppp-pppp-pppppppppppp",
                    "jsonl_available": True,
                },
            ],
            "total": 1,
            "by_kind": {"primary": 9, "job": 1, "sdk": 0, "subagent": 1, "teammate": 2},
            "limit": 80,
            "offset": 0,
        }

    def test_sessions_passes_kind_scope_q_limit_offset_through(self):
        fake = self._fake_list_data()
        self.list_mock.return_value = fake
        status, payload = self._get("/api/v2/sessions", qs_of(
            "kind=subagent&scope=team%3Ademo-team&q=hello&limit=5&offset=2"))
        self.assertEqual(status, 200)
        self.list_mock.assert_called_once_with(
            app.INDEX_DB_FILE,
            kind="subagent",
            scope="team:demo-team",
            q="hello",
            limit=5,
            offset=2,
        )
        self.assertEqual(payload["total"], fake["total"])
        self.assertEqual(payload["by_kind"], fake["by_kind"])
        self.assertEqual(payload["items"][0]["id"], fake["items"][0]["id"])
        self.assertEqual(payload["items"][0]["project_id"], "Proj-1")
        # The API attaches stored summaries but must never add IO-layer fields.
        self.assertIn("ai_summary", payload["items"][0])
        self.assertNotIn("jsonl_rel_path", payload["items"][0])

    def test_sessions_defaults_kind_all_scope_none(self):
        self.list_mock.return_value = self._fake_list_data()
        status, payload = self._get("/api/v2/sessions", {})
        self.assertEqual(status, 200)
        self.list_mock.assert_called_once_with(
            app.INDEX_DB_FILE,
            kind="all",
            scope=None,
            q="",
            limit=80,
            offset=0,
        )

    def test_sessions_scope_project_and_parent_values(self):
        self.list_mock.return_value = self._fake_list_data()
        for scope in ("project:Proj-1", "parent:aaaa--agent-0001"):
            with self.subTest(scope=scope):
                status, _ = self._get("/api/v2/sessions", qs_of("scope=" + urllib.parse.quote(scope)))
                self.assertEqual(status, 200)
                self.assertEqual(self.list_mock.call_args.kwargs["scope"], scope)
                self.list_mock.reset_mock()

    def test_sessions_automatic_kind_is_accepted(self):
        self.list_mock.return_value = self._fake_list_data()
        status, _ = self._get("/api/v2/sessions", qs_of("kind=automatic"))
        self.assertEqual(status, 200)
        self.assertEqual(self.list_mock.call_args.kwargs["kind"], "automatic")

    def test_sessions_rejects_invalid_kind(self):
        for kind in ("bogus", "primary;", "ALLx"):
            with self.subTest(kind=kind):
                status, payload = self._get("/api/v2/sessions", qs_of("kind=" + kind))
                self.assertEqual(status, 400)
                self.assertEqual(payload.get("error"), "invalid kind")
                self.list_mock.assert_not_called()

    def test_sessions_rejects_invalid_scope(self):
        bad_scopes = (
            "evil:123",          # unknown prefix
            "project:",          # empty value
            "team:",             # empty value
            "parent:",           # empty value
            "noscope",           # missing colon
            "project:..%5Cx",    # traversal in project id
            "project:a%2Fb",     # separator in project id
            "parent:a%3Ab",      # colon in session id
            "team:..",           # traversal in team id
        )
        for scope in bad_scopes:
            with self.subTest(scope=scope):
                status, payload = self._get("/api/v2/sessions", qs_of("scope=" + scope))
                self.assertEqual(status, 400, "scope=%r" % scope)
                self.assertEqual(payload.get("error"), "invalid scope")
                self.list_mock.assert_not_called()

    def test_sessions_response_carries_by_kind_facets(self):
        self.list_mock.return_value = self._fake_list_data()
        _, payload = self._get("/api/v2/sessions", {})
        by_kind = payload.get("by_kind")
        self.assertIsNotNone(by_kind, "by_kind 必须出现在响应中（facet chips 计数用）")
        self.assertEqual(set(by_kind), {"primary", "job", "sdk", "subagent", "teammate"})

    def test_project_sessions_maps_to_scope_project(self):
        fake = self._fake_list_data()
        self.list_mock.return_value = fake
        status, payload = self._get("/api/v2/project/Proj-1/sessions", qs_of("kind=teammate&limit=20"))
        self.assertEqual(status, 200)
        self.list_mock.assert_called_once_with(
            app.INDEX_DB_FILE,
            kind="teammate",
            scope="project:Proj-1",
            q="",
            limit=20,
            offset=0,
        )
        self.assertEqual(payload["by_kind"], fake["by_kind"], "响应结构与规范入口同构")

    def test_project_sessions_rejects_invalid_kind(self):
        status, payload = self._get("/api/v2/project/Proj-1/sessions", qs_of("kind=bogus"))
        self.assertEqual(status, 400)
        self.assertEqual(payload.get("error"), "invalid kind")
        self.list_mock.assert_not_called()

    def test_project_sessions_rejects_invalid_project_id(self):
        status, payload = self._get("/api/v2/project/..%2Fx/sessions", {})
        self.assertEqual(status, 400)
        self.assertEqual(payload.get("error"), "invalid project id")
        self.list_mock.assert_not_called()


class SessionDetailApiTests(unittest.TestCase):
    """GET /api/v2/session/<project>/<session> slim-down (§4.3)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.projects = os.path.join(self.temp.name, "projects")
        os.makedirs(self.projects)
        self.patches = [
            mock.patch.object(app, "PROJECTS_DIR", self.projects),
            mock.patch.object(app, "TRASH_DIR", os.path.join(self.temp.name, "trash")),
            mock.patch.object(app, "INDEX_DB_FILE", os.path.join(self.temp.name, "index.sqlite3")),
            mock.patch.object(app, "SESSION_SUMMARIES_FILE", os.path.join(self.temp.name, "summaries.json")),
        ]
        for patch in self.patches:
            patch.start()
        self.detail_patcher = mock.patch.object(v2_index, "session_detail")
        self.detail_mock = self.detail_patcher.start()

    def tearDown(self):
        self.detail_patcher.stop()
        for patch in self.patches:
            patch.stop()
        self.temp.cleanup()

    def _get(self, path, qs):
        handler = FakeHandler()
        handler._handle_v2_get(path, qs)
        return handler.responses[-1]

    @staticmethod
    def _fake_detail():
        return {
            "session": {
                "id": "ssssssss-ssss-ssss-ssss-ssssssssssss",
                "kind": "primary",
                "project_id": "Proj-1",
                "project_name": "示例项目",
                "title": "主会话",
                "descendant_count": 2,
                "children": [{"id": "child-1"}, {"id": "child-2"}],
                "related": [{"id": "child-1"}],
                "parent": {"id": "pppppppp-pppp-pppp-pppp-pppppppppppp"},
                "lineage": [{"id": "llllllll-llll-llll-llll-llllllllllll"}],
                "team_id": "demo-team",
                "team_name": "Demo Team",
            },
            "messages": [{"role": "user", "content": "你好"}],
            "total": 1,
            "limit": 160,
            "offset": 0,
            "messages_source": "index",
            "stats_on_demand": False,
            "related_total": 5,
        }

    def test_session_detail_strips_children_and_keeps_descendant_count(self):
        self.detail_mock.return_value = self._fake_detail()
        status, payload = self._get(
            "/api/v2/session/Proj-1/ssssssss-ssss-ssss-ssss-ssssssssssss", {})
        self.assertEqual(status, 200)
        session = payload.get("session")
        self.assertIsNotNone(session)
        for key in ("children", "related"):
            self.assertNotIn(key, session, "详情响应不得包含 %s 数组" % key)
        self.assertNotIn("related_total", payload)
        self.assertEqual(session.get("descendant_count"), 2, "descendant_count 必须保留")
        self.assertIsNotNone(session.get("parent"), "parent 卡片保留")
        self.assertIsNotNone(session.get("lineage"), "lineage 保留")
        self.assertEqual(session.get("team_id"), "demo-team", "团队卡片保留")
        self.assertEqual(payload["messages"][0]["role"], "user")
        self.assertIn("ai_summary", session, "AI 摘要照常附加")

    def test_session_detail_missing_session_returns_404(self):
        self.detail_mock.return_value = None
        status, payload = self._get("/api/v2/session/Proj-1/missing-session-id", {})
        self.assertEqual(status, 404)
        self.assertEqual(payload.get("error"), "session not found")


class RealSessionsApiTests(unittest.TestCase):
    """Integration smoke: /api/v2/sessions against the real v2_index
    (no mocks) once list_sessions carries the v2.1 signature."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.projects = os.path.join(self.temp.name, "projects")
        self.record_id = "D--Smoke"
        self.record_dir = os.path.join(self.projects, self.record_id)
        os.makedirs(self.record_dir)
        cwd = os.path.join(self.temp.name, "smoke-project")
        os.makedirs(cwd)
        self.primary_id = "22222222-2222-2222-2222-222222222222"
        self.job_id = "33333333-3333-3333-3333-333333333333"
        for session_id in (self.primary_id, self.job_id):
            with open(os.path.join(self.record_dir, session_id + ".jsonl"), "w", encoding="utf-8") as stream:
                stream.write(json.dumps({
                    "type": "user", "uuid": session_id, "timestamp": 1700000000000,
                    "cwd": cwd, "entrypoint": "cli",
                    "message": {"role": "user", "content": "冒烟测试"},
                }, ensure_ascii=False) + "\n")
        jobs_dir = os.path.join(self.temp.name, "jobs")
        state_path = os.path.join(jobs_dir, "job-1", "state.json")
        os.makedirs(os.path.dirname(state_path))
        with open(state_path, "w", encoding="utf-8") as stream:
            json.dump({"sessionId": self.job_id}, stream)
        self.patches = [
            mock.patch.object(app, "PROJECTS_DIR", self.projects),
            mock.patch.object(app, "TRASH_DIR", os.path.join(self.temp.name, "trash")),
            mock.patch.object(app, "INDEX_DB_FILE", os.path.join(self.temp.name, "index.sqlite3")),
            mock.patch.object(app, "SESSION_SUMMARIES_FILE", os.path.join(self.temp.name, "summaries.json")),
        ]
        for patch in self.patches:
            patch.start()
        app.ensure_v2_index(force=True)
        self.logical_id = v2_index.list_projects(app.INDEX_DB_FILE)["items"][0]["id"]

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.temp.cleanup()

    def _get(self, path, qs):
        handler = FakeHandler()
        handler._handle_v2_get(path, qs)
        return handler.responses[-1]

    def test_sessions_real_route_returns_by_kind_and_no_io_fields(self):
        status, payload = self._get("/api/v2/sessions", qs_of("kind=all"))
        self.assertEqual(status, 200)
        self.assertEqual(payload.get("total"), 2)
        by_kind = payload.get("by_kind")
        self.assertIsNotNone(by_kind, "by_kind 必须出现在响应中")
        self.assertEqual(by_kind.get("primary"), 1)
        self.assertEqual(by_kind.get("job"), 1)
        for item in payload.get("items", []):
            for banned in ("record_project_id", "jsonl_rel_path"):
                self.assertNotIn(banned, item, "不变式 #3: 不得外泄 " + banned)
            self.assertIn("kind", item)
            self.assertIn("id", item)

    def test_sessions_real_route_scope_project_and_kind_job(self):
        status, payload = self._get("/api/v2/sessions", qs_of(
            "kind=job&scope=project:" + self.logical_id))
        self.assertEqual(status, 200)
        self.assertEqual(payload.get("total"), 1)
        self.assertEqual(payload["items"][0]["kind"], "job")
        self.assertEqual(payload["items"][0]["id"], self.job_id)


class OrphanApiTests(unittest.TestCase):
    """GET /api/v2/orphan-history-sessions stays as-is (§4.4)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.projects = os.path.join(self.temp.name, "projects")
        os.makedirs(self.projects)
        self.patches = [
            mock.patch.object(app, "PROJECTS_DIR", self.projects),
            mock.patch.object(app, "TRASH_DIR", os.path.join(self.temp.name, "trash")),
            mock.patch.object(app, "INDEX_DB_FILE", os.path.join(self.temp.name, "index.sqlite3")),
        ]
        for patch in self.patches:
            patch.start()
        self.orphan_patcher = mock.patch.object(v2_index, "list_orphan_history_sessions")
        self.orphan_mock = self.orphan_patcher.start()

    def tearDown(self):
        self.orphan_patcher.stop()
        for patch in self.patches:
            patch.stop()
        self.temp.cleanup()

    def test_orphan_history_endpoint_unchanged(self):
        fake = {"items": [{"session_id": "orphan-1"}], "total": 1, "limit": 12, "offset": 3}
        self.orphan_mock.return_value = fake
        handler = FakeHandler()
        handler._handle_v2_get(
            "/api/v2/orphan-history-sessions",
            qs_of("q=findme&include_command_only=true&limit=12&offset=3"),
        )
        status, payload = handler.responses[-1]
        self.assertEqual(status, 200)
        self.orphan_mock.assert_called_once_with(
            app.INDEX_DB_FILE,
            q="findme",
            include_command_only=True,
            limit=12,
            offset=3,
        )
        self.assertEqual(payload, fake, "orphan 端点响应直通，行为不变")

    def _call_post(self, path, payload):
        handler = FakeHandler(json.dumps(payload).encode("utf-8"))
        handler._dispatch_post(path)
        return handler.responses[-1]

    def test_orphan_remove_reports_removed_count(self):
        patcher = mock.patch.object(
            v2_index, "remove_orphan_history_sessions", return_value=1)
        remove_mock = patcher.start()
        self.addCleanup(patcher.stop)
        status, payload = self._call_post(
            "/api/v2/orphan-history-sessions/remove", {"session_id": "orphan-1"})
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"ok": True, "removed": 1, "message": "记录已移除"})
        remove_mock.assert_called_once_with(app.INDEX_DB_FILE, ["orphan-1"])

    def test_orphan_remove_accepts_dict_result(self):
        patcher = mock.patch.object(
            v2_index, "remove_orphan_history_sessions", return_value={"removed": 3})
        remove_mock = patcher.start()
        self.addCleanup(patcher.stop)
        status, payload = self._call_post(
            "/api/v2/orphan-history-sessions/remove", {"session_id": "orphan-1"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["removed"], 3)

    def test_orphan_remove_missing_session_id_returns_400(self):
        patcher = mock.patch.object(v2_index, "remove_orphan_history_sessions")
        remove_mock = patcher.start()
        self.addCleanup(patcher.stop)
        for body in ({}, {"session_id": ""}, {"session_id": "   "}, {"session_id": 42}):
            with self.subTest(body=body):
                status, payload = self._call_post("/api/v2/orphan-history-sessions/remove", body)
                self.assertEqual(status, 400)
                self.assertFalse(payload.get("ok"))
        remove_mock.assert_not_called()


class TrashCascadeTests(unittest.TestCase):
    """POST /api/v2/trash-session cascade semantics (§4.5)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.projects = os.path.join(self.temp.name, "projects")
        self.record_id = "D--Redesign"
        self.record_dir = os.path.join(self.projects, self.record_id)
        os.makedirs(self.record_dir)
        cwd = os.path.join(self.temp.name, "redesign-project")
        os.makedirs(cwd)
        self.primary_id = "11111111-1111-1111-1111-111111111111"
        self.primary_path = os.path.join(self.record_dir, self.primary_id + ".jsonl")
        with open(self.primary_path, "w", encoding="utf-8") as stream:
            stream.write(json.dumps({
                "type": "user", "uuid": self.primary_id, "timestamp": 1700000000000,
                "cwd": cwd, "entrypoint": "cli",
                "message": {"role": "user", "content": "主会话任务"},
            }, ensure_ascii=False) + "\n")
        # Nested rows: one plain subagent and one teammate (meta sidecar marks
        # taskKind=in_process_teammate); both live under <primary>/subagents/.
        self.subagent_name = "agent-sub1"
        self.subagent_id = self.primary_id + "--" + self.subagent_name
        self.teammate_name = "agent-tmate1"
        self.teammate_id = self.primary_id + "--" + self.teammate_name
        subagents_dir = os.path.join(self.record_dir, self.primary_id, "subagents")
        os.makedirs(subagents_dir)
        self.subagent_path = os.path.join(subagents_dir, self.subagent_name + ".jsonl")
        self.teammate_path = os.path.join(subagents_dir, self.teammate_name + ".jsonl")
        for path, prompt in ((self.subagent_path, "子代理指令"), (self.teammate_path, "队友指令")):
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(json.dumps({
                    "type": "user", "timestamp": 1700000004000, "cwd": cwd,
                    "isSidechain": True, "sessionId": self.primary_id,
                    "message": {"role": "user", "content": prompt},
                }, ensure_ascii=False) + "\n")
        self.subagent_meta_path = self.subagent_path[:-6] + ".meta.json"
        with open(self.subagent_meta_path, "w", encoding="utf-8") as stream:
            json.dump({"name": "sub1", "agentType": "subagent"}, stream, ensure_ascii=False)
        self.teammate_meta_path = self.teammate_path[:-6] + ".meta.json"
        with open(self.teammate_meta_path, "w", encoding="utf-8") as stream:
            json.dump({
                "taskKind": "in_process_teammate",
                "teamName": "demo-team",
                "name": "tmate",
                "agentType": "teammate",
                "color": "#ff6600",
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

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.temp.cleanup()

    def _call(self, method_name, payload):
        handler = FakeHandler(json.dumps(payload).encode("utf-8"))
        getattr(handler, method_name)()
        return handler.responses[-1]

    def _trash_files(self):
        files = []
        root = os.path.join(self.temp.name, "trash")
        for dirpath, _, names in os.walk(root):
            for name in names:
                files.append(os.path.join(dirpath, name))
        return files

    def test_trash_cascade_true_moves_all_nested_sessions_and_sidecars(self):
        status, payload = self._call("_handle_v2_trash_session", {
            "project_id": self.logical_id, "session_id": self.primary_id, "cascade": True,
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"), payload)
        self.assertEqual(payload.get("trashed"), [self.primary_id, self.subagent_id, self.teammate_id])
        self.assertTrue(payload.get("trash_path"), "兼容字段 trash_path 保留")
        for path in (self.primary_path, self.subagent_path, self.teammate_path):
            self.assertFalse(os.path.exists(path), "会话文件应移入回收站: " + path)
        for path in (self.subagent_meta_path, self.teammate_meta_path):
            self.assertFalse(os.path.exists(path), ".meta.json 应连带回收: " + path)
        trashed = self._trash_files()
        jsonls = [p for p in trashed if p.endswith(".jsonl") and not p.endswith(".meta.json")]
        agent_metas = [p for p in trashed if p.endswith(".agent-meta.json")]
        trash_metas = [p for p in trashed if p.endswith(".jsonl.meta.json")]
        self.assertEqual(len(jsonls), 3, "主会话 + 子代理 + 队友 三个转录")
        self.assertEqual(len(agent_metas), 2, "两个 .meta.json 侧车连带移入")
        self.assertEqual(len(trash_metas), 3, "每个回收记录仍有自身元数据")
        names = {os.path.basename(p) for p in jsonls}
        for session_id in (self.primary_id, self.subagent_id, self.teammate_id):
            self.assertTrue(any(n.startswith(session_id + "_") for n in names),
                            "回收文件名应带会话 id: " + session_id)

    def test_trash_cascade_defaults_true(self):
        status, payload = self._call("_handle_v2_trash_session", {
            "project_id": self.logical_id, "session_id": self.primary_id,
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"), payload)
        self.assertEqual(payload.get("trashed"), [self.primary_id, self.subagent_id, self.teammate_id])
        self.assertFalse(os.path.exists(self.primary_path))
        self.assertFalse(os.path.exists(self.subagent_path))
        self.assertFalse(os.path.exists(self.teammate_path))

    def test_trash_cascade_false_moves_only_target(self):
        status, payload = self._call("_handle_v2_trash_session", {
            "project_id": self.logical_id, "session_id": self.primary_id, "cascade": False,
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"), payload)
        self.assertEqual(payload.get("trashed"), [self.primary_id])
        self.assertFalse(os.path.exists(self.primary_path))
        for path in (self.subagent_path, self.teammate_path):
            self.assertTrue(os.path.isfile(path), "cascade=false 不移动嵌套会话: " + path)
        for path in (self.subagent_meta_path, self.teammate_meta_path):
            self.assertTrue(os.path.isfile(path), "cascade=false 不移动侧车: " + path)
        jsonls = [p for p in self._trash_files() if p.endswith(".jsonl") and not p.endswith(".meta.json")]
        self.assertEqual(len(jsonls), 1)

    def test_trash_cascade_accepts_false_string(self):
        status, payload = self._call("_handle_v2_trash_session", {
            "project_id": self.logical_id, "session_id": self.primary_id, "cascade": "false",
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"), payload)
        self.assertEqual(payload.get("trashed"), [self.primary_id])
        self.assertTrue(os.path.isfile(self.subagent_path), "字符串 false 等同布尔 false")

    def test_trash_nested_row_never_cascades(self):
        status, payload = self._call("_handle_v2_trash_session", {
            "project_id": self.logical_id, "session_id": self.subagent_id,
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"), payload)
        self.assertEqual(payload.get("trashed"), [self.subagent_id])
        self.assertFalse(os.path.exists(self.subagent_path))
        self.assertFalse(os.path.exists(self.subagent_meta_path), "自身侧车连带")
        self.assertTrue(os.path.isfile(self.primary_path), "父会话不受影响")
        self.assertTrue(os.path.isfile(self.teammate_path), "兄弟会话不受影响")
        self.assertTrue(os.path.isfile(self.teammate_meta_path))

    def test_trash_missing_session_returns_404(self):
        status, payload = self._call("_handle_v2_trash_session", {
            "project_id": self.logical_id, "session_id": "99999999-9999-9999-9999-999999999999",
        })
        self.assertEqual(status, 404)
        self.assertFalse(payload.get("ok"))
        self.assertTrue(os.path.isfile(self.primary_path), "404 时不动任何文件")


if __name__ == "__main__":
    unittest.main()
