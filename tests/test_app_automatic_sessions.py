"""App-level tests: trash / delete of automatic sessions must not touch parents."""

import io
import json
import os
import tempfile
import unittest
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


class AutomaticSessionTrashTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.projects = os.path.join(self.temp.name, "projects")
        self.record_id = "D--Auto"
        self.record_dir = os.path.join(self.projects, self.record_id)
        os.makedirs(self.record_dir)
        cwd = os.path.join(self.temp.name, "auto-project")
        os.makedirs(cwd)
        self.primary_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        self.job_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        # The synthetic id is <parent>--<agent file base name>, e.g. ...--agent-0001
        self.agent_name = "agent-0001"
        self.subagent_id = self.primary_id + "--" + self.agent_name
        self.primary_path = os.path.join(self.record_dir, self.primary_id + ".jsonl")
        self.job_path = os.path.join(self.record_dir, self.job_id + ".jsonl")
        self.subagent_path = os.path.join(
            self.record_dir, self.primary_id, "subagents", self.agent_name + ".jsonl"
        )
        os.makedirs(os.path.dirname(self.subagent_path))
        for path, session_id in ((self.primary_path, self.primary_id), (self.job_path, self.job_id)):
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(json.dumps({
                    "type": "user", "uuid": session_id, "timestamp": 1700000000000, "cwd": cwd,
                    "entrypoint": "cli", "message": {"role": "user", "content": "任务"},
                }, ensure_ascii=False) + "\n")
        with open(self.subagent_path, "w", encoding="utf-8") as stream:
            stream.write(json.dumps({
                "type": "user", "timestamp": 1700000004000, "cwd": cwd,
                "message": {"role": "user", "content": "子代理指令"},
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

    def _trashed_session_files(self):
        files = []
        root = os.path.join(self.temp.name, "trash", "sessions")
        for dirpath, _, names in os.walk(root):
            for name in names:
                if name.endswith(".jsonl") and not name.endswith(".meta.json"):
                    files.append(os.path.join(dirpath, name))
        return files

    def test_trash_subagent_moves_only_the_subagent_file(self):
        status, payload = self._call("_handle_v2_trash_session", {
            "project_id": self.logical_id, "session_id": self.subagent_id,
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"), payload)
        self.assertTrue(os.path.isfile(self.primary_path), "父会话不应被移动")
        self.assertTrue(os.path.isfile(self.job_path), "同项目其他会话不应被移动")
        self.assertFalse(os.path.exists(self.subagent_path))
        trashed = self._trashed_session_files()
        self.assertEqual(len(trashed), 1)
        self.assertTrue(os.path.basename(trashed[0]).startswith(self.subagent_id))

    def test_trash_job_keeps_primary_and_subagent(self):
        status, payload = self._call("_handle_v2_trash_session", {
            "project_id": self.logical_id, "session_id": self.job_id,
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"), payload)
        self.assertTrue(os.path.isfile(self.primary_path))
        self.assertTrue(os.path.isfile(self.subagent_path))
        self.assertFalse(os.path.exists(self.job_path))

    def test_batch_trash_automatic_sessions_keeps_primary(self):
        status, payload = self._call("_handle_v2_trash_sessions", {
            "project_id": self.logical_id,
            "session_ids": [self.job_id, self.subagent_id],
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"), payload)
        self.assertEqual(payload.get("moved"), 2)
        self.assertTrue(os.path.isfile(self.primary_path), "父会话不应被移动")
        self.assertFalse(os.path.exists(self.job_path))
        self.assertFalse(os.path.exists(self.subagent_path))

    def test_delete_subagent_does_not_delete_parent(self):
        status, payload = self._call("_handle_delete_session", {
            "project_id": self.logical_id, "session_id": self.subagent_id,
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"), payload)
        self.assertTrue(os.path.isfile(self.primary_path), "父会话不应被删除")
        self.assertFalse(os.path.exists(self.subagent_path))


if __name__ == "__main__":
    unittest.main()
