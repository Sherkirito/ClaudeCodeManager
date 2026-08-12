import json
import hashlib
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta


SCHEMA_VERSION = 5
HISTORY_INDEX_VERSION = 1
_SCHEMA_LOCK = threading.RLock()
_SCHEMA_READY = {}


def connect(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=8)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=8000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def init_db(conn):
    """Initialize or migrate a database once per process and file identity."""
    db_row = conn.execute("PRAGMA database_list").fetchone()
    db_path = os.path.realpath(db_row["file"] if db_row and db_row["file"] else ":memory:")
    try:
        stat = os.stat(db_path)
        identity = (stat.st_dev, stat.st_ino)
    except OSError:
        identity = None

    with _SCHEMA_LOCK:
        if _SCHEMA_READY.get(db_path) == identity and identity is not None:
            return
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(
            """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS scan_files (
            path TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            mtime REAL NOT NULL,
            size INTEGER NOT NULL,
            indexed_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            cwd TEXT NOT NULL,
            record_project_id TEXT NOT NULL DEFAULT '',
            source_project_count INTEGER NOT NULL DEFAULT 1,
            path_exists INTEGER NOT NULL DEFAULT 1,
            grouping_reason TEXT NOT NULL DEFAULT 'record_dir',
            session_count INTEGER NOT NULL DEFAULT 0,
            total_messages INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            last_active TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS sessions (
            project_id TEXT NOT NULL,
            id TEXT NOT NULL,
            file_path TEXT NOT NULL,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT '',
            last_active TEXT NOT NULL DEFAULT '',
            cwd TEXT NOT NULL DEFAULT '',
            cwd_initial TEXT NOT NULL DEFAULT '',
            cwd_changed INTEGER NOT NULL DEFAULT 0,
            model TEXT NOT NULL DEFAULT '',
            user_msgs INTEGER NOT NULL DEFAULT 0,
            assistant_msgs INTEGER NOT NULL DEFAULT 0,
            total_msgs INTEGER NOT NULL DEFAULT 0,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            cache_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            first_user_msg TEXT NOT NULL DEFAULT '',
            session_kind TEXT NOT NULL DEFAULT 'primary',
            parent_project_id TEXT NOT NULL DEFAULT '',
            parent_session_id TEXT NOT NULL DEFAULT '',
            agent_id TEXT NOT NULL DEFAULT '',
            relation_confidence TEXT NOT NULL DEFAULT '',
            entrypoint TEXT NOT NULL DEFAULT '',
            child_count INTEGER NOT NULL DEFAULT 0,
            logical_project_id TEXT NOT NULL DEFAULT '',
            path_exists INTEGER NOT NULL DEFAULT 1,
            grouping_reason TEXT NOT NULL DEFAULT 'record_dir',
            agent_type TEXT NOT NULL DEFAULT '',
            agent_name TEXT NOT NULL DEFAULT '',
            agent_description TEXT NOT NULL DEFAULT '',
            agent_color TEXT NOT NULL DEFAULT '',
            task_kind TEXT NOT NULL DEFAULT '',
            team_id TEXT NOT NULL DEFAULT '',
            team_confidence TEXT NOT NULL DEFAULT '',
            indexed_at REAL NOT NULL,
            PRIMARY KEY (project_id, id)
        );

        CREATE TABLE IF NOT EXISTS messages (
            project_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            idx INTEGER NOT NULL,
            role TEXT NOT NULL,
            kind TEXT NOT NULL,
            timestamp TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL DEFAULT '',
            content_json TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            total_tokens INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (project_id, session_id, idx)
        );

        CREATE TABLE IF NOT EXISTS api_usage_events (
            project_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            response_id TEXT NOT NULL,
            timestamp TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT 'unknown',
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
            cache_read_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (project_id, session_id, response_id)
        );

        CREATE TABLE IF NOT EXISTS orphan_history_sessions (
            session_id TEXT PRIMARY KEY,
            project_path TEXT NOT NULL DEFAULT '',
            first_timestamp TEXT NOT NULL DEFAULT '',
            last_timestamp TEXT NOT NULL DEFAULT '',
            prompt_count INTEGER NOT NULL DEFAULT 0,
            substantive_count INTEGER NOT NULL DEFAULT 0,
            first_prompt TEXT NOT NULL DEFAULT '',
            history_file TEXT NOT NULL DEFAULT '',
            is_orphan INTEGER NOT NULL DEFAULT 1,
            detected_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS teams (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT '',
            lead_agent_id TEXT NOT NULL DEFAULT '',
            lead_session_id TEXT NOT NULL DEFAULT '',
            cwd TEXT NOT NULL DEFAULT '',
            member_count INTEGER NOT NULL DEFAULT 0,
            session_count INTEGER NOT NULL DEFAULT 0,
            total_msgs INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            last_active TEXT NOT NULL DEFAULT '',
            config_error INTEGER NOT NULL DEFAULT 0,
            indexed_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS team_members (
            team_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            color TEXT NOT NULL DEFAULT '',
            joined_at TEXT NOT NULL DEFAULT '',
            agent_type TEXT NOT NULL DEFAULT '',
            session_id TEXT NOT NULL DEFAULT '',
            session_project_id TEXT NOT NULL DEFAULT '',
            match_confidence TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (team_id, agent_id)
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
            project_id UNINDEXED,
            session_id UNINDEXED,
            role UNINDEXED,
            title,
            path,
            text,
            tokenize='unicode61'
        );

        CREATE INDEX IF NOT EXISTS idx_sessions_project_active
            ON sessions(project_id, last_active DESC);
        CREATE INDEX IF NOT EXISTS idx_sessions_active
            ON sessions(last_active DESC);
        CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages(project_id, session_id, idx);
        CREATE INDEX IF NOT EXISTS idx_api_usage_timestamp
            ON api_usage_events(timestamp);
        CREATE INDEX IF NOT EXISTS idx_api_usage_response
            ON api_usage_events(response_id);
        CREATE INDEX IF NOT EXISTS idx_orphan_history_activity
            ON orphan_history_sessions(last_timestamp DESC);
        """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
        migrations = {
            "session_kind": "TEXT NOT NULL DEFAULT 'primary'",
            "parent_project_id": "TEXT NOT NULL DEFAULT ''",
            "parent_session_id": "TEXT NOT NULL DEFAULT ''",
            "agent_id": "TEXT NOT NULL DEFAULT ''",
            "relation_confidence": "TEXT NOT NULL DEFAULT ''",
            "entrypoint": "TEXT NOT NULL DEFAULT ''",
            "child_count": "INTEGER NOT NULL DEFAULT 0",
            "logical_project_id": "TEXT NOT NULL DEFAULT ''",
            "path_exists": "INTEGER NOT NULL DEFAULT 1",
            "grouping_reason": "TEXT NOT NULL DEFAULT 'record_dir'",
            "agent_type": "TEXT NOT NULL DEFAULT ''",
            "agent_name": "TEXT NOT NULL DEFAULT ''",
            "agent_description": "TEXT NOT NULL DEFAULT ''",
            "agent_color": "TEXT NOT NULL DEFAULT ''",
            "task_kind": "TEXT NOT NULL DEFAULT ''",
            "team_id": "TEXT NOT NULL DEFAULT ''",
            "team_confidence": "TEXT NOT NULL DEFAULT ''",
        }
        for name, definition in migrations.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE sessions ADD COLUMN {name} {definition}")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_logical_project_active ON sessions(logical_project_id, last_active DESC)"
        )
        project_columns = {row["name"] for row in conn.execute("PRAGMA table_info(projects)")}
        project_migrations = {
            "record_project_id": "TEXT NOT NULL DEFAULT ''",
            "source_project_count": "INTEGER NOT NULL DEFAULT 1",
            "path_exists": "INTEGER NOT NULL DEFAULT 1",
            "grouping_reason": "TEXT NOT NULL DEFAULT 'record_dir'",
        }
        for name, definition in project_migrations.items():
            if name not in project_columns:
                conn.execute(f"ALTER TABLE projects ADD COLUMN {name} {definition}")
        history_columns = {row["name"] for row in conn.execute("PRAGMA table_info(orphan_history_sessions)")}
        if "is_orphan" not in history_columns:
            conn.execute("ALTER TABLE orphan_history_sessions ADD COLUMN is_orphan INTEGER NOT NULL DEFAULT 1")
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
        try:
            stat = os.stat(db_path)
            _SCHEMA_READY[db_path] = (stat.st_dev, stat.st_ino)
        except OSError:
            _SCHEMA_READY.pop(db_path, None)


def _row_dict(row):
    return dict(row) if row is not None else None


def _history_prompt(row):
    value = row.get("display")
    if value in (None, ""):
        value = row.get("prompt", "")
    return value if isinstance(value, str) else str(value or "")


def _is_substantive_history_prompt(value):
    text = (value or "").strip()
    if len(text) < 8:
        return False
    first = text.split(None, 1)[0].lower()
    return first not in {
        "/resume", "/clear", "/model", "/context", "/history", "/memory",
        "/theme", "/compact", "/help", "/exit", "/quit", "-continue", "-resume",
    }


def _history_timestamp(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000 if value > 100000000000 else value).isoformat()
    return str(value or "")


def _history_preview(value):
    text = (value or "")[:500]
    patterns = (
        r"(?i)((?:api[_ -]?key|access[_ -]?token|secret|password)\s*[:=]\s*)\S+",
        r"\b(?:sk|AIza|ghp|github_pat)_[A-Za-z0-9_-]{12,}\b",
    )
    for pattern in patterns:
        text = re.sub(pattern, r"\1[已隐藏]" if "(?i)" in pattern else "[已隐藏]", text)
    return text


def _refresh_orphan_history(conn, projects_dir):
    """Persist compact history metadata and cheaply reconcile it with active JSONLs."""
    history_file = os.path.join(os.path.dirname(projects_dir), "history.jsonl")
    if not os.path.isfile(history_file):
        conn.execute("DELETE FROM orphan_history_sessions")
        return 0
    try:
        stat = os.stat(history_file)
    except OSError:
        return 0
    signature = f"v{HISTORY_INDEX_VERSION}:{stat.st_mtime_ns}:{stat.st_size}"
    old_signature = conn.execute(
        "SELECT value FROM meta WHERE key = 'history_file_signature'"
    ).fetchone()
    if not old_signature or old_signature["value"] != signature:
        grouped = {}
        try:
            with open(history_file, "r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    try:
                        row = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    session_id = row.get("sessionId") or row.get("session_id")
                    if not session_id:
                        continue
                    item = grouped.setdefault(session_id, {"rows": [], "project": ""})
                    item["rows"].append(row)
                    item["project"] = item["project"] or row.get("project") or row.get("cwd") or ""
        except OSError:
            return 0

        conn.execute("DELETE FROM orphan_history_sessions")
        now = time.time()
        for session_id, item in grouped.items():
            rows = item["rows"]
            prompts = [_history_prompt(row) for row in rows]
            substantive = [prompt for prompt in prompts if _is_substantive_history_prompt(prompt)]
            timestamps = [_history_timestamp(row.get("timestamp")) for row in rows]
            conn.execute(
                """
                INSERT INTO orphan_history_sessions(
                    session_id, project_path, first_timestamp, last_timestamp,
                    prompt_count, substantive_count, first_prompt, history_file,
                    is_orphan, detected_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    session_id, item["project"], timestamps[0] if timestamps else "",
                    timestamps[-1] if timestamps else "", len(prompts), len(substantive),
                    _history_preview((substantive or prompts or [""])[0]), history_file, now,
                ),
            )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('history_file_signature', ?)",
            (signature,),
        )

    conn.execute(
        """
        UPDATE orphan_history_sessions
        SET is_orphan = CASE WHEN EXISTS (
            SELECT 1 FROM sessions
            WHERE sessions.id = orphan_history_sessions.session_id
              AND sessions.parent_session_id = ''
        ) THEN 0 ELSE 1 END
        """
    )
    return conn.execute(
        "SELECT COUNT(*) AS c FROM orphan_history_sessions WHERE is_orphan = 1"
    ).fetchone()["c"]


def _norm_project_path(path):
    if not isinstance(path, str) or not path.strip():
        return ""
    return os.path.normcase(os.path.normpath(path.strip()))


def _logical_project_id(path):
    digest = hashlib.sha1(_norm_project_path(path).encode("utf-8", "surrogatepass")).hexdigest()[:16]
    return "cwd-" + digest


def _public_session(row):
    item = _row_dict(row)
    if item is None:
        return None
    item["record_project_id"] = item.get("project_id", "")
    item["project_id"] = item.get("logical_project_id") or item["record_project_id"]
    return item


def _dt_from_timestamp(value):
    if value in (None, ""):
        return ""
    try:
        if isinstance(value, (int, float)):
            ts = float(value)
        else:
            ts = float(str(value))
        if ts > 100000000000:
            ts = ts / 1000
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(value)


def _message_text(content, fix_text):
    parts = []
    if isinstance(content, str):
        parts.append(fix_text(content))
    elif isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "")
            if btype == "text" and block.get("text"):
                parts.append(fix_text(block.get("text", "")))
            elif btype == "tool_use":
                name = block.get("name", "tool")
                raw_input = block.get("input", {})
                try:
                    raw_input = json.dumps(raw_input, ensure_ascii=False)
                except Exception:
                    raw_input = str(raw_input)
                parts.append("[tool_use] " + name + " " + raw_input[:4000])
            elif btype == "tool_result":
                rc = block.get("content", "")
                if isinstance(rc, str):
                    parts.append("[tool_result] " + fix_text(rc))
                elif isinstance(rc, list):
                    for item in rc:
                        if isinstance(item, dict) and item.get("text"):
                            parts.append("[tool_result] " + fix_text(item.get("text", "")))
    return "\n".join(p for p in parts if p).strip()


def _token_count(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _extract_api_usage_events(file_path, project_id, session_id):
    """Read complete API usage data and collapse repeated blocks in one log."""
    events = {}
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as stream:
            for line_number, raw_line in enumerate(stream, 1):
                try:
                    entry = json.loads(raw_line)
                except (TypeError, ValueError):
                    continue
                if entry.get("type") != "assistant":
                    continue
                message = entry.get("message") or {}
                if not isinstance(message, dict):
                    continue
                usage = message.get("usage")
                if not isinstance(usage, dict) or not usage:
                    continue
                message_id = str(message.get("id") or "").strip()
                response_id = message_id or f"local:{project_id}:{session_id}:{line_number}"
                values = {
                    "input_tokens": _token_count(usage.get("input_tokens")),
                    "output_tokens": _token_count(usage.get("output_tokens")),
                    "cache_creation_tokens": _token_count(usage.get("cache_creation_input_tokens")),
                    "cache_read_tokens": _token_count(usage.get("cache_read_input_tokens")),
                }
                row_total = sum(values.values())
                existing = events.get(response_id)
                if existing is None:
                    events[response_id] = {
                        "project_id": project_id,
                        "session_id": session_id,
                        "response_id": response_id,
                        "timestamp": _dt_from_timestamp(entry.get("timestamp")),
                        "model": str(message.get("model") or "unknown"),
                        "total_tokens": row_total,
                        **values,
                    }
                    continue
                timestamp = _dt_from_timestamp(entry.get("timestamp"))
                if timestamp and (not existing["timestamp"] or timestamp < existing["timestamp"]):
                    existing["timestamp"] = timestamp
                if row_total > existing["total_tokens"]:
                    existing.update(values)
                    existing["total_tokens"] = row_total
                    existing["model"] = str(message.get("model") or existing["model"])
                if existing["model"] == "unknown" and message.get("model"):
                    existing["model"] = str(message.get("model"))
    except OSError:
        return []

    result = []
    for event in events.values():
        event["total_tokens"] = (
            event["input_tokens"]
            + event["output_tokens"]
            + event["cache_creation_tokens"]
            + event["cache_read_tokens"]
        )
        result.append(event)
    return result


def _session_meta(entries, fix_text):
    meta = {
        "title": "未命名会话",
        "created_at": "",
        "last_active": "",
        "cwd": "",
        "cwd_initial": "",
        "cwd_changed": 0,
        "model": "",
        "user_msgs": 0,
        "assistant_msgs": 0,
        "total_msgs": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_tokens": 0,
        "total_tokens": 0,
        "first_user_msg": "",
        "entrypoint": "",
        "agent_id": "",
        "is_sidechain": 0,
        "message_uuids": [],
    }
    last_cwd = ""
    usage_by_response = {}
    for entry_index, entry in enumerate(entries):
        if entry.get("entrypoint") and not meta["entrypoint"]:
            meta["entrypoint"] = str(entry.get("entrypoint"))
        if entry.get("agentId") and not meta["agent_id"]:
            meta["agent_id"] = str(entry.get("agentId"))
        if entry.get("isSidechain") is True:
            meta["is_sidechain"] = 1
        if entry.get("uuid"):
            meta["message_uuids"].append(str(entry.get("uuid")))
        timestamp = _dt_from_timestamp(entry.get("timestamp"))
        if timestamp:
            if not meta["created_at"]:
                meta["created_at"] = timestamp
            meta["last_active"] = timestamp

        cwd = entry.get("cwd")
        if isinstance(cwd, str) and cwd.strip():
            cwd = fix_text(cwd.strip())
            if not meta["cwd_initial"]:
                meta["cwd_initial"] = cwd
            if last_cwd and os.path.normcase(os.path.normpath(last_cwd)) != os.path.normcase(os.path.normpath(cwd)):
                meta["cwd_changed"] = 1
            last_cwd = cwd
            meta["cwd"] = cwd

        if entry.get("type") == "ai-title" and entry.get("aiTitle"):
            meta["title"] = fix_text(entry.get("aiTitle"))
            continue

        t = entry.get("type", "")
        msg = entry.get("message", {})
        if not isinstance(msg, dict):
            msg = {}
        if t == "user":
            meta["user_msgs"] += 1
            text = _message_text(msg.get("content", ""), fix_text)
            if text and not meta["first_user_msg"]:
                meta["first_user_msg"] = text[:500]
        elif t == "assistant":
            meta["assistant_msgs"] += 1
            if not meta["model"]:
                meta["model"] = msg.get("model") or ""
            usage = msg.get("usage", {}) or {}
            if isinstance(usage, dict) and usage:
                response_id = str(msg.get("id") or "").strip() or f"local:{entry_index}"
                values = {
                    "input_tokens": _token_count(usage.get("input_tokens")),
                    "output_tokens": _token_count(usage.get("output_tokens")),
                    "cache_tokens": (
                        _token_count(usage.get("cache_creation_input_tokens"))
                        + _token_count(usage.get("cache_read_input_tokens"))
                    ),
                }
                existing = usage_by_response.setdefault(response_id, {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_tokens": 0,
                })
                if sum(values.values()) > sum(existing.values()):
                    existing.update(values)

    for usage in usage_by_response.values():
        meta["input_tokens"] += usage["input_tokens"]
        meta["output_tokens"] += usage["output_tokens"]
        meta["cache_tokens"] += usage["cache_tokens"]

    meta["total_msgs"] = meta["user_msgs"] + meta["assistant_msgs"]
    meta["total_tokens"] = meta["input_tokens"] + meta["output_tokens"]
    if not meta["last_active"]:
        meta["last_active"] = meta["created_at"]
    if not meta["model"]:
        meta["model"] = "unknown"
    return meta


def _extract_messages(project_id, session_id, entries, fix_text):
    out = []
    idx = 0
    for entry in entries:
        t = entry.get("type", "")
        if t not in ("user", "assistant"):
            continue
        msg = entry.get("message", {}) or {}
        content = msg.get("content", "")
        text = _message_text(content, fix_text)
        if not text and t == "assistant":
            continue
        usage = msg.get("usage", {}) or {}
        total_tokens = int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
        try:
            content_json = json.dumps(content, ensure_ascii=False)
        except Exception:
            content_json = json.dumps(str(content), ensure_ascii=False)
        out.append(
            {
                "project_id": project_id,
                "session_id": session_id,
                "idx": idx,
                "role": msg.get("role") or t,
                "kind": t,
                "timestamp": _dt_from_timestamp(entry.get("timestamp")),
                "text": text,
                "content_json": content_json,
                "model": msg.get("model") or "",
                "total_tokens": total_tokens,
            }
        )
        idx += 1
    return out


def _project_path(folder_name, folder_path, read_jsonl, fix_text):
    try:
        files = [
            os.path.join(folder_path, fn)
            for fn in os.listdir(folder_path)
            if fn.endswith(".jsonl")
        ]
        files.sort(key=lambda fp: os.path.getmtime(fp), reverse=True)
        for fp in files[:3]:
            for entry in read_jsonl(fp, max_entries=80):
                cwd = entry.get("cwd")
                if isinstance(cwd, str) and cwd.strip():
                    return fix_text(cwd.strip())
    except Exception:
        pass
    parts = folder_name.split("--")
    if len(parts) > 1:
        return parts[0].rstrip("-") + ":\\" + "\\".join(parts[1:])
    return folder_name


def _refresh_logical_projects(conn):
    """Group records by their real initial cwd instead of Claude's lossy folder id."""
    physical_paths = {
        row["id"]: (row["cwd"] or row["name"] or row["id"])
        for row in conn.execute("SELECT id, name, cwd FROM projects")
    }
    rows = [dict(row) for row in conn.execute(
        "SELECT project_id, id, cwd_initial, cwd, parent_project_id, parent_session_id FROM sessions"
    )]
    parent_paths = {}
    for row in rows:
        path = row["cwd_initial"] or row["cwd"] or ""
        if path:
            parent_paths[(row["project_id"], row["id"])] = path

    classified = []
    paths_by_record = {}
    records_by_path = {}
    for row in rows:
        path = ""
        if row["parent_session_id"]:
            path = parent_paths.get((row["parent_project_id"] or row["project_id"], row["parent_session_id"]), "")
        if not path:
            path = row["cwd_initial"] or row["cwd"] or ""
        if not path:
            path = physical_paths.get(row["project_id"], row["project_id"])
        path = os.path.normpath(path)
        key = _norm_project_path(path)
        classified.append((row, path, key))
        paths_by_record.setdefault(row["project_id"], set()).add(key)
        records_by_path.setdefault(key, set()).add(row["project_id"])

    groups = {}
    for row, path, key in classified:
        record_collision = len(paths_by_record.get(row["project_id"], ())) > 1
        multi_record = len(records_by_path.get(key, ())) > 1
        if record_collision or multi_record:
            logical_id = _logical_project_id(path)
            reason = "cwd_collision" if record_collision else "multi_record_dirs"
        else:
            logical_id = row["project_id"]
            reason = "record_dir"
        exists = int(os.path.isdir(path))
        conn.execute(
            "UPDATE sessions SET logical_project_id = ?, path_exists = ?, grouping_reason = ? WHERE project_id = ? AND id = ?",
            (logical_id, exists, reason, row["project_id"], row["id"]),
        )
        group = groups.setdefault(logical_id, {
            "path": path,
            "records": set(),
            "exists": exists,
            "reason": reason,
        })
        group["records"].add(row["project_id"])
        group["exists"] = max(group["exists"], exists)
        if reason != "record_dir":
            group["reason"] = reason

    conn.execute("DELETE FROM projects")
    for logical_id, group in groups.items():
        record_ids = sorted(group["records"])
        conn.execute(
            """
            INSERT INTO projects(
                id, name, cwd, record_project_id, source_project_count,
                path_exists, grouping_reason
            ) VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                logical_id,
                group["path"],
                group["path"],
                record_ids[0] if len(record_ids) == 1 else "",
                len(record_ids),
                group["exists"],
                group["reason"],
            ),
        )


def _refresh_project_path_state(conn):
    """Refresh moved/missing directory flags without rebuilding project groups."""
    projects = conn.execute("SELECT id, cwd FROM projects").fetchall()
    for project in projects:
        exists = int(bool(project["cwd"]) and os.path.isdir(project["cwd"]))
        conn.execute("UPDATE projects SET path_exists = ? WHERE id = ?", (exists, project["id"]))
    conn.execute(
        """
        UPDATE sessions
        SET path_exists = COALESCE(
            (SELECT path_exists FROM projects WHERE projects.id = sessions.logical_project_id),
            path_exists
        )
        """
    )


def rebuild_index(db_path, projects_dir, read_jsonl, fix_text):
    conn = connect(db_path)
    try:
        init_db(conn)
        conn.executescript(
            """
            DELETE FROM scan_files;
            DELETE FROM projects;
            DELETE FROM sessions;
            DELETE FROM messages;
            DELETE FROM messages_fts;
            """
        )
        conn.commit()
    finally:
        conn.close()
    return scan_incremental(db_path, projects_dir, read_jsonl, fix_text, force=True)


def _discover_session_files(folder_path):
    """Yield top-level sessions and Claude-managed nested subagent logs."""
    found = []
    for fn in sorted(os.listdir(folder_path)):
        if fn.endswith(".jsonl"):
            found.append((os.path.join(folder_path, fn), fn[:-6], "", ""))
    for root, _, files in os.walk(folder_path):
        parts = os.path.relpath(root, folder_path).split(os.sep)
        if "subagents" not in parts:
            continue
        parent_session_id = parts[0] if parts else ""
        for fn in sorted(files):
            if not fn.startswith("agent-") or not fn.endswith(".jsonl"):
                continue
            agent_id = fn[6:-6]
            synthetic_id = parent_session_id + "--agent-" + agent_id
            found.append((os.path.join(root, fn), synthetic_id, parent_session_id, agent_id))
    return found


def _job_session_ids(projects_dir):
    jobs_dir = os.path.join(os.path.dirname(projects_dir), "jobs")
    if not os.path.isdir(jobs_dir):
        return set()
    result = set()
    for name in os.listdir(jobs_dir):
        state_path = os.path.join(jobs_dir, name, "state.json")
        if not os.path.isfile(state_path):
            continue
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            if state.get("sessionId"):
                result.add(str(state["sessionId"]))
        except Exception:
            continue
    return result


def _infer_job_parents(direct_sessions):
    """Infer cloned job lineage only when message identity overlap is decisive."""
    parents = {}
    by_project = {}
    for item in direct_sessions:
        by_project.setdefault(item["project_id"], []).append(item)
    for sessions in by_project.values():
        for child in sessions:
            if child["kind"] != "job" or not child["uuids"]:
                continue
            child_uuids = child["uuids"]
            best = None
            for candidate in sessions:
                if candidate["id"] == child["id"] or candidate["kind"] != "primary":
                    continue
                if candidate["file_created"] > child["file_created"]:
                    continue
                shared = len(child_uuids.intersection(candidate["uuids"]))
                denominator = min(len(child_uuids), len(candidate["uuids"])) or 1
                ratio = shared / denominator
                if shared >= 3 and ratio >= 0.8 and (best is None or shared > best[0]):
                    best = (shared, candidate["id"])
            if best:
                parents[(child["project_id"], child["id"])] = best[1]
    return parents


def _read_agent_meta(jsonl_path):
    """Read a subagent log's sibling .meta.json and return teammate fields.

    Returns {} unless the meta marks the agent as an in-process teammate
    (taskKind == 'in_process_teammate') carrying a team name, in which case
    the member fields are returned keyed by sessions column names. A missing
    or unparsable meta file also yields {}.
    """
    meta_path = (
        jsonl_path[:-6] + ".meta.json" if jsonl_path.endswith(".jsonl") else jsonl_path + ".meta.json"
    )
    try:
        with open(meta_path, "r", encoding="utf-8", errors="replace") as stream:
            meta = json.load(stream)
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(meta, dict):
        return {}
    if meta.get("taskKind") != "in_process_teammate" or not meta.get("teamName"):
        return {}
    return {
        "agent_type": str(meta.get("agentType") or ""),
        "agent_name": str(meta.get("name") or ""),
        "agent_description": str(meta.get("description") or ""),
        "agent_color": str(meta.get("color") or ""),
        "task_kind": "in_process_teammate",
        "team_id": str(meta.get("teamName") or ""),
    }


_AGENT_META_COLUMNS = (
    "agent_type", "agent_name", "agent_description",
    "agent_color", "task_kind", "team_id",
)


def _update_session_agent_meta(conn, project_id, session_id, agent_meta):
    """Refresh teammate columns for a gated file without re-reading its log."""
    stored = conn.execute(
        "SELECT agent_type, agent_name, agent_description, agent_color, task_kind, team_id "
        "FROM sessions WHERE project_id = ? AND id = ?",
        (project_id, session_id),
    ).fetchone()
    if stored is None:
        return
    changes = [
        column for column in _AGENT_META_COLUMNS
        if (stored[column] or "") != str(agent_meta.get(column) or "")
    ]
    if not changes:
        return
    assignments = ", ".join(column + " = ?" for column in changes)
    conn.execute(
        f"UPDATE sessions SET {assignments} WHERE project_id = ? AND id = ?",
        [str(agent_meta.get(column) or "") for column in changes] + [project_id, session_id],
    )


_TEAM_CONF_RANK = {
    "lead_session": 0,
    "exact": 1,
    "meta_scope": 2,
    "lead_dir": 3,
    "team_name": 4,
}


def _iso_created_at(value):
    if value in (None, ""):
        return ""
    try:
        timestamp = float(value)
        if timestamp > 100000000000:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return str(value)


def _agent_id_matches_member(agent_id, member_name):
    """True when a session agent id carries the member name as a token.

    Matches the forms name / name-<hex> / a+name / a+name-<hex> as prefixes,
    so "aindexer-a1b2..." resolves to the member named "indexer" without
    matching a sibling like "indexer2".
    """
    if not agent_id or not member_name:
        return False
    lowered = agent_id.lower()
    for prefix in (member_name.lower(), "a" + member_name.lower()):
        if lowered == prefix or lowered.startswith(prefix + "-"):
            return True
    return False


def _upsert_team(conn, team_id, config, now):
    """Insert or refresh one teams row (and its member rows) from a config dict.

    A falsy config marks the row as unreadable (config_error = 1) without
    deleting existing data; a parsed config replaces the team members.
    """
    if config:
        lead_agent_id = str(config.get("leadAgentId") or "")
        lead_session_id = str(config.get("leadSessionId") or "")
        # Privacy: config member cwd is display-only and never persisted, so
        # teams.cwd stays empty here; team_detail derives a display value from
        # the already-indexed lead session instead.
        conn.execute(
            """
            INSERT OR REPLACE INTO teams(
                id, name, created_at, lead_agent_id, lead_session_id, cwd,
                config_error, indexed_at
            ) VALUES(?, ?, ?, ?, ?, '', 0, ?)
            """,
            (
                team_id,
                str(config.get("name") or ""),
                _iso_created_at(config.get("createdAt")),
                lead_agent_id,
                lead_session_id,
                now,
            ),
        )
        conn.execute("DELETE FROM team_members WHERE team_id = ?", (team_id,))
        for member in config.get("members") or []:
            if not isinstance(member, dict) or not member.get("agentId"):
                continue
            conn.execute(
                """
                INSERT INTO team_members(team_id, agent_id, name, color, joined_at, agent_type)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    team_id,
                    str(member.get("agentId") or ""),
                    str(member.get("name") or ""),
                    str(member.get("color") or ""),
                    str(member.get("joinedAt") or ""),
                    str(member.get("agentType") or ""),
                ),
            )
        return
    existing = conn.execute("SELECT 1 FROM teams WHERE id = ?", (team_id,)).fetchone()
    if existing:
        conn.execute("UPDATE teams SET config_error = 1 WHERE id = ?", (team_id,))
    else:
        conn.execute(
            "INSERT INTO teams(id, config_error, indexed_at) VALUES(?, 1, ?)",
            (team_id, now),
        )


def _refresh_teams(conn, teams_dir):
    """Reconcile Agent team configs with sessions and member mappings.

    Reads each <team>/config.json (skipping unchanged files via a stored
    mtime:size signature), upserts teams/team_members rows, cascades four
    evidence levels to link member sessions to members, and recomputes
    aggregate stats every scan.
    """
    now = time.time()
    session_rows = [dict(row) for row in conn.execute(
        "SELECT project_id, id, parent_session_id, agent_id, task_kind, team_id, last_active "
        "FROM sessions ORDER BY last_active DESC"
    )]
    if not os.path.isdir(teams_dir):
        conn.execute("DELETE FROM teams")
        conn.execute("DELETE FROM team_members")
        conn.execute("UPDATE sessions SET team_id = '', task_kind = '', team_confidence = ''")
        return

    seen_team_ids = set()
    for name in sorted(os.listdir(teams_dir)):
        team_dir = os.path.join(teams_dir, name)
        if not os.path.isdir(team_dir):
            continue
        seen_team_ids.add(name)
        config_path = os.path.join(team_dir, "config.json")
        try:
            stat = os.stat(config_path)
        except OSError:
            _upsert_team(conn, name, {}, now)
            continue
        signature = f"{stat.st_mtime}:{stat.st_size}"
        sig_key = "teams_scan:" + os.path.normpath(config_path)
        old_signature = conn.execute(
            "SELECT value FROM meta WHERE key = ?", (sig_key,)
        ).fetchone()
        if old_signature and old_signature["value"] == signature:
            continue
        config = None
        try:
            with open(config_path, "r", encoding="utf-8", errors="replace") as stream:
                config = json.load(stream)
            if not isinstance(config, dict):
                config = None
        except (OSError, ValueError, TypeError):
            config = None
        if config is None:
            _upsert_team(conn, name, {}, now)
            continue
        _upsert_team(conn, name, config, now)
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
            (sig_key, signature),
        )

    # Member<->session links are rebuilt every scan so deleted logs drop out.
    conn.execute(
        "UPDATE team_members SET session_id = '', session_project_id = '', match_confidence = ''"
    )
    team_rows = [dict(row) for row in conn.execute(
        "SELECT id, name, lead_session_id, lead_agent_id FROM teams"
    )]
    member_rows = [dict(row) for row in conn.execute(
        "SELECT team_id, agent_id, name FROM team_members"
    )]
    members_by_team = {}
    for row in member_rows:
        members_by_team.setdefault(row["team_id"], []).append(row)
    sessions_by_id = {}
    for row in session_rows:
        sessions_by_id.setdefault(row["id"], []).append(row)

    session_assign = {}
    member_candidates = []
    member_claims = {}

    def offer(key, team_id, confidence):
        rank = _TEAM_CONF_RANK[confidence]
        current = session_assign.get(key)
        if current is None or rank < _TEAM_CONF_RANK[current[1]]:
            session_assign[key] = (team_id, confidence)

    for team in team_rows:
        team_id = team["id"]
        team_name = team["name"] or ""
        lead_session_id = team["lead_session_id"] or ""
        lead_agent_id = team["lead_agent_id"] or ""
        if lead_session_id:
            # Lead link: the lead transcript may live in any record.
            for row in sessions_by_id.get(lead_session_id, []):
                offer((row["project_id"], row["id"]), team_id, "lead_session")
        for member in members_by_team.get(team_id, []):
            member_agent_id = member["agent_id"]
            member_name = member["name"]
            if member_agent_id == lead_agent_id or "team-lead" in member_agent_id:
                # The lead member row never joins the generic member cascade: a
                # stale lead transcript carrying the same leadAgentId must not
                # be tagged as a teammate. Link the row straight to the current
                # lead session instead (tagged by the lead link above).
                lead_rows = sessions_by_id.get(lead_session_id, []) if lead_session_id else []
                if lead_rows:
                    member_claims[(team_id, member_agent_id)] = (lead_rows[0], "exact")
                continue
            for row in session_rows:
                agent_id = row["agent_id"] or ""
                if not agent_id:
                    continue
                in_scope = (
                    not row["team_id"]
                    or row["team_id"] == team_id
                    or (team_name and row["team_id"] == team_name)
                )
                if not in_scope:
                    continue
                if agent_id == member_agent_id:
                    member_candidates.append((1, team_id, member_agent_id, row))
                    continue
                if not _agent_id_matches_member(agent_id, member_name):
                    continue
                if row["team_id"]:
                    # teamName scope + member name prefix match.
                    member_candidates.append((2, team_id, member_agent_id, row))
                elif lead_session_id and row["parent_session_id"] == lead_session_id:
                    # Physical nesting under the lead session dir backs a member
                    # match even without teammate meta; unrelated subagents that
                    # match no member are never tagged this way.
                    member_candidates.append((3, team_id, member_agent_id, row))

    member_candidates.sort(key=lambda item: (item[0], item[3]["project_id"], item[3]["id"]))
    claimed_sessions = set()
    claimed_members = set()
    for rank, team_id, member_agent_id, row in member_candidates:
        key = (row["project_id"], row["id"])
        if key in claimed_sessions or (team_id, member_agent_id) in claimed_members:
            continue
        claimed_sessions.add(key)
        claimed_members.add((team_id, member_agent_id))
        confidence = {1: "exact", 2: "meta_scope", 3: "lead_dir"}[rank]
        member_claims[(team_id, member_agent_id)] = (row, confidence)
        offer(key, team_id, confidence)

    # Fallback: a meta teamName that resolves to exactly one team.
    name_to_teams = {}
    for team in team_rows:
        if team["id"]:
            name_to_teams.setdefault(team["id"].lower(), []).append(team)
        if team["name"]:
            name_to_teams.setdefault(team["name"].lower(), []).append(team)
    for row in session_rows:
        key = (row["project_id"], row["id"])
        if key in session_assign:
            continue
        candidates = name_to_teams.get((row["team_id"] or "").lower(), [])
        if len(candidates) == 1:
            offer(key, candidates[0]["id"], "team_name")

    for key, (team_id, confidence) in session_assign.items():
        conn.execute(
            "UPDATE sessions SET team_id = ?, team_confidence = ? WHERE project_id = ? AND id = ?",
            (team_id, confidence, key[0], key[1]),
        )
    leads_by_team = {team["id"]: team["lead_session_id"] or "" for team in team_rows}
    for (team_id, member_agent_id), (row, confidence) in member_claims.items():
        conn.execute(
            """
            UPDATE team_members
            SET session_id = ?, session_project_id = ?, match_confidence = ?
            WHERE team_id = ? AND agent_id = ?
            """,
            (row["id"], row["project_id"], confidence, team_id, member_agent_id),
        )
        if row["id"] != leads_by_team.get(team_id):
            # Member-level links (exact / meta_scope / lead_dir) mark the
            # session as a teammate so kind="teammate" stays consistent with
            # the member mapping. The lead session itself is exempt (it is
            # resolved via leadSessionId), as is the team-only fallback.
            conn.execute(
                "UPDATE sessions SET task_kind = 'in_process_teammate' "
                "WHERE project_id = ? AND id = ?",
                (row["project_id"], row["id"]),
            )

    # Drop teams whose directory disappeared and clear dangling session links.
    existing_ids = {row["id"] for row in conn.execute("SELECT id FROM teams")}
    for stale in existing_ids - seen_team_ids:
        conn.execute("DELETE FROM teams WHERE id = ?", (stale,))
        conn.execute("DELETE FROM team_members WHERE team_id = ?", (stale,))
    conn.execute(
        """
        UPDATE sessions
        SET team_id = '', task_kind = '', team_confidence = ''
        WHERE team_id != '' AND team_id NOT IN (SELECT id FROM teams)
        """
    )

    # Aggregates are recomputed every scan, even for unchanged configs.
    for team_id in sorted(existing_ids & seen_team_ids):
        agg = conn.execute(
            """
            SELECT COUNT(*) AS session_count,
                   COALESCE(SUM(total_msgs), 0) AS total_msgs,
                   COALESCE(SUM(total_tokens), 0) AS total_tokens,
                   COALESCE(MAX(last_active), '') AS last_active,
                   (SELECT COUNT(*) FROM team_members WHERE team_members.team_id = ?) AS member_count
            FROM sessions WHERE team_id = ?
            """,
            (team_id, team_id),
        ).fetchone()
        conn.execute(
            """
            UPDATE teams
            SET session_count = ?, total_msgs = ?, total_tokens = ?,
                last_active = ?, member_count = ?, indexed_at = ?
            WHERE id = ?
            """,
            (
                agg["session_count"], agg["total_msgs"], agg["total_tokens"],
                agg["last_active"], agg["member_count"], now, team_id,
            ),
        )


def scan_incremental(db_path, projects_dir, read_jsonl, fix_text, force=False):
    started = time.time()
    stats = {"projects": 0, "sessions": 0, "indexed": 0, "removed": 0, "orphan_history": 0, "duration_ms": 0}
    conn = connect(db_path)
    try:
        init_db(conn)
        relation_version = conn.execute("SELECT value FROM meta WHERE key = 'relation_index_version'").fetchone()
        if not relation_version or relation_version["value"] != str(SCHEMA_VERSION):
            force = True
        if not os.path.isdir(projects_dir):
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('last_scan', ?)", (str(time.time()),))
            conn.commit()
            return stats

        seen_files = set()
        direct_sessions = []
        raw_team_meta = {}
        known_files = {
            row["path"]: row
            for row in conn.execute(
                "SELECT path, project_id, session_id, mtime, size FROM scan_files"
            )
        }
        known_record_paths = {}
        for row in conn.execute(
            """
            SELECT project_id, cwd_initial, cwd
            FROM sessions
            WHERE cwd_initial != '' OR cwd != ''
            ORDER BY indexed_at DESC
            """
        ):
            known_record_paths.setdefault(row["project_id"], row["cwd_initial"] or row["cwd"])
        job_session_ids = _job_session_ids(projects_dir)
        for project_id in sorted(os.listdir(projects_dir)):
            folder_path = os.path.join(projects_dir, project_id)
            if not os.path.isdir(folder_path):
                continue
            stats["projects"] += 1
            real_path = known_record_paths.get(project_id) or _project_path(
                project_id, folder_path, read_jsonl, fix_text
            )
            conn.execute(
                "INSERT OR IGNORE INTO projects(id, name, cwd) VALUES(?, ?, ?)",
                (project_id, real_path, real_path),
            )

            for file_path, session_id, parent_session_id, path_agent_id in _discover_session_files(folder_path):
                normalized_path = os.path.realpath(file_path)
                seen_files.add(normalized_path)
                stats["sessions"] += 1
                try:
                    st = os.stat(file_path)
                except OSError:
                    continue
                old = known_files.get(normalized_path)
                # Teammate metadata (.meta.json) can change without touching the
                # log, so read it every pass for nested files to keep the member
                # columns fresh even when the JSONL is gated below.
                agent_meta = _read_agent_meta(file_path) if parent_session_id else {}
                if parent_session_id:
                    raw_team_meta[(project_id, session_id)] = agent_meta
                if (
                    not force
                    and old
                    and float(old["mtime"]) == float(st.st_mtime)
                    and int(old["size"]) == int(st.st_size)
                ):
                    if parent_session_id:
                        _update_session_agent_meta(conn, project_id, session_id, agent_meta)
                    continue

                # Subagent logs can be numerous and very large. Their role in the
                # manager is lineage/navigation, so cap indexing work while keeping
                # the original JSONL untouched on disk.
                entries = read_jsonl(file_path, max_entries=240) if parent_session_id else read_jsonl(file_path)
                meta = _session_meta(entries, fix_text)
                usage_events = _extract_api_usage_events(file_path, project_id, session_id)
                if parent_session_id:
                    session_kind = "subagent"
                    relation_confidence = "exact"
                elif session_id in job_session_ids:
                    session_kind = "job"
                    relation_confidence = ""
                elif meta["entrypoint"] == "sdk-cli":
                    session_kind = "sdk"
                    relation_confidence = ""
                else:
                    session_kind = "primary"
                    relation_confidence = ""
                if not parent_session_id:
                    direct_sessions.append({
                        "project_id": project_id,
                        "id": session_id,
                        "kind": session_kind,
                        "uuids": set(meta["message_uuids"]),
                        "file_created": st.st_ctime,
                    })
                messages = [] if parent_session_id else _extract_messages(project_id, session_id, entries, fix_text)
                now = time.time()

                conn.execute("DELETE FROM sessions WHERE project_id = ? AND id = ?", (project_id, session_id))
                conn.execute("DELETE FROM messages WHERE project_id = ? AND session_id = ?", (project_id, session_id))
                conn.execute("DELETE FROM messages_fts WHERE project_id = ? AND session_id = ?", (project_id, session_id))
                conn.execute("DELETE FROM api_usage_events WHERE project_id = ? AND session_id = ?", (project_id, session_id))
                conn.execute(
                    """
                    INSERT INTO sessions(
                        project_id, id, file_path, title, created_at, last_active, cwd, cwd_initial,
                        cwd_changed, model, user_msgs, assistant_msgs, total_msgs, input_tokens,
                        output_tokens, cache_tokens, total_tokens, first_user_msg, session_kind,
                        parent_project_id, parent_session_id, agent_id, relation_confidence,
                        entrypoint, child_count, logical_project_id, path_exists, grouping_reason,
                        agent_type, agent_name, agent_description, agent_color, task_kind,
                        team_id, indexed_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        session_id,
                        file_path,
                        meta["title"],
                        meta["created_at"],
                        meta["last_active"],
                        meta["cwd"],
                        meta["cwd_initial"],
                        meta["cwd_changed"],
                        meta["model"],
                        meta["user_msgs"],
                        meta["assistant_msgs"],
                        meta["total_msgs"],
                        meta["input_tokens"],
                        meta["output_tokens"],
                        meta["cache_tokens"],
                        meta["total_tokens"],
                        meta["first_user_msg"],
                        session_kind,
                        project_id if parent_session_id else "",
                        parent_session_id,
                        meta["agent_id"] or path_agent_id,
                        relation_confidence,
                        meta["entrypoint"],
                        0,
                        project_id,
                        int(os.path.isdir(meta["cwd_initial"] or meta["cwd"])) if (meta["cwd_initial"] or meta["cwd"]) else 0,
                        "record_dir",
                        agent_meta.get("agent_type", ""),
                        agent_meta.get("agent_name", ""),
                        agent_meta.get("agent_description", ""),
                        agent_meta.get("agent_color", ""),
                        agent_meta.get("task_kind", ""),
                        agent_meta.get("team_id", ""),
                        now,
                    ),
                )
                for message in messages:
                    conn.execute(
                        """
                        INSERT INTO messages(project_id, session_id, idx, role, kind, timestamp, text, content_json, model, total_tokens)
                        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            message["project_id"],
                            message["session_id"],
                            message["idx"],
                            message["role"],
                            message["kind"],
                            message["timestamp"],
                            message["text"],
                            message["content_json"],
                            message["model"],
                            message["total_tokens"],
                        ),
                    )
                    conn.execute(
                        "INSERT INTO messages_fts(project_id, session_id, role, title, path, text) VALUES(?, ?, ?, ?, ?, ?)",
                        (project_id, session_id, message["role"], meta["title"], meta["cwd"] or real_path, message["text"]),
                    )
                conn.executemany(
                    """
                    INSERT INTO api_usage_events(
                        project_id, session_id, response_id, timestamp, model,
                        input_tokens, output_tokens, cache_creation_tokens,
                        cache_read_tokens, total_tokens
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            event["project_id"],
                            event["session_id"],
                            event["response_id"],
                            event["timestamp"],
                            event["model"],
                            event["input_tokens"],
                            event["output_tokens"],
                            event["cache_creation_tokens"],
                            event["cache_read_tokens"],
                            event["total_tokens"],
                        )
                        for event in usage_events
                    ],
                )
                conn.execute(
                    "INSERT OR REPLACE INTO scan_files(path, project_id, session_id, mtime, size, indexed_at) VALUES(?, ?, ?, ?, ?, ?)",
                    (normalized_path, project_id, session_id, st.st_mtime, st.st_size, now),
                )
                stats["indexed"] += 1

        inferred_parents = _infer_job_parents(direct_sessions)
        for (project_id, session_id), parent_session_id in inferred_parents.items():
            conn.execute(
                "UPDATE sessions SET parent_project_id = ?, parent_session_id = ?, relation_confidence = 'high' WHERE project_id = ? AND id = ?",
                (project_id, parent_session_id, project_id, session_id),
            )

        for row in known_files.values():
            if row["path"] in seen_files and os.path.exists(row["path"]):
                continue
            conn.execute("DELETE FROM scan_files WHERE path = ?", (row["path"],))
            conn.execute("DELETE FROM sessions WHERE project_id = ? AND id = ?", (row["project_id"], row["session_id"]))
            conn.execute("DELETE FROM messages WHERE project_id = ? AND session_id = ?", (row["project_id"], row["session_id"]))
            conn.execute("DELETE FROM messages_fts WHERE project_id = ? AND session_id = ?", (row["project_id"], row["session_id"]))
            conn.execute("DELETE FROM api_usage_events WHERE project_id = ? AND session_id = ?", (row["project_id"], row["session_id"]))
            stats["removed"] += 1

        # Reseed the team columns from the raw teammate metadata read this pass
        # (clearing every other row), so the team cascade always derives from
        # current evidence instead of feeding on its own previous output.
        conn.execute(
            "UPDATE sessions SET team_id = '', task_kind = '', team_confidence = '' "
            "WHERE team_id != '' OR task_kind != '' OR team_confidence != ''"
        )
        for (project_id, session_id), agent_meta in raw_team_meta.items():
            if not agent_meta.get("team_id") and not agent_meta.get("task_kind"):
                continue
            conn.execute(
                "UPDATE sessions SET team_id = ?, task_kind = ?, team_confidence = '' "
                "WHERE project_id = ? AND id = ?",
                (agent_meta.get("team_id", ""), agent_meta.get("task_kind", ""), project_id, session_id),
            )
        _refresh_teams(conn, os.path.join(os.path.dirname(projects_dir), "teams"))

        conn.execute(
            """
            UPDATE sessions AS child
            SET parent_project_id = '', parent_session_id = '', relation_confidence = ''
            WHERE child.parent_session_id != '' AND NOT EXISTS (
                SELECT 1 FROM sessions parent
                WHERE parent.project_id = child.parent_project_id
                  AND parent.id = child.parent_session_id
            )
            """
        )

        index_changed = force or stats["indexed"] > 0 or stats["removed"] > 0
        if index_changed:
            conn.execute(
                """
                UPDATE sessions SET child_count = COALESCE((
                    SELECT COUNT(*) FROM sessions child
                    WHERE child.parent_project_id = sessions.project_id
                      AND child.parent_session_id = sessions.id
                ), 0)
                """
            )
            _refresh_logical_projects(conn)
        else:
            _refresh_project_path_state(conn)
        stats["orphan_history"] = _refresh_orphan_history(conn, projects_dir)
        if index_changed:
            conn.execute(
                """
                UPDATE projects SET
                    session_count = COALESCE((SELECT COUNT(*) FROM sessions WHERE logical_project_id = projects.id AND session_kind = 'primary' AND parent_session_id = ''), 0),
                    total_messages = COALESCE((SELECT SUM(total_msgs) FROM sessions WHERE logical_project_id = projects.id AND session_kind = 'primary' AND parent_session_id = ''), 0),
                    total_tokens = COALESCE((SELECT SUM(total_tokens) FROM sessions WHERE logical_project_id = projects.id AND session_kind = 'primary' AND parent_session_id = ''), 0),
                    last_active = COALESCE((SELECT MAX(last_active) FROM sessions WHERE logical_project_id = projects.id), ''),
                    cwd = COALESCE(NULLIF(name, ''), cwd)
                """
            )
        conn.execute(
            "DELETE FROM projects WHERE NOT EXISTS (SELECT 1 FROM sessions WHERE sessions.logical_project_id = projects.id)"
        )
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('last_scan', ?)", (str(time.time()),))
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('relation_index_version', ?)", (str(SCHEMA_VERSION),))
        conn.commit()
    finally:
        conn.close()
    stats["duration_ms"] = int((time.time() - started) * 1000)
    return stats


def dashboard(db_path, today=None):
    """Return local index totals and de-duplicated API usage for 30 days."""
    if today is None:
        today = datetime.now().date()
    elif isinstance(today, datetime):
        today = today.date()
    elif isinstance(today, str):
        today = datetime.strptime(today, "%Y-%m-%d").date()
    start_date = today - timedelta(days=29)
    start_text = start_date.isoformat()
    end_text = today.isoformat()

    conn = connect(db_path)
    try:
        init_db(conn)
        counts = _row_dict(
            conn.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM projects) AS total_projects,
                    (SELECT COUNT(*) FROM teams) AS total_teams,
                    (SELECT COUNT(*) FROM sessions WHERE session_kind = 'primary' AND parent_session_id = '') AS total_sessions,
                    (SELECT COUNT(*) FROM sessions WHERE session_kind != 'primary' OR parent_session_id != '') AS total_automatic_sessions,
                    (SELECT COUNT(*) FROM sessions) AS total_all_sessions,
                    (SELECT COUNT(*) FROM orphan_history_sessions WHERE is_orphan = 1 AND substantive_count > 0) AS total_orphan_history_sessions,
                    COALESCE((SELECT SUM(total_msgs) FROM sessions WHERE session_kind = 'primary' AND parent_session_id = ''), 0) AS total_messages,
                    COALESCE((SELECT SUM(total_msgs) FROM sessions WHERE session_kind = 'primary' AND parent_session_id = ''), 0) AS total_primary_messages,
                    COALESCE((SELECT SUM(total_msgs) FROM sessions WHERE session_kind != 'primary' OR parent_session_id != ''), 0) AS total_automatic_messages,
                    COALESCE((SELECT SUM(total_msgs) FROM sessions), 0) AS total_all_messages
                """
            ).fetchone()
        )
        recent = [_public_session(r) for r in conn.execute(
            """
            SELECT s.*, p.name AS project_name
            FROM sessions s
            JOIN projects p ON p.id = s.logical_project_id
            WHERE s.session_kind = 'primary' AND s.parent_session_id = ''
            ORDER BY s.last_active DESC
            LIMIT 12
            """
        )]
        usage_by_model = [_row_dict(r) for r in conn.execute(
            """
            WITH ranked AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY response_id
                    ORDER BY total_tokens DESC,
                             CASE WHEN model = 'unknown' THEN 1 ELSE 0 END,
                             timestamp ASC,
                             project_id ASC,
                             session_id ASC
                ) AS occurrence_rank
                FROM api_usage_events
            )
            SELECT model,
                   COUNT(*) AS unique_responses,
                   COALESCE(SUM(input_tokens), 0) AS input_tokens,
                   COALESCE(SUM(output_tokens), 0) AS output_tokens,
                   COALESCE(SUM(cache_creation_tokens), 0) AS cache_creation_tokens,
                   COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
                   COALESCE(SUM(total_tokens), 0) AS total_tokens
            FROM ranked
            WHERE occurrence_rank = 1
              AND timestamp != ''
              AND total_tokens > 0
              AND substr(timestamp, 1, 10) BETWEEN ? AND ?
            GROUP BY model
            ORDER BY total_tokens DESC, model ASC
            """,
            (start_text, end_text),
        )]
        counts["api_unique_responses_30d"] = sum(row["unique_responses"] for row in usage_by_model)
        counts["api_input_output_tokens_30d"] = sum(
            row["input_tokens"] + row["output_tokens"] for row in usage_by_model
        )
        counts["api_cache_tokens_30d"] = sum(
            row["cache_creation_tokens"] + row["cache_read_tokens"] for row in usage_by_model
        )
        counts["api_tokens_30d"] = sum(row["total_tokens"] for row in usage_by_model)
        status = _row_dict(conn.execute("SELECT value FROM meta WHERE key = 'last_scan'").fetchone())
        return {
            "stats": counts,
            "recent_sessions": recent,
            "api_usage": usage_by_model,
            "api_usage_period": {
                "start": start_text,
                "end": end_text,
                "days": 30,
            },
            "last_scan": status["value"] if status else "",
        }
    finally:
        conn.close()


def list_orphan_history_sessions(db_path, q="", include_command_only=False, limit=80, offset=0):
    conn = connect(db_path)
    try:
        init_db(conn)
        where = ["is_orphan = 1"]
        params = []
        if not include_command_only:
            where.append("substantive_count > 0")
        if q:
            where.append("(first_prompt LIKE ? OR project_path LIKE ? OR session_id LIKE ?)")
            like = "%" + q + "%"
            params.extend([like, like, like])
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM orphan_history_sessions" + where_sql, params
        ).fetchone()["c"]
        rows = conn.execute(
            "SELECT * FROM orphan_history_sessions" + where_sql
            + " ORDER BY substantive_count DESC, last_timestamp DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        return {"items": [_row_dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}
    finally:
        conn.close()


def _path_parts(path):
    path = (path or "").replace("/", "\\").strip("\\")
    return [p for p in path.split("\\") if p]


def _path_startswith(path, prefix):
    if not prefix:
        return True
    parts = _path_parts(path)
    prefix_parts = _path_parts(prefix)
    if len(prefix_parts) > len(parts):
        return False
    for idx, part in enumerate(prefix_parts):
        if part.lower() != parts[idx].lower():
            return False
    return True


def project_dirs(db_path, prefix=""):
    conn = connect(db_path)
    try:
        init_db(conn)
        prefix_parts = _path_parts(prefix)
        children = {}
        count = 0
        rows = conn.execute("SELECT id, name, cwd FROM projects").fetchall()
        for row in rows:
            path = row["cwd"] or row["name"] or row["id"]
            parts = _path_parts(path)
            if len(prefix_parts) > len(parts):
                continue
            ok = True
            for idx, part in enumerate(prefix_parts):
                if part.lower() != parts[idx].lower():
                    ok = False
                    break
            if not ok:
                continue
            count += 1
            if len(parts) > len(prefix_parts):
                child = parts[len(prefix_parts)]
                children[child] = children.get(child, 0) + 1
        return {
            "prefix": "\\".join(prefix_parts),
            "count": count,
            "children": [{"name": k, "count": children[k]} for k in sorted(children.keys(), key=str.lower)],
        }
    finally:
        conn.close()


def list_projects(db_path, q="", drive="", sort="active", path_prefix="", limit=60, offset=0):
    conn = connect(db_path)
    try:
        init_db(conn)
        where = []
        params = []
        if q:
            where.append("(lower(name) LIKE ? OR lower(cwd) LIKE ? OR lower(id) LIKE ?)")
            like = "%" + q.lower() + "%"
            params.extend([like, like, like])
        if drive:
            where.append("upper(cwd) LIKE ?")
            params.append(drive.upper().rstrip(":") + ":%")
        if path_prefix:
            prefix = path_prefix.replace("/", "\\").rstrip("\\")
            where.append("(lower(cwd) LIKE ? OR lower(name) LIKE ?)")
            params.extend([prefix.lower() + "%", prefix.lower() + "%"])
        where_sql = " WHERE " + " AND ".join(where) if where else ""
        order = {
            "name": "name COLLATE NOCASE ASC",
            "sessions": "session_count DESC, last_active DESC",
            "tokens": "total_tokens DESC, last_active DESC",
            "oldest": "last_active ASC",
        }.get(sort, "last_active DESC")
        total = conn.execute("SELECT COUNT(*) AS c FROM projects" + where_sql, params).fetchone()["c"]
        rows = [_row_dict(r) for r in conn.execute(
            f"""SELECT projects.*,
                       (SELECT COUNT(*) FROM sessions s WHERE s.logical_project_id = projects.id AND (s.session_kind != 'primary' OR s.parent_session_id != '')) AS automatic_session_count,
                       (SELECT COUNT(*) FROM sessions s WHERE s.logical_project_id = projects.id) AS all_session_count
                FROM projects{where_sql} ORDER BY {order} LIMIT ? OFFSET ?""",
            params + [limit, offset],
        )]
        drives = [r["drive"] for r in conn.execute(
            """
            SELECT DISTINCT upper(substr(cwd, 1, 2)) AS drive
            FROM projects
            WHERE substr(cwd, 2, 1) = ':'
            ORDER BY drive
            """
        )]
        return {"items": rows, "total": total, "limit": limit, "offset": offset, "drives": drives}
    finally:
        conn.close()


def list_teams(db_path, q="", limit=80, offset=0):
    conn = connect(db_path)
    try:
        init_db(conn)
        where = []
        params = []
        if q:
            where.append("(lower(name) LIKE ? OR lower(cwd) LIKE ? OR lower(lead_agent_id) LIKE ?)")
            like = "%" + q.lower() + "%"
            params.extend([like, like, like])
        where_sql = " WHERE " + " AND ".join(where) if where else ""
        total = conn.execute("SELECT COUNT(*) AS c FROM teams" + where_sql, params).fetchone()["c"]
        rows = []
        for row in conn.execute(
            f"""
            SELECT teams.*,
                   (SELECT s.cwd FROM sessions s WHERE s.id = teams.lead_session_id
                    ORDER BY s.last_active DESC LIMIT 1) AS lead_cwd
            FROM teams{where_sql} ORDER BY last_active DESC LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ):
            item = _row_dict(row)
            # Display-only cwd derived from the indexed lead session; member
            # cwd from the config is never persisted.
            item["cwd"] = item.pop("lead_cwd") or ""
            rows.append(item)
        return {"items": rows, "total": total, "limit": limit, "offset": offset}
    finally:
        conn.close()


def team_detail(db_path, team_id):
    """Return one team with its lead session and member rows (sessions joined)."""
    conn = connect(db_path)
    try:
        init_db(conn)
        team = _row_dict(conn.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone())
        if not team:
            return None
        lead = {"agent_id": team["lead_agent_id"], "session": None}
        if team["lead_session_id"]:
            lead_row = conn.execute(
                """
                SELECT s.*, p.name AS project_name
                FROM sessions s
                JOIN projects p ON p.id = s.logical_project_id
                WHERE s.id = ?
                ORDER BY s.last_active DESC
                LIMIT 1
                """,
                (team["lead_session_id"],),
            ).fetchone()
            lead["session"] = _public_session(lead_row)
            if lead_row:
                # Config member cwd is display-only (never persisted), so the
                # team cwd shown here derives from the already-indexed lead
                # session instead of the config.
                team["cwd"] = lead_row["cwd"] or team["cwd"]
        members = []
        for row in conn.execute(
            "SELECT * FROM team_members WHERE team_id = ? ORDER BY joined_at ASC, name ASC",
            (team_id,),
        ):
            member = {
                "agent_id": row["agent_id"],
                "name": row["name"],
                "color": row["color"],
                "joined_at": row["joined_at"],
                "agent_type": row["agent_type"],
                "confidence": row["match_confidence"],
                "session": None,
                "logical_project_id": "",
                "record_project_id": "",
            }
            if row["session_id"]:
                session_row = conn.execute(
                    """
                    SELECT s.*, p.name AS project_name
                    FROM sessions s
                    JOIN projects p ON p.id = s.logical_project_id
                    WHERE s.project_id = ? AND s.id = ?
                    """,
                    (row["session_project_id"], row["session_id"]),
                ).fetchone()
                if session_row:
                    public = _public_session(session_row)
                    member["session"] = public
                    member["logical_project_id"] = public["project_id"]
                    member["record_project_id"] = public["record_project_id"]
            members.append(member)
        return {"team": team, "lead": lead, "members": members}
    finally:
        conn.close()


def _attach_children(conn, rows):
    for row in rows:
        record_project_id = row.get("record_project_id") or row.get("project_id")
        children = [_public_session(child) for child in conn.execute(
            """
            SELECT s.*, p.name AS project_name, t.name AS team_name
            FROM sessions s
            JOIN projects p ON p.id = s.logical_project_id
            LEFT JOIN teams t ON t.id = s.team_id
            WHERE s.parent_project_id = ? AND s.parent_session_id = ?
            ORDER BY s.last_active DESC
            """,
            (record_project_id, row["id"]),
        )]
        row["children"] = children
    return rows


def _attach_parents(conn, rows):
    """Attach each automatic session's parent row (when known) to flat lists."""
    for row in rows:
        parent_session_id = row.get("parent_session_id") or ""
        if not parent_session_id:
            row["parent"] = None
            continue
        parent = conn.execute(
            """
            SELECT s.*, p.name AS project_name, t.name AS team_name
            FROM sessions s
            JOIN projects p ON p.id = s.logical_project_id
            LEFT JOIN teams t ON t.id = s.team_id
            WHERE s.project_id = ? AND s.id = ?
            """,
            (row.get("parent_project_id") or row.get("record_project_id") or "", parent_session_id),
        ).fetchone()
        row["parent"] = _public_session(parent) if parent else None
    return rows


def list_sessions(db_path, project_id=None, q="", role="", limit=80, offset=0, kind="primary"):
    """List sessions filtered by kind: primary (default), automatic or all.

    kind values:
      - "primary" (default): main sessions only. Automatic children are nested
        under their parents and unattached automatic sessions are returned in
        ``automatic_items`` — the historical behavior.
      - "automatic": every automatic session (job / sdk / subagent) as a flat
        list, each carrying parent info when known.
      - "teammate": every in-process teammate session as a flat list, each
        carrying its team info.
      - "all": primary + automatic in one flat, paginated list without nesting,
        so the same automatic session never appears twice.

    Counts (``primary_total`` / ``automatic_total`` / ``automatic_all_total`` /
    ``teammate_total`` / ``related_total``) always describe the full project
    (plus the query filter), independent of the selected kind, so callers can
    label sections correctly.
    """
    conn = connect(db_path)
    try:
        init_db(conn)
        kind = kind if kind in ("all", "primary", "automatic", "teammate") else "primary"
        base_where, base_params = [], []
        if project_id:
            base_where.append("s.logical_project_id = ?")
            base_params.append(project_id)
        if q:
            base_where.append("(lower(s.title) LIKE ? OR lower(s.first_user_msg) LIKE ? OR lower(s.cwd) LIKE ?)")
            like = "%" + q.lower() + "%"
            base_params.extend([like, like, like])

        kind_where = []
        if kind == "primary":
            kind_where = ["s.session_kind = 'primary'", "s.parent_session_id = ''"]
        elif kind == "automatic":
            kind_where = ["(s.session_kind != 'primary' OR s.parent_session_id != '')"]
        elif kind == "teammate":
            kind_where = ["s.task_kind = 'in_process_teammate'"]
        where_sql = " WHERE " + " AND ".join(base_where + kind_where) if (base_where or kind_where) else ""
        total = conn.execute("SELECT COUNT(*) AS c FROM sessions s" + where_sql, base_params).fetchone()["c"]
        rows = [_public_session(r) for r in conn.execute(
            f"""
            SELECT s.*, p.name AS project_name, t.name AS team_name
            FROM sessions s
            JOIN projects p ON p.id = s.logical_project_id
            LEFT JOIN teams t ON t.id = s.team_id
            {where_sql}
            ORDER BY s.last_active DESC
            LIMIT ? OFFSET ?
            """,
            base_params + [limit, offset],
        )]
        if kind == "primary":
            _attach_children(conn, rows)
        else:
            _attach_parents(conn, rows)

        primary_where = " WHERE " + " AND ".join(
            base_where + ["s.session_kind = 'primary'", "s.parent_session_id = ''"]
        )
        primary_total = conn.execute("SELECT COUNT(*) AS c FROM sessions s" + primary_where, base_params).fetchone()["c"]
        automatic_all_where = " WHERE " + " AND ".join(
            base_where + ["(s.session_kind != 'primary' OR s.parent_session_id != '')"]
        )
        automatic_all_total = conn.execute("SELECT COUNT(*) AS c FROM sessions s" + automatic_all_where, base_params).fetchone()["c"]
        teammate_where = " WHERE " + " AND ".join(
            base_where + ["s.task_kind = 'in_process_teammate'"]
        )
        teammate_total = conn.execute("SELECT COUNT(*) AS c FROM sessions s" + teammate_where, base_params).fetchone()["c"]
        automatic_unattached_where = " WHERE " + " AND ".join(
            base_where + ["s.session_kind != 'primary'", "s.parent_session_id = ''"]
        )
        automatic_unattached_total = conn.execute(
            "SELECT COUNT(*) AS c FROM sessions s" + automatic_unattached_where, base_params
        ).fetchone()["c"]
        automatic_rows = [_public_session(r) for r in conn.execute(
            f"""
            SELECT s.*, p.name AS project_name
            FROM sessions s JOIN projects p ON p.id = s.logical_project_id
            {automatic_unattached_where}
            ORDER BY s.last_active DESC LIMIT 100
            """,
            base_params,
        )]
        return {
            "items": rows,
            "automatic_items": automatic_rows,
            "total": total,
            "primary_total": primary_total,
            "automatic_total": automatic_unattached_total,
            "automatic_all_total": automatic_all_total,
            "teammate_total": teammate_total,
            "related_total": automatic_all_total,
            "limit": limit,
            "offset": offset,
            "kind": kind,
        }
    finally:
        conn.close()


def _builtin_read_jsonl(path, max_entries=None):
    """Minimal JSONL reader used when the host app does not inject its own."""
    rows = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
                if max_entries and len(rows) >= max_entries:
                    break
    except OSError:
        return []
    return rows


def session_detail(db_path, project_id, session_id, limit=160, offset=0, role="", read_jsonl=None, fix_text=None):
    conn = connect(db_path)
    try:
        init_db(conn)
        session = _public_session(conn.execute(
            """
            SELECT s.*, p.name AS project_name, t.name AS team_name
            FROM sessions s
            JOIN projects p ON p.id = s.logical_project_id
            LEFT JOIN teams t ON t.id = s.team_id
            WHERE s.logical_project_id = ? AND s.id = ?
            """,
            (project_id, session_id),
        ).fetchone())
        if not session:
            return None
        record_project_id = session["record_project_id"]
        session["children"] = [_public_session(r) for r in conn.execute(
            """
            SELECT s.*, p.name AS project_name FROM sessions s
            JOIN projects p ON p.id = s.logical_project_id
            WHERE s.parent_project_id = ? AND s.parent_session_id = ?
            ORDER BY s.last_active DESC
            """,
            (record_project_id, session_id),
        )]
        session["parent"] = _public_session(conn.execute(
            """
            SELECT s.*, p.name AS project_name FROM sessions s
            JOIN projects p ON p.id = s.logical_project_id
            WHERE s.project_id = ? AND s.id = ?
            """,
            (session.get("parent_project_id") or record_project_id, session.get("parent_session_id") or ""),
        ).fetchone()) if session.get("parent_session_id") else None
        fixer = fix_text if callable(fix_text) else (lambda value: value)
        messages_source = "index"
        stats_on_demand = False
        is_subagent = session.get("session_kind") == "subagent" or bool(session.get("parent_session_id"))
        if is_subagent:
            # Subagent logs are deliberately not indexed (see scan_incremental) to
            # cap indexing cost. Read the original JSONL on demand for the detail
            # view; the original file is never modified.
            file_path = session.get("file_path") or ""
            if file_path and os.path.isfile(file_path):
                reader = read_jsonl if callable(read_jsonl) else _builtin_read_jsonl
                try:
                    entries = reader(file_path)
                except Exception:
                    entries = []
                if entries:
                    meta = _session_meta(entries, fixer)
                    for key in (
                        "title", "created_at", "last_active", "model", "user_msgs",
                        "assistant_msgs", "total_msgs", "input_tokens", "output_tokens",
                        "cache_tokens", "total_tokens", "first_user_msg",
                    ):
                        if key in meta:
                            session[key] = meta[key]
                    messages = _extract_messages(record_project_id, session_id, entries, fixer)
                    if role:
                        messages = [message for message in messages if message["role"] == role]
                    total = len(messages)
                    rows = messages[offset:offset + limit]
                    messages_source = "jsonl"
                    stats_on_demand = True
                else:
                    messages_source = "unavailable"
                    rows, total = [], 0
            else:
                messages_source = "unavailable"
                rows, total = [], 0
        else:
            where = "WHERE project_id = ? AND session_id = ?"
            params = [record_project_id, session_id]
            if role:
                where += " AND role = ?"
                params.append(role)
            total = conn.execute("SELECT COUNT(*) AS c FROM messages " + where, params).fetchone()["c"]
            rows = [_row_dict(r) for r in conn.execute(
                f"SELECT * FROM messages {where} ORDER BY idx ASC LIMIT ? OFFSET ?",
                params + [limit, offset],
            )]
        return {
            "session": session,
            "messages": rows,
            "total": total,
            "limit": limit,
            "offset": offset,
            "messages_source": messages_source,
            "stats_on_demand": stats_on_demand,
        }
    finally:
        conn.close()


def record_project_id(db_path, project_id, session_id):
    """Resolve a UI logical project id back to Claude's physical record folder id."""
    conn = connect(db_path)
    try:
        init_db(conn)
        row = conn.execute(
            "SELECT project_id FROM sessions WHERE logical_project_id = ? AND id = ? LIMIT 1",
            (project_id, session_id),
        ).fetchone()
        return row["project_id"] if row else project_id
    finally:
        conn.close()


def session_file_path(db_path, project_id, session_id):
    """Return (physical_jsonl_path, record_project_id) for a session row.

    Looks the row up by its physical record project id; nested subagent logs
    (<project>/<parent>/subagents/agent-*.jsonl) do not map to a top-level
    <session>.jsonl file, so their recorded path is the only reliable one.
    """
    conn = connect(db_path)
    try:
        init_db(conn)
        row = conn.execute(
            "SELECT file_path, project_id FROM sessions WHERE project_id = ? AND id = ? LIMIT 1",
            (project_id, session_id),
        ).fetchone()
        return (row["file_path"], row["project_id"]) if row else ("", "")
    finally:
        conn.close()


def search(db_path, q, limit=50, offset=0):
    conn = connect(db_path)
    try:
        init_db(conn)
        if not q:
            return {"items": [], "total": 0, "limit": limit, "offset": offset}
        items = []
        like = "%" + q.lower() + "%"
        for row in conn.execute(
            """
            SELECT 'project' AS type, id AS project_id, '' AS session_id, name AS title,
                   cwd AS path, '' AS role, '' AS snippet, last_active
            FROM projects
            WHERE lower(name) LIKE ? OR lower(cwd) LIKE ? OR lower(id) LIKE ?
            ORDER BY last_active DESC
            LIMIT ?
            """,
            (like, like, like, min(limit, 20)),
        ):
            items.append(_row_dict(row))
        for row in conn.execute(
            """
            SELECT 'session' AS type, s.logical_project_id AS project_id,
                   s.project_id AS record_project_id, s.id AS session_id, s.title,
                   s.cwd AS path, '' AS role, s.first_user_msg AS snippet, s.last_active,
                   s.session_kind, s.task_kind,
                   (SELECT t.name FROM teams t WHERE t.id = s.team_id) AS team_name,
                   s.parent_project_id, s.parent_session_id,
                   s.path_exists, s.grouping_reason,
                   (SELECT ps.title FROM sessions ps
                    WHERE ps.project_id = s.parent_project_id AND ps.id = s.parent_session_id
                   ) AS parent_title
            FROM sessions s
            WHERE lower(s.title) LIKE ? OR lower(s.first_user_msg) LIKE ? OR lower(s.cwd) LIKE ?
            ORDER BY s.last_active DESC
            LIMIT ?
            """,
            (like, like, like, limit),
        ):
            items.append(_row_dict(row))

        try:
            fts_query = q.replace('"', " ")
            for row in conn.execute(
                """
                SELECT 'message' AS type, s.logical_project_id AS project_id,
                       s.project_id AS record_project_id, f.session_id, f.title,
                       f.path, f.role,
                       snippet(messages_fts, 5, '<mark>', '</mark>', '...', 12) AS snippet,
                       s.last_active, s.session_kind, s.task_kind,
                       (SELECT t.name FROM teams t WHERE t.id = s.team_id) AS team_name,
                       s.parent_project_id, s.parent_session_id,
                       s.path_exists, s.grouping_reason,
                       (SELECT ps.title FROM sessions ps
                        WHERE ps.project_id = s.parent_project_id AND ps.id = s.parent_session_id
                       ) AS parent_title
                FROM messages_fts f
                JOIN sessions s ON s.project_id = f.project_id AND s.id = f.session_id
                WHERE messages_fts MATCH ?
                ORDER BY rank
                LIMIT ? OFFSET ?
                """,
                (fts_query, limit, offset),
            ):
                items.append(_row_dict(row))
        except sqlite3.Error:
            pass

        items.sort(key=lambda x: x.get("last_active") or "", reverse=True)
        return {"items": items[:limit], "total": len(items), "limit": limit, "offset": offset}
    finally:
        conn.close()
