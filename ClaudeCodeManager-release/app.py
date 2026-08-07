#!/usr/bin/env python3
"""
Claude 代码管理器 (Claude Code Manager)
=======================================
A local web GUI for browsing, managing, and summarizing Claude Code records.
Reads data directly from ~/.claude/projects/ — no external services required.
"""

import os
import json
import re
import sys
import time
import shutil
import socket
import subprocess
import urllib.parse
import urllib.error
import urllib.request
import webbrowser
import threading
import traceback
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime

import v2_index

_VALID_ID = re.compile(r"^[a-zA-Z0-9._\-]+$")
MAX_POST_BODY = 64 * 1024  # 64 KB max request body

# =============================================================================
# Configuration
# =============================================================================
CLAUDE_DIR = os.path.expanduser("~/.claude")
HOST = "127.0.0.1"
PORT = 5141
PORT_FALLBACK_LIMIT = 200
PROJECTS_DIR = os.path.join(CLAUDE_DIR, "projects")
# Handle both dev and PyInstaller-packaged paths
if getattr(sys, "frozen", False):
    MANAGER_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    EXE_DIR = os.path.dirname(sys.executable)
else:
    MANAGER_DIR = os.path.dirname(os.path.abspath(__file__))
    EXE_DIR = MANAGER_DIR
DATA_DIR = os.path.join(EXE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
TRASH_DIR = os.path.join(DATA_DIR, "trash")
os.makedirs(TRASH_DIR, exist_ok=True)
MIGRATIONS_DIR = os.path.join(DATA_DIR, "migrations")
os.makedirs(MIGRATIONS_DIR, exist_ok=True)

DESCRIPTIONS_FILE = os.path.join(DATA_DIR, "project-descriptions.json")
SESSION_SUMMARIES_FILE = os.path.join(DATA_DIR, "session-summaries.json")
API_CONFIG_FILE = os.path.join(DATA_DIR, "api-config.json")
PATH_MAPPINGS_FILE = os.path.join(DATA_DIR, "path-mappings.json")

# ---- Model presets per provider ----

PROVIDER_MODELS = {
    "anthropic": {
        "claude-haiku-4-5-20251001":  "Claude Haiku 4.5 (最快最便宜)",
        "claude-sonnet-4-6-20250514": "Claude Sonnet 4.6 (推荐 速度与质量平衡)",
        "claude-opus-4-7-20250514":   "Claude Opus 4.7 (最贵最准确)",
    },
    "deepseek": {
        "deepseek-v4-flash": "DeepSeek-V4-Flash (推荐)",
        "deepseek-v4-pro":   "DeepSeek-V4-Pro",
    },
}

DEFAULT_API_CONFIG = {
    "provider": "deepseek",
    "api_key": "",
    "api_endpoint": "https://api.deepseek.com/v1/chat/completions",
    "api_model": "deepseek-v4-flash",
}

# ---- Quick-Launch presets ----

DEFAULT_QL_PATH = os.path.expanduser("~")

APP_VERSION = "v2.0-preview.12"
APP_UI_VERSION = "v2.0-preview.12"
# The index is a rebuildable cache shared by source and packaged launches.
# Keeping it outside EXE_DIR prevents the two launch modes from drifting apart.
INDEX_DATA_DIR = (
    os.path.join(os.environ["LOCALAPPDATA"], "ClaudeCodeManager")
    if os.environ.get("LOCALAPPDATA")
    else os.path.join(os.path.expanduser("~"), ".claude-code-manager")
)
INDEX_DB_FILE = os.path.join(INDEX_DATA_DIR, "manager-index.sqlite3")
_index_lock = threading.Lock()
_index_last_scan = 0
_index_scan_ttl = 60
_project_cache_lock = threading.Lock()
_mutation_lock = threading.RLock()
_static_cache_lock = threading.Lock()
_static_cache = {}
_desktop_lock = threading.Lock()
_desktop_window = None
_desktop_mode = False
_desktop_ready = threading.Event()

PERMISSION_PRESETS = {
    "read":  {"label": "仅阅读",  "desc": "启动时追加 --allowedTools Read"},
    "write": {"label": "文件编辑", "desc": "启动时追加 --allowedTools Read,Write"},
    "std":   {"label": "标准权限", "desc": "不追加权限参数，使用 Claude Code 默认权限规则"},
    "full":  {"label": "完全控制", "desc": "启动时追加 --permission-mode bypassPermissions"},
}


def runtime_log(message, error=False):
    """Log safely in both console and PyInstaller windowed executables."""
    stream = getattr(sys, "stderr" if error else "stdout", None)
    if stream is not None:
        try:
            stream.write(str(message) + "\n")
            stream.flush()
        except Exception:
            pass
    if error and getattr(sys, "frozen", False):
        try:
            with open(os.path.join(DATA_DIR, "runtime-error.log"), "a", encoding="utf-8") as log:
                log.write(f"[{datetime.now().isoformat(timespec='seconds')}] {message}\n")
        except Exception:
            pass


# =============================================================================
# Data helpers
# =============================================================================

def encode_project_path(path):
    """Encode a filesystem path the same way Claude Code names project folders."""
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.normpath(path))


def _norm_path_key(path):
    if not isinstance(path, str) or not path.strip():
        return ""
    return os.path.normcase(os.path.normpath(path.strip()))


def _is_same_or_child(path, parent):
    path_key = _norm_path_key(path)
    parent_key = _norm_path_key(parent)
    if not path_key or not parent_key:
        return False
    return path_key == parent_key or path_key.startswith(parent_key + os.sep)


def load_path_mappings():
    if os.path.isfile(PATH_MAPPINGS_FILE):
        try:
            with open(PATH_MAPPINGS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"mappings": {}, "updated_at": ""}


def save_path_mappings(data):
    if not isinstance(data, dict):
        data = {"mappings": {}}
    if not isinstance(data.get("mappings"), dict):
        data["mappings"] = {}
    data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(PATH_MAPPINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def set_path_mapping(old_path, new_path):
    old_path = os.path.normpath((old_path or "").strip())
    new_path = os.path.normpath((new_path or "").strip())
    data = load_path_mappings()
    data.setdefault("mappings", {})[old_path] = {
        "old_path": old_path,
        "new_path": new_path,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_path_mappings(data)
    return data["mappings"][old_path]


def remove_path_mapping(old_path):
    data = load_path_mappings()
    data.setdefault("mappings", {}).pop(os.path.normpath((old_path or "").strip()), None)
    save_path_mappings(data)


def apply_path_mapping(path):
    """Map an old path or child path to its new location using the longest prefix."""
    if not isinstance(path, str) or not path.strip():
        return path
    mappings = load_path_mappings().get("mappings", {})
    best = None
    best_len = -1
    for old_path, item in mappings.items():
        new_path = item.get("new_path") if isinstance(item, dict) else ""
        if not old_path or not new_path:
            continue
        if _is_same_or_child(path, old_path):
            old_key = _norm_path_key(old_path)
            if len(old_key) > best_len:
                best = (old_path, new_path)
                best_len = len(old_key)
    if not best:
        return path
    old_path, new_path = best
    try:
        rel = os.path.relpath(os.path.normpath(path), os.path.normpath(old_path))
    except ValueError:
        rel = "."
    if rel in (".", ""):
        return os.path.normpath(new_path)
    return os.path.normpath(os.path.join(new_path, rel))


def mapping_for_path(path):
    mapped = apply_path_mapping(path)
    if mapped == path:
        return None
    return {
        "old_path": os.path.normpath(path),
        "new_path": mapped,
        "exists": os.path.isdir(mapped),
    }


def resolve_project_path(folder_name):
    """
    Resolve the encoded project folder name to a real filesystem path.
    Strategy: read the first recorded 'cwd' from a session file.  Claude Code
    stores resumable sessions by the project directory where the JSONL was
    created, so later cwd changes inside a session must not redefine the
    project path.  Falls back to a best-effort heuristic decode.
    """
    folder_path = os.path.join(PROJECTS_DIR, folder_name)
    if not os.path.isdir(folder_path):
        return folder_name

    # 1. Try to read cwd from a session file (most reliable)
    try:
        files = [
            os.path.join(folder_path, fn)
            for fn in os.listdir(folder_path)
            if fn.endswith(".jsonl")
        ]
        files.sort(key=lambda fp: os.path.getmtime(fp), reverse=True)
        for fp in files:
            entries = _read_jsonl(fp)
            for entry in entries:
                cwd = entry.get("cwd")
                if cwd:
                    return apply_path_mapping(_fix_mojibake(cwd))
    except Exception:
        pass

    # 2. Heuristic decode: split on '--', first segment = drive letter
    parts = folder_name.split("--")
    drive_letter = parts[0].rstrip("-")
    rest = parts[1:]
    segments = [drive_letter + ":"] + rest
    joined = "\\".join(segments)
    # Collapse runs of spaces (likely encoded CJK chars we can't recover)
    joined = re.sub(r" +", " ", joined)
    return apply_path_mapping(joined)


def _safe_project_path(project_id, session_id=None):
    """Validate that project_id/session_id don't escape PROJECTS_DIR.
    Returns (folder_path, session_path) or (None, None) on invalid input."""
    # Reject path traversal characters
    for val in [project_id, session_id or ""]:
        if not val:
            continue
        if ".." in val or "/" in val or "\\" in val:
            return None, None
    folder = os.path.realpath(os.path.join(PROJECTS_DIR, project_id))
    if not folder.startswith(os.path.realpath(PROJECTS_DIR) + os.sep):
        return None, None
    if session_id:
        sf = os.path.realpath(os.path.join(folder, session_id + ".jsonl"))
        if not sf.startswith(folder + os.sep) and sf != os.path.join(folder, session_id + ".jsonl"):
            return None, None
        return folder, sf
    return folder, None


def _read_jsonl(filepath, max_entries=None):
    """Read a JSONL file with encoding fallback (UTF-8 → GBK → GB18030 → replace).
    Returns a list of parsed JSON objects."""
    entries = []
    try:
        with open(filepath, "rb") as f:
            raw = f.read()
        # Try encodings in order; GBK/GB18030 cover Chinese Windows terminal output
        text = None
        for enc in ["utf-8", "gbk", "gb18030"]:
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text = raw.decode("utf-8", errors="replace")

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
                if max_entries and len(entries) >= max_entries:
                    break
            except json.JSONDecodeError:
                continue
    except Exception:
        return entries  # return partial results on error
    return entries


def _fix_mojibake(text):
    """Attempt to recover Chinese text that was GBK-encoded but mistakenly
    stored as if it were Latin-1 characters in a UTF-8 JSON file (mojibake).

    The corruption chain:
      1. Terminal outputs GBK bytes (e.g. 0xB6 0xFE for "二")
      2. Each byte is treated as a Latin-1 character (0xB6=¶, 0xFE=þ)
      3. Some multi-byte Latin-1 sequences happen to also be valid UTF-8
         and become characters like ڶ (U+06B6, Arabic), ҵ (U+04B5, Cyrillic)
      4. Invalid UTF-8 sequences become U+FFFD (�)

    To recover: map each character back to its original byte(s), then
    decode the whole byte-stream as GBK."""
    if not isinstance(text, str) or not text:
        return text
    if "�" not in text:
        return text
    try:
        as_bytes = bytearray()
        for ch in text:
            cp = ord(ch)
            if cp == 0xFFFD:
                as_bytes.append(0x3F)       # lost byte → placeholder
            elif cp <= 0x7F:
                as_bytes.append(cp)         # ASCII was never corrupted
            elif cp <= 0xFF:
                as_bytes.append(cp)         # Latin-1 → original byte
            else:
                as_bytes.extend(ch.encode("utf-8", errors="replace"))
        recovered = as_bytes.decode("gbk", errors="replace")
        if recovered.count("�") < text.count("�"):
            return recovered
    except Exception:
        pass
    return text


def load_session_entries(filepath):
    """Load a session JSONL file; returns (entries, error_string)."""
    try:
        entries = _read_jsonl(filepath)
        return entries, None
    except Exception as e:
        return [], str(e)


def extract_session_meta(entries):
    """Return a metadata dict for a list of session entries."""
    meta = {
        "title": None,
        "created_at": None,
        "cwd": None,
        "cwd_initial": None,
        "cwd_changed": False,
        "git_branch": None,
        "user_msgs": 0,
        "assistant_msgs": 0,
        "total_msgs": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_tokens": 0,
        "total_tokens": 0,
        "model": None,
        "first_user_msg": "",
    }

    for entry in entries:
        t = entry.get("type", "")
        if not meta["created_at"] and entry.get("timestamp"):
            meta["created_at"] = entry["timestamp"]
        entry_cwd = entry.get("cwd")
        if isinstance(entry_cwd, str) and entry_cwd.strip():
            entry_cwd = _fix_mojibake(entry_cwd.strip())
            if not meta["cwd_initial"]:
                meta["cwd_initial"] = entry_cwd
            if meta["cwd"] and os.path.normcase(os.path.normpath(meta["cwd"])) != os.path.normcase(os.path.normpath(entry_cwd)):
                meta["cwd_changed"] = True
            meta["cwd"] = entry_cwd
        if entry.get("gitBranch"):
            meta["git_branch"] = entry.get("gitBranch") or meta["git_branch"]

        if t == "ai-title" and not meta["title"]:
            meta["title"] = entry.get("aiTitle")

        elif t == "system":
            pass

        elif t == "user":
            meta["user_msgs"] += 1
            msg = entry.get("message", {})
            content = msg.get("content", "")
            if isinstance(content, list):
                texts = [b.get("text", "") for b in content if b.get("type") == "text"]
                first_text = " ".join(texts)
            elif isinstance(content, str):
                first_text = content
            else:
                first_text = ""
            if not meta["first_user_msg"] and first_text.strip():
                meta["first_user_msg"] = _fix_mojibake(first_text.strip())[:500]

        elif t == "assistant":
            meta["assistant_msgs"] += 1
            msg = entry.get("message", {})
            usage = msg.get("usage", {})
            if usage:
                meta["input_tokens"] += usage.get("input_tokens", 0)
                meta["output_tokens"] += usage.get("output_tokens", 0)
                meta["cache_tokens"] += usage.get("cache_creation_input_tokens", 0)
                meta["cache_tokens"] += usage.get("cache_read_input_tokens", 0)
            if not meta["model"]:
                meta["model"] = msg.get("model")

    meta["total_msgs"] = meta["user_msgs"] + meta["assistant_msgs"]
    meta["total_tokens"] = meta["input_tokens"] + meta["output_tokens"]

    # Human-readable created_at
    ts = meta["created_at"]
    if ts:
        try:
            ts_num = float(ts) if not isinstance(ts, (int, float)) else ts
            dt = datetime.fromtimestamp(ts_num / 1000)
            meta["created_at"] = dt.strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, OverflowError, ValueError, TypeError):
            meta["created_at"] = str(ts)
    else:
        meta["created_at"] = ""

    if not meta["model"]:
        meta["model"] = "unknown"
    if not meta["title"]:
        meta["title"] = "未命名会话"

    return meta


# Simple in-memory cache for project scans
_project_cache = {"data": None, "time": 0}
_project_cache_ttl = 3  # seconds


def invalidate_project_cache():
    """Clear the in-memory project scan cache after destructive changes."""
    with _project_cache_lock:
        _project_cache["data"] = None
        _project_cache["time"] = 0


def get_cached_projects():
    """Return cached or freshly scanned project list."""
    now = time.time()
    with _project_cache_lock:
        if _project_cache["data"] is not None and (now - _project_cache["time"]) < _project_cache_ttl:
            return _project_cache["data"]
        data = _scan_all_projects()
        _project_cache["data"] = data
        _project_cache["time"] = now
        return data


def ensure_v2_index(force=False):
    """Keep the SQLite index fresh; force bypasses the TTL but preserves file-level caching."""
    global _index_last_scan
    now = time.time()
    if not force and now - _index_last_scan < _index_scan_ttl:
        return {"skipped": True}
    with _index_lock:
        now = time.time()
        if not force and now - _index_last_scan < _index_scan_ttl:
            return {"skipped": True}
        stats = v2_index.scan_incremental(INDEX_DB_FILE, PROJECTS_DIR, _read_jsonl, _fix_mojibake, force=False)
        _index_last_scan = time.time()
        return stats


def rebuild_v2_index(full=False):
    global _index_last_scan
    with _index_lock:
        if full:
            stats = v2_index.rebuild_index(INDEX_DB_FILE, PROJECTS_DIR, _read_jsonl, _fix_mojibake)
        else:
            stats = v2_index.scan_incremental(INDEX_DB_FILE, PROJECTS_DIR, _read_jsonl, _fix_mojibake)
        _index_last_scan = time.time()
        return stats


def _trash_stamp():
    return datetime.now().strftime("%Y%m%d%H%M%S")


def _write_trash_meta(dest_path, meta):
    meta_path = dest_path + ".meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def _unique_trash_path(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    for idx in range(2, 1000):
        candidate = f"{base}_{idx}{ext}"
        if not os.path.exists(candidate):
            return candidate
    raise RuntimeError("无法生成唯一回收站路径")


def attach_session_summaries(items):
    stored = load_session_summaries()
    for item in items or []:
        session_id = item.get("id", item.get("session_id", ""))
        keys = [
            item.get("record_project_id", "") + "/" + session_id,
            item.get("project_id", "") + "/" + session_id,
        ]
        item["ai_summary"] = next((stored[key].get("summary", "") for key in keys if key in stored), "")
    return items


def _map_entry_cwd(entry, old_path, new_path):
    if not isinstance(entry, dict):
        return entry, False
    cwd = entry.get("cwd")
    if isinstance(cwd, str) and _is_same_or_child(cwd, old_path):
        entry = dict(entry)
        entry["cwd"] = apply_specific_path_mapping(cwd, old_path, new_path)
        return entry, True
    return entry, False


def apply_specific_path_mapping(path, old_path, new_path):
    try:
        rel = os.path.relpath(os.path.normpath(path), os.path.normpath(old_path))
    except ValueError:
        rel = "."
    if rel in (".", ""):
        return os.path.normpath(new_path)
    return os.path.normpath(os.path.join(new_path, rel))


def write_migrated_jsonl(src_path, dest_path, old_path, new_path):
    changed = 0
    with open(src_path, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8", "replace")
    with open(dest_path, "w", encoding="utf-8", newline="\n") as out:
        for line in text.splitlines():
            try:
                entry = json.loads(line)
                entry, did_change = _map_entry_cwd(entry, old_path, new_path)
                if did_change:
                    changed += 1
                out.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
            except Exception:
                out.write(line + "\n")
    return changed


def sync_project_cache_keys(old_project_id, new_project_id, moved_session_ids, remove_old_description=False):
    descs = load_project_descriptions()
    if old_project_id in descs and new_project_id not in descs:
        descs[new_project_id] = descs[old_project_id]
    if remove_old_description and old_project_id in descs:
        descs.pop(old_project_id, None)
    save_project_descriptions(descs)

    sums = load_session_summaries()
    for session_id in moved_session_ids:
        old_key = old_project_id + "/" + session_id
        new_key = new_project_id + "/" + session_id
        if old_key in sums and new_key not in sums:
            sums[new_key] = sums[old_key]
        if old_key in sums:
            sums.pop(old_key, None)
    save_session_summaries(sums)


def migrate_project_records(project_id, new_path):
    if not project_id or not _VALID_ID.match(project_id):
        return {"ok": False, "message": "无效的 project_id"}
    new_path = os.path.normpath((new_path or "").strip())
    if not new_path or not os.path.isdir(new_path):
        return {"ok": False, "message": "新路径不存在: " + new_path}

    source_dir, _ = _safe_project_path(project_id)
    if not source_dir or not os.path.isdir(source_dir):
        return {"ok": False, "message": "Claude 记录项目目录不存在"}

    old_path = resolve_project_path(project_id)
    # resolve_project_path may already apply a saved mapping; recover the source cwd from JSONL when possible.
    raw_old_path = old_path
    for fn in sorted(os.listdir(source_dir)):
        if fn.endswith(".jsonl"):
            entries = _read_jsonl(os.path.join(source_dir, fn), max_entries=80)
            for entry in entries:
                cwd = entry.get("cwd")
                if isinstance(cwd, str) and cwd.strip():
                    raw_old_path = _fix_mojibake(cwd.strip())
                    break
            if raw_old_path:
                break

    new_project_id = encode_project_path(new_path)
    target_dir = os.path.join(PROJECTS_DIR, new_project_id)
    os.makedirs(target_dir, exist_ok=True)

    backup_dir = os.path.join(MIGRATIONS_DIR, _trash_stamp() + "_" + project_id + "_to_" + new_project_id)
    os.makedirs(backup_dir, exist_ok=True)

    moved = []
    failed = []
    cwd_rewrites = 0
    for fn in sorted(os.listdir(source_dir)):
        if not fn.endswith(".jsonl"):
            continue
        session_id = fn[:-6]
        src = os.path.join(source_dir, fn)
        dest = os.path.join(target_dir, fn)
        if os.path.exists(dest):
            failed.append({"session_id": session_id, "error": "目标会话已存在"})
            continue
        tmp = dest + ".tmp"
        try:
            changed = write_migrated_jsonl(src, tmp, raw_old_path, new_path)
            os.replace(tmp, dest)
            shutil.move(src, os.path.join(backup_dir, fn))
            moved.append(session_id)
            cwd_rewrites += changed
        except Exception as e:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            failed.append({"session_id": session_id, "error": str(e)})

    remaining_jsonl = [fn for fn in os.listdir(source_dir) if fn.endswith(".jsonl")]
    if not remaining_jsonl:
        try:
            os.rmdir(source_dir)
        except OSError:
            pass

    set_path_mapping(raw_old_path, new_path)
    sync_project_cache_keys(project_id, new_project_id, moved, remove_old_description=not remaining_jsonl)
    _write_trash_meta(backup_dir, {
        "type": "migration-backup",
        "old_project_id": project_id,
        "new_project_id": new_project_id,
        "old_path": raw_old_path,
        "new_path": new_path,
        "moved_sessions": moved,
        "failed": failed,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    invalidate_project_cache()
    ensure_v2_index(force=True)
    return {
        "ok": len(moved) > 0 and not failed,
        "message": f"迁移完成: {len(moved)} 个会话成功, {len(failed)} 个失败",
        "old_project_id": project_id,
        "new_project_id": new_project_id,
        "old_path": raw_old_path,
        "new_path": new_path,
        "moved": len(moved),
        "failed": len(failed),
        "errors": failed,
        "backup_dir": backup_dir,
        "cwd_rewrites": cwd_rewrites,
    }


def _scan_all_projects():
    """Return a list of project dicts, each with a list of sessions."""
    if not os.path.isdir(PROJECTS_DIR):
        return []

    projects = []
    for folder_name in sorted(os.listdir(PROJECTS_DIR)):
        folder_path = os.path.join(PROJECTS_DIR, folder_name)
        if not os.path.isdir(folder_path):
            continue

        sessions = []
        total_tokens = 0
        total_msgs = 0
        last_active = ""
        session_count = 0
        project_cwd = ""

        for fn in sorted(os.listdir(folder_path)):
            if not fn.endswith(".jsonl"):
                continue
            session_count += 1
            fp = os.path.join(folder_path, fn)
            entries, err = load_session_entries(fp)
            if err or not entries:
                continue
            sm = extract_session_meta(entries)
            total_tokens += sm["total_tokens"]
            total_msgs += sm["total_msgs"]
            if sm["created_at"] and sm["created_at"] > last_active:
                last_active = sm["created_at"]
            if not project_cwd and sm.get("cwd"):
                project_cwd = sm["cwd"]
            sessions.append({"id": fn.replace(".jsonl", ""), **sm})

        sessions.sort(key=lambda s: s["created_at"], reverse=True)
        if sessions and sessions[0].get("cwd"):
            project_cwd = sessions[0]["cwd"]
        real_path = resolve_project_path(folder_name)

        projects.append({
            "id": folder_name,
            "name": real_path,
            "cwd": project_cwd or real_path,
            "session_count": session_count,
            "total_tokens": total_tokens,
            "total_msgs": total_msgs,
            "last_active": last_active,
            "sessions": sessions,
        })

    projects.sort(key=lambda p: p["last_active"], reverse=True)
    return projects


# =============================================================================
# Chinese summarization
# =============================================================================

def generate_chinese_summary(meta):
    """Generate a concise Chinese summary from session metadata (no API)."""
    parts = []
    if meta.get("title"):
        parts.append(f"📋 任务：{meta['title']}")
    first = meta.get("first_user_msg", "")
    if first:
        cleaned = first.strip()[:120]
        if len(first) > 120:
            cleaned += "…"
        parts.append(f"💬 描述：{cleaned}")
    parts.append(
        f"📊 统计：{meta['total_msgs']} 条消息 · {meta['model']} · {meta['total_tokens']:,} tokens"
    )
    if meta.get("created_at"):
        parts.append(f"🕐 时间：{meta['created_at']}")
    return "\n".join(parts)


def generate_project_summary(project):
    """Generate a concise Chinese project summary."""
    sessions = project.get("sessions", [])
    titles = [s.get("title", "") for s in sessions if s.get("title")]
    parts = [f"📁 项目：{project['name']}"]
    if titles:
        parts.append(f"📋 主要任务：{'、'.join(titles[:5])}")
        if len(titles) > 5:
            parts.append(f"  ...及其他 {len(titles) - 5} 项任务")
    parts.append(
        f"📊 统计：{len(sessions)} 个会话 · {project['total_msgs']} 条消息 · {project['total_tokens']:,} tokens"
    )
    if project.get("last_active"):
        parts.append(f"🕐 最近活跃：{project['last_active']}")
    return "\n".join(parts)


# =============================================================================
# AI project descriptions storage
# =============================================================================

def load_project_descriptions():
    """Load stored AI-generated project descriptions."""
    if os.path.isfile(DESCRIPTIONS_FILE):
        try:
            with open(DESCRIPTIONS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_project_descriptions(descriptions):
    """Save project descriptions to disk."""
    with open(DESCRIPTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(descriptions, f, ensure_ascii=False, indent=2)


def get_summary_model():
    """Get the configured summarization model from API config."""
    return _ai_config.get("api_model", "deepseek-v4-flash")


def build_project_description_text(project):
    """Build input text for AI to describe a project."""
    sessions = project.get("sessions", [])
    lines = ["项目路径: " + project.get("name", ""), "会话数量: " + str(len(sessions))]
    if sessions:
        lines.append("\n会话列表:")
        for s in sessions[:15]:
            title = s.get("title", "未命名")
            msg = s.get("first_user_msg", "")[:120]
            lines.append("  - " + str(title))
            if msg:
                lines.append("    首条消息: " + msg)
    return "\n".join(lines)


def generate_project_description(project):
    """Use configured AI to generate a Chinese project description."""
    if not is_ai_available():
        return None
    text = build_project_description_text(project)
    return ai_describe_project(text)


# =============================================================================
# AI API integration (Anthropic + DeepSeek)
# =============================================================================

def _read_api_config(path):
    """Read an API configuration dictionary without leaking its secret."""
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
        return saved if isinstance(saved, dict) else None
    except Exception:
        return None


def legacy_api_config_candidates():
    """Return old web-version config locations eligible for desktop migration."""
    if not getattr(sys, "frozen", False):
        return []
    current = os.path.normcase(os.path.realpath(API_CONFIG_FILE))
    candidates = [
        os.path.join(os.path.dirname(EXE_DIR), "data", "api-config.json"),
        os.path.join(os.getcwd(), "data", "api-config.json"),
    ]
    unique = []
    seen = {current}
    for candidate in candidates:
        normalized = os.path.normcase(os.path.realpath(candidate))
        if normalized not in seen:
            seen.add(normalized)
            unique.append(candidate)
    return unique


def _migrate_api_model(cfg):
    old_new = {"deepseek-chat": "deepseek-v4-flash", "deepseek-reasoner": "deepseek-v4-pro"}
    if cfg.get("api_model") in old_new:
        cfg["api_model"] = old_new[cfg["api_model"]]
    return cfg


def load_api_config(config_path=None, legacy_candidates=None):
    """Load API config and recover the old web-version config when needed."""
    config_path = config_path or API_CONFIG_FILE
    cfg = dict(DEFAULT_API_CONFIG)
    saved = _read_api_config(config_path)
    if saved:
        cfg.update(saved)

    if not str(cfg.get("api_key", "")).strip():
        candidates = legacy_api_config_candidates() if legacy_candidates is None else legacy_candidates
        for candidate in candidates:
            legacy = _read_api_config(candidate)
            if not legacy or not str(legacy.get("api_key", "")).strip():
                continue
            for key in ("provider", "api_key", "api_endpoint", "api_model", "ql_path", "ql_perm"):
                if key in legacy and legacy[key] not in (None, ""):
                    cfg[key] = legacy[key]
            cfg = _migrate_api_model(cfg)
            try:
                save_api_config(cfg, config_path)
                runtime_log("Recovered API configuration from the legacy web data directory.")
            except OSError as exc:
                runtime_log(f"Could not persist migrated API configuration: {exc}", error=True)
            break
    return _migrate_api_model(cfg)


def save_api_config(cfg, config_path=None):
    """Atomically save API provider config to disk."""
    config_path = config_path or API_CONFIG_FILE
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    temp_path = config_path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_path, config_path)


def masked_api_key():
    """Return a non-sensitive hint so users can recognize a retained key."""
    key = str(_ai_config.get("api_key", "")).strip()
    if not key:
        return ""
    return "••••••••" + key[-4:]


_ai_config = load_api_config()


def is_ai_available():
    return bool(_ai_config.get("api_key", ""))


def is_api_error(text):
    return isinstance(text, str) and text.startswith("[API Error")


def mask_sensitive_config(value):
    if isinstance(value, dict):
        masked = {}
        for key, item in value.items():
            key_upper = str(key).upper()
            if any(word in key_upper for word in ("TOKEN", "KEY", "SECRET", "PASSWORD", "AUTH")):
                masked[key] = "***已隐藏***" if item else item
            else:
                masked[key] = mask_sensitive_config(item)
        return masked
    if isinstance(value, list):
        return [mask_sensitive_config(item) for item in value]
    return value


def _extract_ai_response_text(result):
    """Extract useful text from OpenAI-compatible or Anthropic responses."""
    if not isinstance(result, dict):
        return ""
    if isinstance(result.get("content"), list) and result["content"]:
        part = result["content"][0]
        if isinstance(part, dict):
            return (part.get("text") or "").strip()
    choices = result.get("choices") or []
    if choices:
        msg = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
        content = (msg.get("content") or "").strip()
        if content:
            return content
        reasoning = (msg.get("reasoning_content") or "").strip()
        if reasoning:
            return reasoning
    return ""


def call_ai_api(prompt, max_tokens=500):
    """Call the configured AI provider and return the response text."""
    cfg = _ai_config
    if not cfg.get("api_key"):
        return None

    provider = cfg["provider"]
    model = cfg.get("api_model", "deepseek-v4-flash")
    api_key = cfg["api_key"]
    endpoint = cfg.get("api_endpoint", "")

    try:
        if provider == "anthropic":
            body = json.dumps({
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }).encode()
            req = urllib.request.Request(
                endpoint or "https://api.anthropic.com/v1/messages",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read())
            text = _extract_ai_response_text(result)
            return text or "[API Error: API 返回空内容]"

        else:  # deepseek (OpenAI-compatible API)
            body = json.dumps({
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }).encode()
            req = urllib.request.Request(
                endpoint or "https://api.deepseek.com/v1/chat/completions",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + api_key,
                },
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read())
            text = _extract_ai_response_text(result)
            return text or "[API Error: API 返回空内容]"

    except urllib.error.HTTPError as e:
        try:
            body = e.read(600).decode("utf-8", "replace")
        except Exception:
            body = ""
        return "[API Error: HTTP " + str(e.code) + (" " + body if body else "") + "]"
    except Exception as e:
        return "[API Error: " + str(e) + "]"


def ai_summarize_session(text, max_length=150):
    """Generate a focused summary of a single conversation."""
    prompt = (
        "下面是一个 Claude Code 会话的对话记录。请用一段中文（" + str(max_length) + "字以内）总结：\n"
        "1) 这个会话主要讨论了什么\n"
        "2) 具体做了什么操作或解决了什么问题\n"
        "3) 最终结果或输出是什么\n\n"
        "简明扼要，不要套话。\n\n" +
        text[:4000] + "\n\n总结："
    )
    return call_ai_api(prompt, max_tokens=700)


def ai_describe_project(project_info):
    """Generate a broad overview of what topics a project covers."""
    prompt = (
        "下面是一个项目目录下所有 Claude Code 会话的标题和首条消息。\n"
        "请用 2-3 句中文简要概括：这个目录下的对话主要涉及哪些方面的内容。\n"
        "像在给一个开发者做项目速览，让他一眼知道这里面讨论过什么话题。\n\n" +
        project_info[:2500] + "\n\n项目概览："
    )
    return call_ai_api(prompt, max_tokens=450)


def load_session_summaries():
    """Load stored AI session summaries."""
    if os.path.isfile(SESSION_SUMMARIES_FILE):
        try:
            with open(SESSION_SUMMARIES_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_session_summaries(summaries):
    """Save all AI session summaries."""
    with open(SESSION_SUMMARIES_FILE, "w", encoding="utf-8") as f:
        json.dump(summaries, f, ensure_ascii=False, indent=2)


def save_session_summary(project_id, session_id, summary):
    """Save an AI session summary."""
    summaries = load_session_summaries()
    key = project_id + "/" + session_id
    summaries[key] = {
        "summary": summary.strip(),
        "model": _ai_config.get("api_model", ""),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_session_summaries(summaries)


# =============================================================================
# Claude Code CLI detection & launching
# =============================================================================

def find_claude():
    """Locate the claude executable. Returns path string or None."""
    claude_path = shutil.which("claude")
    if claude_path:
        return claude_path
    # Fallback: common locations on Windows
    fallbacks = [
        os.path.expanduser("~/AppData/Local/npm/claude.cmd"),
        os.path.expanduser("~/AppData/Roaming/npm/claude.cmd"),
        os.path.expanduser("~/AppData/Local/fnm/node-bin/claude"),
        shutil.which("npx"),
    ]
    for fb in fallbacks:
        if fb and os.path.isfile(fb):
            return fb
    return None


CLAUDE_EXE = find_claude()


PERMISSION_TOOLS = {
    "read":  "Read",
    "write": "Read,Write",
    "std":   None,
    "full":  None,   # uses --permission-mode bypassPermissions instead
}

def launch_claude(workspace_path, resume=False, session_id=None, permission=None):
    """Launch Claude Code in a new terminal window at the given path."""
    if not CLAUDE_EXE:
        return False, "未找到 claude 命令"
    if not os.path.isdir(workspace_path):
        return False, "目录不存在: " + workspace_path
    try:
        cmd = [CLAUDE_EXE]
        if resume and session_id:
            cmd.extend(["--resume", session_id])
        elif resume:
            cmd.append("--resume")
        if permission:
            if permission == "full":
                cmd.extend(["--permission-mode", "bypassPermissions"])
            elif PERMISSION_TOOLS.get(permission):
                cmd.extend(["--allowedTools", PERMISSION_TOOLS[permission]])
        if os.name == "nt":
            subprocess.Popen(
                cmd,
                cwd=workspace_path,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
                shell=False,
            )
        elif sys.platform == "darwin":
            subprocess.Popen(
                ["open", "-a", "Terminal"] + cmd,
                cwd=workspace_path,
            )
        else:
            subprocess.Popen(
                ["x-terminal-emulator", "-e"] + cmd,
                cwd=workspace_path,
            )
        return True, "Claude Code 已启动"
    except Exception as e:
        return False, str(e)


def open_directory_in_file_manager(path, opener=None):
    """Open an existing directory in the platform file manager without a shell."""
    if not isinstance(path, str) or not path.strip():
        return False, "缺少项目目录", ""
    normalized = os.path.realpath(os.path.expanduser(path.strip()))
    if not os.path.isdir(normalized):
        return False, "目录不存在: " + normalized, normalized
    try:
        if opener is not None:
            opener(normalized)
        elif os.name == "nt":
            os.startfile(normalized)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", normalized], shell=False)
        else:
            subprocess.Popen(["xdg-open", normalized], shell=False)
        return True, "已在文件资源管理器中打开项目目录", normalized
    except Exception as exc:
        return False, "无法打开项目目录: " + str(exc), normalized


def resolve_session_launch_path(project_id, session_id, fallback_path=""):
    """Resolve the best launch directory for a session resume."""
    if not project_id or not session_id:
        return fallback_path
    if not _VALID_ID.match(project_id) or not _VALID_ID.match(session_id):
        return fallback_path
    _, session_path = _safe_project_path(project_id, session_id)
    if not session_path or not os.path.isfile(session_path):
        return fallback_path
    entries, err = load_session_entries(session_path)
    if err or not entries:
        return fallback_path
    meta = extract_session_meta(entries)
    project_path = resolve_project_path(project_id)
    candidates = [
        meta.get("cwd_initial"),
        project_path,
        fallback_path,
        meta.get("cwd"),
    ]
    mapped_candidates = []
    for candidate in candidates:
        if candidate:
            mapped = apply_path_mapping(candidate)
            if mapped != candidate:
                mapped_candidates.append(mapped)
    candidates.extend(mapped_candidates)
    seen = set()
    for candidate in candidates:
        if not candidate:
            continue
        norm = os.path.normcase(os.path.normpath(candidate))
        if norm in seen:
            continue
        seen.add(norm)
        if candidate and os.path.isdir(candidate):
            return candidate
    return fallback_path


def resume_migration_hint(project_id, session_id):
    """Return migration guidance when a mapped session cannot resume yet."""
    if not project_id or not session_id:
        return None
    if not _VALID_ID.match(project_id) or not _VALID_ID.match(session_id):
        return None
    _, session_path = _safe_project_path(project_id, session_id)
    if not session_path or not os.path.isfile(session_path):
        return None
    entries, err = load_session_entries(session_path)
    if err or not entries:
        return None
    meta = extract_session_meta(entries)
    old_path = meta.get("cwd_initial") or meta.get("cwd") or ""
    mapped_path = apply_path_mapping(old_path)
    if not old_path or mapped_path == old_path:
        return None
    new_project_id = encode_project_path(mapped_path)
    _, new_session_path = _safe_project_path(new_project_id, session_id)
    if new_session_path and os.path.isfile(new_session_path):
        return None
    if os.path.isdir(mapped_path):
        return {
            "old_path": old_path,
            "new_path": mapped_path,
            "old_project_id": project_id,
            "new_project_id": new_project_id,
            "session_id": session_id,
        }
    return None


# =============================================================================
# HTTP Server
# =============================================================================

class ManagerHTTPServer(ThreadingHTTPServer):
    """Concurrent loopback server tuned for a desktop UI workload."""

    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False
    request_queue_size = 32


class Handler(BaseHTTPRequestHandler):

    protocol_version = "HTTP/1.1"

    # ── Routing ────────────────────────────────────────────────────────────

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        routes = {
            "/":                    lambda: self._serve_static("index.html", "text/html; charset=utf-8"),
            "/api/stats":           self._handle_stats,
            "/api/projects":        self._handle_projects,
            "/api/config":          self._handle_config,
            "/api/api-key-status":  self._handle_api_key_status,
            "/api/claude-status":   self._handle_claude_status,
            "/api/descriptions":    self._handle_get_descriptions,
            "/api/pick-folder":     self._handle_pick_folder,
            "/api/desktop/activate": self._handle_desktop_activate,
        }

        # Dynamic routes
        if path.startswith("/static/"):
            self._serve_static(path[len("/static/"):])
        elif path.startswith("/api/v2/"):
            self._handle_v2_get(path, qs)
        elif path.startswith("/api/project/"):
            self._handle_project_detail(path[len("/api/project/"):])
        elif path.startswith("/api/session/"):
            parts = path[len("/api/session/"):].split("/", 1)
            if len(parts) == 2:
                self._handle_session(parts[0], parts[1])
            else:
                self._send_json({"error": "bad request"}, 400)
        elif path == "/api/summarize":
            self._handle_summarize(qs)
        elif path == "/api/search":
            self._handle_search(qs)
        elif path in routes:
            routes[path]()
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_POST_BODY:
            self.close_connection = True
            self._send_json({"error": "payload too large"}, 413)
            return
        parsed = urllib.parse.urlparse(self.path)
        with _mutation_lock:
            self._dispatch_post(parsed.path)

    def _dispatch_post(self, path):
        if path == "/api/v2/reindex":
            self._handle_v2_reindex()
        elif path == "/api/v2/trash-project":
            self._handle_v2_trash_project()
        elif path == "/api/v2/trash-session":
            self._handle_v2_trash_session()
        elif path == "/api/v2/trash-projects":
            self._handle_v2_trash_projects()
        elif path == "/api/v2/trash-sessions":
            self._handle_v2_trash_sessions()
        elif path == "/api/v2/path-map":
            self._handle_v2_path_map()
        elif path == "/api/v2/path-map-delete":
            self._handle_v2_path_map_delete()
        elif path == "/api/v2/migrate-project":
            self._handle_v2_migrate_project()
        elif path == "/api/open-claude":
            self._handle_open_claude()
        elif path == "/api/open-directory":
            self._handle_open_directory()
        elif path == "/api/quick-launch":
            self._handle_quick_launch()
        elif path == "/api/describe-project":
            self._handle_describe_project()
        elif path == "/api/describe-all":
            self._handle_describe_all()
        elif path == "/api/set-api-config":
            self._handle_set_api_config()
        elif path == "/api/delete-project":
            self._handle_delete_project()
        elif path == "/api/delete-projects":
            self._handle_delete_projects()
        elif path == "/api/delete-session":
            self._handle_delete_session()
        elif path == "/api/delete-sessions":
            self._handle_delete_sessions()
        elif path == "/api/summarize-all":
            self._handle_summarize_all()
        elif path == "/api/shutdown":
            self._handle_shutdown()
        else:
            self._discard_request_body()
            self._send_json({"error": "not found"}, 404)

    # ── API handlers ───────────────────────────────────────────────────────

    def _q_int(self, qs, name, default, minimum=0, maximum=500):
        try:
            value = int((qs.get(name) or [default])[0])
        except Exception:
            value = default
        return max(minimum, min(maximum, value))

    def _handle_v2_get(self, path, qs):
        try:
            ensure_v2_index()
            subpath = path[len("/api/v2/"):]
            if subpath == "dashboard":
                data = v2_index.dashboard(INDEX_DB_FILE)
                attach_session_summaries(data.get("recent_sessions", []))
                self._send_json(data)
                return
            if subpath == "projects":
                self._send_json(v2_index.list_projects(
                    INDEX_DB_FILE,
                    q=((qs.get("q") or [""])[0]).strip(),
                    drive=((qs.get("drive") or [""])[0]).strip(),
                    sort=((qs.get("sort") or ["active"])[0]).strip(),
                    path_prefix=((qs.get("path_prefix") or [""])[0]).strip(),
                    limit=self._q_int(qs, "limit", 60, 1, 200),
                    offset=self._q_int(qs, "offset", 0, 0, 1000000),
                ))
                return
            if subpath == "project-dirs":
                self._send_json(v2_index.project_dirs(
                    INDEX_DB_FILE,
                    prefix=((qs.get("prefix") or [""])[0]).strip(),
                ))
                return
            if subpath == "path-mappings":
                self._send_json(load_path_mappings())
                return
            if subpath == "sessions":
                data = v2_index.list_sessions(
                    INDEX_DB_FILE,
                    q=((qs.get("q") or [""])[0]).strip(),
                    limit=self._q_int(qs, "limit", 80, 1, 200),
                    offset=self._q_int(qs, "offset", 0, 0, 1000000),
                )
                attach_session_summaries(data.get("items", []))
                self._send_json(data)
                return
            if subpath == "orphan-history-sessions":
                self._send_json(v2_index.list_orphan_history_sessions(
                    INDEX_DB_FILE,
                    q=((qs.get("q") or [""])[0]).strip(),
                    include_command_only=((qs.get("include_command_only") or [""])[0]).lower() in ("1", "true", "yes"),
                    limit=self._q_int(qs, "limit", 80, 1, 200),
                    offset=self._q_int(qs, "offset", 0, 0, 1000000),
                ))
                return
            if subpath == "search":
                self._send_json(v2_index.search(
                    INDEX_DB_FILE,
                    q=((qs.get("q") or [""])[0]).strip(),
                    limit=self._q_int(qs, "limit", 50, 1, 100),
                    offset=self._q_int(qs, "offset", 0, 0, 1000000),
                ))
                return
            if subpath.startswith("project/") and subpath.endswith("/sessions"):
                project_id = subpath[len("project/"):-len("/sessions")]
                if not _VALID_ID.match(project_id):
                    self._send_json({"error": "invalid project id"}, 400)
                    return
                data = v2_index.list_sessions(
                    INDEX_DB_FILE,
                    project_id=project_id,
                    q=((qs.get("q") or [""])[0]).strip(),
                    limit=self._q_int(qs, "limit", 80, 1, 200),
                    offset=self._q_int(qs, "offset", 0, 0, 1000000),
                )
                attach_session_summaries(data.get("items", []))
                self._send_json(data)
                return
            if subpath.startswith("session/"):
                parts = subpath[len("session/"):].split("/", 1)
                if len(parts) != 2 or not _VALID_ID.match(parts[0]) or not _VALID_ID.match(parts[1]):
                    self._send_json({"error": "invalid session path"}, 400)
                    return
                detail = v2_index.session_detail(
                    INDEX_DB_FILE,
                    parts[0],
                    parts[1],
                    limit=self._q_int(qs, "limit", 160, 1, 300),
                    offset=self._q_int(qs, "offset", 0, 0, 1000000),
                    role=((qs.get("role") or [""])[0]).strip(),
                )
                if not detail:
                    self._send_json({"error": "session not found"}, 404)
                    return
                stored = load_session_summaries()
                record_project_id = detail["session"].get("record_project_id") or parts[0]
                detail["session"]["ai_summary"] = stored.get(
                    record_project_id + "/" + parts[1],
                    stored.get(parts[0] + "/" + parts[1], {}),
                ).get("summary", "")
                self._send_json(detail)
                return
            self._send_json({"error": "not found"}, 404)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_v2_reindex(self):
        try:
            data = self._read_json_body()
            stats = rebuild_v2_index(full=bool(data.get("full")))
            invalidate_project_cache()
            self._send_json({"ok": True, "stats": stats})
        except Exception as e:
            self._send_json({"ok": False, "message": str(e)}, 500)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_POST_BODY:
            raise ValueError("payload too large")
        return json.loads(self.rfile.read(length) or b"{}")

    def _discard_request_body(self):
        """Consume an optional body so HTTP/1.1 can safely reuse the connection."""
        length = min(int(self.headers.get("Content-Length", 0)), MAX_POST_BODY)
        if length:
            self.rfile.read(length)

    def _handle_v2_path_map(self):
        try:
            data = self._read_json_body()
            old_path = os.path.normpath((data.get("old_path") or "").strip())
            new_path = os.path.normpath((data.get("new_path") or "").strip())
        except Exception:
            self._send_json({"ok": False, "message": "请求格式错误"}, 400)
            return
        if not old_path or not new_path:
            self._send_json({"ok": False, "message": "缺少 old_path 或 new_path"}, 400)
            return
        if not os.path.isdir(new_path):
            self._send_json({"ok": False, "message": "新路径不存在: " + new_path}, 400)
            return
        mapping = set_path_mapping(old_path, new_path)
        invalidate_project_cache()
        self._send_json({"ok": True, "mapping": mapping, "message": "路径映射已保存"})

    def _handle_v2_path_map_delete(self):
        try:
            data = self._read_json_body()
            old_path = data.get("old_path") or ""
        except Exception:
            self._send_json({"ok": False, "message": "请求格式错误"}, 400)
            return
        if not old_path:
            self._send_json({"ok": False, "message": "缺少 old_path"}, 400)
            return
        remove_path_mapping(old_path)
        invalidate_project_cache()
        self._send_json({"ok": True, "message": "路径映射已删除"})

    def _handle_v2_migrate_project(self):
        try:
            data = self._read_json_body()
            project_id = data.get("project_id") or ""
            new_path = data.get("new_path") or ""
        except Exception:
            self._send_json({"ok": False, "message": "请求格式错误"}, 400)
            return
        result = migrate_project_records(project_id, new_path)
        self._send_json(result, 200 if result.get("ok") or result.get("moved", 0) else 400)

    def _handle_v2_trash_project(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length))
            project_id = data.get("project_id", "")
        except Exception:
            self._send_json({"ok": False, "message": "请求格式错误"}, 400)
            return
        if not project_id or not _VALID_ID.match(project_id):
            self._send_json({"ok": False, "message": "无效的 project_id"}, 400)
            return
        folder_path, _ = _safe_project_path(project_id)
        if not folder_path or not os.path.isdir(folder_path):
            self._send_json({"ok": False, "message": "项目不存在"}, 404)
            return
        try:
            dest_dir = os.path.join(TRASH_DIR, "projects")
            os.makedirs(dest_dir, exist_ok=True)
            dest = _unique_trash_path(os.path.join(dest_dir, project_id + "_" + _trash_stamp()))
            shutil.move(folder_path, dest)
            _write_trash_meta(dest, {
                "type": "project",
                "project_id": project_id,
                "original_path": folder_path,
                "trashed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
            invalidate_project_cache()
            ensure_v2_index(force=True)
            self._send_json({"ok": True, "message": "项目已移到回收站", "trash_path": dest})
        except Exception as e:
            self._send_json({"ok": False, "message": str(e)}, 500)

    def _handle_v2_trash_session(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length))
            project_id = data.get("project_id", "")
            session_id = data.get("session_id", "")
        except Exception:
            self._send_json({"ok": False, "message": "请求格式错误"}, 400)
            return
        if not project_id or not session_id or not _VALID_ID.match(project_id) or not _VALID_ID.match(session_id):
            self._send_json({"ok": False, "message": "无效的项目或会话 ID"}, 400)
            return
        project_id = v2_index.record_project_id(INDEX_DB_FILE, project_id, session_id)
        _, filepath = _safe_project_path(project_id, session_id)
        if not filepath or not os.path.isfile(filepath):
            self._send_json({"ok": False, "message": "会话文件不存在"}, 404)
            return
        try:
            dest_dir = os.path.join(TRASH_DIR, "sessions", project_id)
            os.makedirs(dest_dir, exist_ok=True)
            dest = _unique_trash_path(os.path.join(dest_dir, session_id + "_" + _trash_stamp() + ".jsonl"))
            shutil.move(filepath, dest)
            _write_trash_meta(dest, {
                "type": "session",
                "project_id": project_id,
                "session_id": session_id,
                "original_path": filepath,
                "trashed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
            invalidate_project_cache()
            ensure_v2_index(force=True)
            self._send_json({"ok": True, "message": "会话已移到回收站", "trash_path": dest})
        except Exception as e:
            self._send_json({"ok": False, "message": str(e)}, 500)

    def _handle_v2_trash_projects(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length))
            project_ids = data.get("project_ids", [])
        except Exception:
            self._send_json({"ok": False, "message": "请求格式错误"}, 400)
            return
        if not isinstance(project_ids, list) or not project_ids:
            self._send_json({"ok": False, "message": "缺少 project_ids"}, 400)
            return
        if len(project_ids) > 200:
            self._send_json({"ok": False, "message": "一次最多移动 200 个项目"}, 400)
            return

        dest_dir = os.path.join(TRASH_DIR, "projects")
        os.makedirs(dest_dir, exist_ok=True)
        moved, failed, errors = 0, 0, []
        for project_id in project_ids:
            if not isinstance(project_id, str) or not _VALID_ID.match(project_id):
                failed += 1
                errors.append(str(project_id) + ": 无效的 project_id")
                continue
            folder_path, _ = _safe_project_path(project_id)
            if not folder_path or not os.path.isdir(folder_path):
                failed += 1
                errors.append(project_id + ": 项目不存在")
                continue
            try:
                dest = _unique_trash_path(os.path.join(dest_dir, project_id + "_" + _trash_stamp()))
                shutil.move(folder_path, dest)
                _write_trash_meta(dest, {
                    "type": "project",
                    "project_id": project_id,
                    "original_path": folder_path,
                    "trashed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                moved += 1
            except Exception as e:
                failed += 1
                errors.append(project_id + ": " + str(e))
        invalidate_project_cache()
        ensure_v2_index(force=True)
        self._send_json({
            "ok": failed == 0,
            "moved": moved,
            "failed": failed,
            "errors": errors,
            "message": f"批量移动完成: {moved} 成功, {failed} 失败",
        }, 200 if failed == 0 else 207)

    def _handle_v2_trash_sessions(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length))
            project_id = data.get("project_id", "")
            session_ids = data.get("session_ids", [])
        except Exception:
            self._send_json({"ok": False, "message": "请求格式错误"}, 400)
            return
        if not project_id or not _VALID_ID.match(project_id):
            self._send_json({"ok": False, "message": "无效的 project_id"}, 400)
            return
        if not isinstance(session_ids, list) or not session_ids:
            self._send_json({"ok": False, "message": "缺少 session_ids"}, 400)
            return
        if len(session_ids) > 500:
            self._send_json({"ok": False, "message": "一次最多移动 500 个会话"}, 400)
            return

        dest_dir = os.path.join(TRASH_DIR, "sessions", project_id)
        os.makedirs(dest_dir, exist_ok=True)
        moved, failed, errors = 0, 0, []
        for session_id in session_ids:
            if not isinstance(session_id, str) or not _VALID_ID.match(session_id):
                failed += 1
                errors.append(str(session_id) + ": 无效的 session_id")
                continue
            record_project_id = v2_index.record_project_id(INDEX_DB_FILE, project_id, session_id)
            _, filepath = _safe_project_path(record_project_id, session_id)
            if not filepath or not os.path.isfile(filepath):
                failed += 1
                errors.append(session_id + ": 会话文件不存在")
                continue
            try:
                dest = _unique_trash_path(os.path.join(dest_dir, session_id + "_" + _trash_stamp() + ".jsonl"))
                shutil.move(filepath, dest)
                _write_trash_meta(dest, {
                    "type": "session",
                    "project_id": record_project_id,
                    "session_id": session_id,
                    "original_path": filepath,
                    "trashed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                moved += 1
            except Exception as e:
                failed += 1
                errors.append(session_id + ": " + str(e))
        invalidate_project_cache()
        ensure_v2_index(force=True)
        self._send_json({
            "ok": failed == 0,
            "moved": moved,
            "failed": failed,
            "errors": errors,
            "message": f"批量移动完成: {moved} 成功, {failed} 失败",
        }, 200 if failed == 0 else 207)

    def _handle_stats(self):
        projects = get_cached_projects()
        daily = {}
        for p in projects:
            for s in p.get("sessions", []):
                created = s.get("created_at", "")
                day = created[:10] if isinstance(created, str) and len(created) >= 10 else "未知日期"
                if day not in daily:
                    daily[day] = {"date": day, "sessions": 0, "messages": 0, "tokens": 0}
                daily[day]["sessions"] += 1
                daily[day]["messages"] += s.get("total_msgs", 0)
                daily[day]["tokens"] += s.get("total_tokens", 0)
        self._send_json({
            "total_projects": len(projects),
            "total_sessions": sum(p["session_count"] for p in projects),
            "total_messages": sum(p["total_msgs"] for p in projects),
            "total_tokens":   sum(p["total_tokens"] for p in projects),
            "daily_activity": [daily[k] for k in sorted(daily.keys())],
        })

    def _handle_projects(self):
        projects = get_cached_projects()
        result = []
        for p in projects:
            result.append({
                "id":             p["id"],
                "name":           p["name"],
                "cwd":            p.get("cwd", ""),
                "session_count":  p["session_count"],
                "total_tokens":   p["total_tokens"],
                "total_msgs":     p["total_msgs"],
                "last_active":    p["last_active"],
                "summary":        generate_project_summary(p),
            })
        self._send_json(result)

    def _handle_project_detail(self, project_id):
        projects = get_cached_projects()
        for p in projects:
            if p["id"] == project_id:
                # Load stored AI summaries for sessions
                stored = load_session_summaries()
                for s in p["sessions"]:
                    s["chinese_summary"] = generate_chinese_summary(s)
                    key = project_id + "/" + s["id"]
                    s["ai_summary"] = stored.get(key, {}).get("summary", "")
                p["summary"] = generate_project_summary(p)
                self._send_json(p)
                return
        self._send_json({"error": "project not found"}, 404)

    def _handle_session(self, project_id, session_id):
        if not _VALID_ID.match(project_id) or not _VALID_ID.match(session_id):
            self._send_json({"error": "invalid id"}, 400)
            return
        session_path = os.path.join(PROJECTS_DIR, project_id, session_id + ".jsonl")
        if not os.path.isfile(session_path):
            self._send_json({"error": "session not found"}, 404)
            return

        entries, err = load_session_entries(session_path)
        if err:
            self._send_json({"error": err}, 500)
            return

        meta = extract_session_meta(entries)
        conversation = []
        for entry in entries:
            t = entry.get("type", "")
            if t not in ("user", "assistant"):
                continue
            msg = entry.get("message", {})
            content = msg.get("content", "")
            # Fix mojibake in text content (GBK terminal output mistaken as Latin-1)
            if isinstance(content, str):
                content = _fix_mojibake(content)
            elif isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "text" and b.get("text"):
                        b["text"] = _fix_mojibake(b["text"])
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        rc = b.get("content", "")
                        if isinstance(rc, str):
                            b["content"] = _fix_mojibake(rc)
                        elif isinstance(rc, list):
                            for rb in rc:
                                if isinstance(rb, dict) and rb.get("text"):
                                    rb["text"] = _fix_mojibake(rb["text"])
            item = {"role": msg.get("role", t), "content": content}
            if t == "assistant":
                item["model"] = msg.get("model", "")
                item["usage"] = msg.get("usage", {})
            conversation.append(item)

        # Check for stored AI summary
        stored = load_session_summaries()
        key = project_id + "/" + session_id
        ai_summary = stored.get(key, {}).get("summary", "")

        self._send_json({
            "id": session_id,
            "metadata": meta,
            "chinese_summary": generate_chinese_summary(meta),
            "ai_summary": ai_summary,
            "conversation": conversation,
        })

    def _handle_summarize(self, qs):
        proj = (qs.get("project") or [None])[0]
        sess = (qs.get("session") or [None])[0]
        if not proj or not sess:
            self._send_json({"error": "missing project/session"}, 400)
            return
        if not _VALID_ID.match(proj) or not _VALID_ID.match(sess):
            self._send_json({"error": "invalid id"}, 400)
            return
        if not is_ai_available():
            self._send_json({"error": "API 密钥未设置，请在设置页面配置"})
            return

        session_path = os.path.join(PROJECTS_DIR, proj, sess + ".jsonl")
        if not os.path.isfile(session_path):
            self._send_json({"error": "session not found"}, 404)
            return

        entries, _ = load_session_entries(session_path)
        text_parts = []
        for entry in entries:
            t = entry.get("type", "")
            if t not in ("user", "assistant"):
                continue
            msg = entry.get("message", {})
            content = msg.get("content", "")
            if isinstance(content, list):
                texts = [_fix_mojibake(b.get("text", "")) for b in content if b.get("type") == "text" and b.get("text")]
                content = "\n".join(texts)
            elif isinstance(content, str):
                content = _fix_mojibake(content)
            if isinstance(content, str) and content.strip():
                text_parts.append("[" + msg.get("role", t) + "]: " + content[:500])

        summary = ai_summarize_session("\n\n".join(text_parts))
        if is_api_error(summary):
            self._send_json({"ok": False, "error": summary}, 502)
            return
        if summary:
            save_session_summary(proj, sess, summary)
            self._send_json({"ok": True, "summary": summary})
            return
        self._send_json({"ok": False, "error": "总结生成失败"}, 502)

    def _handle_summarize_all(self):
        """AI-summarize all sessions in a project."""
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length))
            project_id = data.get("project_id", "")
        except Exception:
            self._send_json({"ok": False, "message": "请求格式错误"}, 400)
            return
        if not project_id:
            self._send_json({"ok": False, "message": "缺少 project_id"}, 400)
            return
        if not _VALID_ID.match(project_id):
            self._send_json({"ok": False, "message": "无效的 project_id"}, 400)
            return
        if not is_ai_available():
            self._send_json({"ok": False, "message": "请先在设置页面配置 API 密钥"})
            return

        folder = os.path.join(PROJECTS_DIR, project_id)
        if not os.path.isdir(folder):
            self._send_json({"ok": False, "message": "项目不存在"}, 404)
            return

        stored = load_session_summaries()
        results = {"total": 0, "success": 0, "failed": 0, "skipped": 0, "errors": []}
        for fn in sorted(os.listdir(folder)):
            if not fn.endswith(".jsonl"):
                continue
            sid = fn.replace(".jsonl", "")
            results["total"] += 1
            key = project_id + "/" + sid
            if stored.get(key, {}).get("summary"):
                results["skipped"] += 1
                continue
            session_path = os.path.join(folder, fn)
            try:
                entries, _ = load_session_entries(session_path)
                text_parts = []
                for entry in entries:
                    t = entry.get("type", "")
                    if t not in ("user", "assistant"):
                        continue
                    msg = entry.get("message", {})
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        texts = [_fix_mojibake(b.get("text", "")) for b in content if b.get("type") == "text" and b.get("text")]
                        content = "\n".join(texts)
                    elif isinstance(content, str):
                        content = _fix_mojibake(content)
                    if isinstance(content, str) and content.strip():
                        text_parts.append("[" + msg.get("role", t) + "]: " + content[:500])
                summary = ai_summarize_session("\n\n".join(text_parts))
                if summary and not is_api_error(summary):
                    save_session_summary(project_id, sid, summary)
                    results["success"] += 1
                else:
                    results["failed"] += 1
                    results["errors"].append(sid + ": " + (summary or "总结生成失败"))
                time.sleep(0.8)
            except Exception as e:
                results["failed"] += 1
                results["errors"].append(sid + ": " + str(e))

        results["message"] = f"完成: 新增 {results['success']}，跳过 {results['skipped']}，失败 {results['failed']}"
        self._send_json({"ok": results["failed"] == 0, **results}, 200 if results["failed"] == 0 else 502)

    def _handle_search(self, qs):
        q = ((qs.get("q") or [""])[0]).strip().lower()
        if not q:
            self._send_json({"q": q, "results": []})
            return

        results = []
        seen_projects = set()
        seen_sessions = set()

        projects = get_cached_projects()

        # ── 1. Search project descriptions ──
        descs = load_project_descriptions()
        for pid, info in descs.items():
            desc = info.get("description", "")
            if q in desc.lower():
                pname = pid
                for p in projects:
                    if p["id"] == pid:
                        pname = p.get("name", pid)
                        break
                seen_projects.add(pid)
                results.append({
                    "type": "project",
                    "id": pid,
                    "name": pname,
                    "matched_text": desc[:200],
                })

        # ── 2. Search project names / paths ──
        for p in projects:
            if p["id"] in seen_projects:
                continue
            name = p.get("name", "")
            if q in p["id"].lower() or q in name.lower():
                seen_projects.add(p["id"])
                results.append({
                    "type": "project",
                    "id": p["id"],
                    "name": name,
                    "matched_text": "项目路径: " + name,
                })

        # ── 3. Search session summaries ──
        sums = load_session_summaries()
        for key, info in sums.items():
            summary = info.get("summary", "")
            if q in summary.lower():
                parts = key.split("/", 1)
                pid = parts[0]
                sid = parts[1] if len(parts) > 1 else key
                seen_sessions.add(pid + "/" + sid)
                title = sid
                for p in projects:
                    if p["id"] == pid:
                        for s in p.get("sessions", []):
                            if s["id"] == sid:
                                title = s.get("title", sid)
                                break
                results.append({
                    "type": "session",
                    "project_id": pid,
                    "session_id": sid,
                    "title": title,
                    "matched_text": summary[:300],
                })

        # ── 4. Search session titles (native Claude summary) ──
        for p in projects:
            for s in p.get("sessions", []):
                key = p["id"] + "/" + s["id"]
                if key in seen_sessions:
                    continue
                title = s.get("title", "")
                if q in title.lower():
                    seen_sessions.add(key)
                    results.append({
                        "type": "session",
                        "project_id": p["id"],
                        "session_id": s["id"],
                        "title": title,
                        "matched_text": "会话标题: " + title,
                    })

        # Sort: projects first, then sessions
        results.sort(key=lambda r: (0 if r["type"] == "project" else 1, r.get("title", "")))
        self._send_json({"q": q, "results": results})

    def _handle_claude_status(self):
        available = CLAUDE_EXE is not None
        self._send_json({
            "available": available,
            "path": CLAUDE_EXE or "",
        })

    def _handle_open_claude(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length))
            path = data.get("path", "")
            resume = data.get("resume", False)
            project_id = data.get("project_id") or None
            session_id = data.get("session_id") or None
            permission = data.get("permission")
        except Exception:
            self._send_json({"ok": False, "message": "请求格式错误"}, 400)
            return

        if not path:
            self._send_json({"ok": False, "message": "缺少 path 参数"}, 400)
            return
        if session_id and not _VALID_ID.match(session_id):
            self._send_json({"ok": False, "message": "无效的 session_id"}, 400)
            return
        if project_id and not _VALID_ID.match(project_id):
            self._send_json({"ok": False, "message": "无效的 project_id"}, 400)
            return
        path = apply_path_mapping(path)
        if resume and project_id and session_id:
            hint = resume_migration_hint(project_id, session_id)
            if hint:
                self._send_json({
                    "ok": False,
                    "needs_migration": True,
                    "message": "该会话已映射到新位置，但 Claude 会话记录还没有迁移。请在项目页点击“迁移会话”后再恢复。",
                    "hint": hint,
                }, 409)
                return
            path = resolve_session_launch_path(project_id, session_id, path)

        ok, msg = launch_claude(path, resume=resume, session_id=session_id, permission=permission)
        self._send_json({"ok": ok, "message": msg})

    def _handle_open_directory(self):
        """Open a project path in the native file manager."""
        try:
            data = self._read_json_body()
            path = data.get("path", "") if isinstance(data, dict) else ""
        except Exception:
            self._send_json({"ok": False, "message": "请求格式错误"}, 400)
            return
        path = apply_path_mapping(path)
        ok, message, opened_path = open_directory_in_file_manager(path)
        self._send_json(
            {"ok": ok, "message": message, "path": opened_path},
            200 if ok else 404,
        )

    def _handle_quick_launch(self):
        """Quick-launch Claude Code with saved path & permission settings."""
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length))
        except Exception:
            self._send_json({"ok": False, "message": "请求格式错误"}, 400)
            return

        path = (data.get("path") or "").strip()
        perm = data.get("permission", "std")
        if not path:
            path = DEFAULT_QL_PATH
        if not os.path.isdir(path):
            self._send_json({"ok": False, "message": "目录不存在: " + path}, 400)
            return

        # Save settings for next time
        _ai_config["ql_path"] = path
        _ai_config["ql_perm"] = perm
        save_api_config(_ai_config)

        ok, msg = launch_claude(path, permission=perm)
        self._send_json({"ok": ok, "message": msg})

    def _handle_get_descriptions(self):
        """Return all stored AI project descriptions."""
        descs = load_project_descriptions()
        self._send_json(descs)

    def _handle_describe_project(self):
        """Generate AI description for a single project."""
        if not is_ai_available():
            self._send_json({"ok": False, "message": "请先在设置页面配置 API 密钥"}, 400)
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length))
            project_id = data.get("project_id", "")
        except Exception:
            self._send_json({"ok": False, "message": "请求格式错误"}, 400)
            return

        # Find the project
        projects = get_cached_projects()
        project = None
        for p in projects:
            if p["id"] == project_id:
                project = p
                break
        if not project:
            self._send_json({"ok": False, "message": "项目未找到"}, 404)
            return

        # Generate description via API
        model = get_summary_model()
        description = generate_project_description(project)
        if not description:
            self._send_json({"ok": False, "message": "API 调用返回空"}, 500)
            return
        if is_api_error(description):
            self._send_json({"ok": False, "message": description}, 500)
            return

        # Save to storage
        descs = load_project_descriptions()
        descs[project_id] = {
            "description": description.strip(),
            "model": model,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        save_project_descriptions(descs)

        self._send_json({
            "ok": True,
            "project_id": project_id,
            "description": descs[project_id],
        })

    def _handle_describe_all(self):
        """Generate AI descriptions for ALL projects sequentially."""
        self._discard_request_body()
        if not is_ai_available():
            self._send_json({"ok": False, "message": "请先在设置页面配置 API 密钥"}, 400)
            return

        projects = get_cached_projects()
        model = get_summary_model()
        descs = load_project_descriptions()
        results = {"total": len(projects), "success": 0, "failed": 0, "errors": []}

        for p in projects:
            try:
                description = generate_project_description(p)
                if description and not is_api_error(description):
                    descs[p["id"]] = {
                        "description": description.strip(),
                        "model": model,
                        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    results["success"] += 1
                else:
                    results["failed"] += 1
                    results["errors"].append(f"{p['name']}: {description}")
            except Exception as e:
                results["failed"] += 1
                results["errors"].append(f"{p['name']}: {e}")

        save_project_descriptions(descs)
        results["message"] = f"完成: {results['success']} 成功, {results['failed']} 失败"
        results["ok"] = results["failed"] == 0
        # A partial batch still completed successfully at the transport layer.
        # Keep HTTP 200 so the UI can refresh and show descriptions that succeeded.
        self._send_json(results)

    def _handle_set_api_config(self):
        """Update API provider, endpoint, or key."""
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length))
        except Exception:
            self._send_json({"ok": False, "message": "请求格式错误"}, 400)
            return

        changed = False
        if "provider" in data and data["provider"] in PROVIDER_MODELS:
            _ai_config["provider"] = data["provider"]
            # If switching provider, reset model to first available
            models = PROVIDER_MODELS[data["provider"]]
            _ai_config["api_model"] = list(models.keys())[0]
            changed = True
        if "api_endpoint" in data and data["api_endpoint"].strip():
            _ai_config["api_endpoint"] = data["api_endpoint"].strip()
            changed = True
        if "api_key" in data and data["api_key"].strip():
            _ai_config["api_key"] = data["api_key"].strip()
            changed = True
        if "api_model" in data:
            prov = _ai_config.get("provider", "deepseek")
            if data["api_model"] in PROVIDER_MODELS.get(prov, {}):
                _ai_config["api_model"] = data["api_model"]
                changed = True

        if changed:
            save_api_config(_ai_config)
        safe = {k: v for k, v in _ai_config.items() if k != "api_key"}
        self._send_json({"ok": True, "config": safe})

    def _handle_delete_project(self):
        """Delete a project and all its session files."""
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length))
            project_id = data.get("project_id", "")
        except Exception:
            self._send_json({"ok": False, "message": "请求格式错误"}, 400)
            return
        if not project_id:
            self._send_json({"ok": False, "message": "缺少 project_id"}, 400)
            return
        if not _VALID_ID.match(project_id):
            self._send_json({"ok": False, "message": "无效的项目ID"}, 400)
            return

        folder_path = os.path.join(PROJECTS_DIR, project_id)
        if not os.path.isdir(folder_path):
            self._send_json({"ok": False, "message": "项目不存在"}, 404)
            return

        try:
            shutil.rmtree(folder_path)
            descs = load_project_descriptions()
            if project_id in descs:
                descs.pop(project_id, None)
                save_project_descriptions(descs)
            sums = load_session_summaries()
            prefix = project_id + "/"
            changed = False
            for key in list(sums.keys()):
                if key.startswith(prefix):
                    sums.pop(key, None)
                    changed = True
            if changed:
                save_session_summaries(sums)
            invalidate_project_cache()
            return self._send_json({"ok": True, "message": "已删除"})
        except Exception as e:
            return self._send_json({"ok": False, "message": str(e)}, 500)

    def _handle_delete_projects(self):
        """Delete multiple projects and their session files."""
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length))
            project_ids = data.get("project_ids", [])
        except Exception:
            self._send_json({"ok": False, "message": "请求格式错误"}, 400)
            return
        if not isinstance(project_ids, list) or not project_ids:
            self._send_json({"ok": False, "message": "缺少 project_ids"}, 400)
            return
        if len(project_ids) > 200:
            self._send_json({"ok": False, "message": "一次最多删除 200 个项目"}, 400)
            return

        descs = load_project_descriptions()
        sums = load_session_summaries()
        deleted, failed, errors = 0, 0, []
        for project_id in project_ids:
            if not isinstance(project_id, str) or not _VALID_ID.match(project_id):
                failed += 1
                errors.append(str(project_id) + ": 无效的项目ID")
                continue
            folder_path, _ = _safe_project_path(project_id)
            if not folder_path or not os.path.isdir(folder_path):
                failed += 1
                errors.append(project_id + ": 项目不存在")
                continue
            try:
                shutil.rmtree(folder_path)
                deleted += 1
                descs.pop(project_id, None)
                prefix = project_id + "/"
                for key in list(sums.keys()):
                    if key.startswith(prefix):
                        sums.pop(key, None)
            except Exception as e:
                failed += 1
                errors.append(project_id + ": " + str(e))

        save_project_descriptions(descs)
        save_session_summaries(sums)
        invalidate_project_cache()
        self._send_json({
            "ok": failed == 0,
            "deleted": deleted,
            "failed": failed,
            "errors": errors,
            "message": f"删除完成: {deleted} 成功, {failed} 失败",
        })

    def _handle_delete_session(self):
        """Delete a single session file."""
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length))
            project_id = data.get("project_id", "")
            session_id = data.get("session_id", "")
        except Exception:
            self._send_json({"ok": False, "message": "请求格式错误"}, 400)
            return
        if not project_id or not session_id:
            self._send_json({"ok": False, "message": "缺少参数"}, 400)
            return
        if not _VALID_ID.match(project_id) or not _VALID_ID.match(session_id):
            self._send_json({"ok": False, "message": "无效的ID"}, 400)
            return

        filepath = os.path.join(PROJECTS_DIR, project_id, session_id + ".jsonl")
        if not os.path.isfile(filepath):
            self._send_json({"ok": False, "message": "会话文件不存在"}, 404)
            return

        try:
            os.remove(filepath)
            sums = load_session_summaries()
            key = project_id + "/" + session_id
            if key in sums:
                sums.pop(key, None)
                save_session_summaries(sums)
            invalidate_project_cache()
            return self._send_json({"ok": True, "message": "会话已删除"})
        except Exception as e:
            return self._send_json({"ok": False, "message": str(e)}, 500)

    def _handle_delete_sessions(self):
        """Delete multiple session files from one project."""
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length))
            project_id = data.get("project_id", "")
            session_ids = data.get("session_ids", [])
        except Exception:
            self._send_json({"ok": False, "message": "请求格式错误"}, 400)
            return
        if not project_id or not isinstance(session_ids, list) or not session_ids:
            self._send_json({"ok": False, "message": "缺少参数"}, 400)
            return
        if not _VALID_ID.match(project_id):
            self._send_json({"ok": False, "message": "无效的项目ID"}, 400)
            return
        if len(session_ids) > 500:
            self._send_json({"ok": False, "message": "一次最多删除 500 个会话"}, 400)
            return

        sums = load_session_summaries()
        deleted, failed, errors = 0, 0, []
        for session_id in session_ids:
            if not isinstance(session_id, str) or not _VALID_ID.match(session_id):
                failed += 1
                errors.append(str(session_id) + ": 无效的会话ID")
                continue
            _, filepath = _safe_project_path(project_id, session_id)
            if not filepath or not os.path.isfile(filepath):
                failed += 1
                errors.append(session_id + ": 会话文件不存在")
                continue
            try:
                os.remove(filepath)
                deleted += 1
                sums.pop(project_id + "/" + session_id, None)
            except Exception as e:
                failed += 1
                errors.append(session_id + ": " + str(e))

        save_session_summaries(sums)
        invalidate_project_cache()
        self._send_json({
            "ok": failed == 0,
            "deleted": deleted,
            "failed": failed,
            "errors": errors,
            "message": f"删除完成: {deleted} 成功, {failed} 失败",
        })

    def _handle_config(self):
        provider = _ai_config.get("provider", "deepseek")
        config = {
            "api_key_available": is_ai_available(),
            "api_key_masked": masked_api_key(),
            "provider": provider,
            "api_model": get_summary_model(),
            "summary_models": PROVIDER_MODELS.get(provider, {}),
            "api_endpoint": _ai_config.get("api_endpoint", ""),
            "ql_path": _ai_config.get("ql_path", DEFAULT_QL_PATH),
            "ql_perm": _ai_config.get("ql_perm", "std"),
            "ql_permissions": {k: {"label": v["label"], "desc": v["desc"]} for k, v in PERMISSION_PRESETS.items()},
            "ql_default_path": DEFAULT_QL_PATH,
        }
        settings_path = os.path.join(CLAUDE_DIR, "settings.json")
        if os.path.isfile(settings_path):
            try:
                with open(settings_path, encoding="utf-8") as f:
                    config["settings"] = mask_sensitive_config(json.load(f))
            except Exception:
                config["settings"] = {"error": "无法解析"}
        claude_md = os.path.join(os.path.dirname(CLAUDE_DIR), "CLAUDE.md")
        if os.path.isfile(claude_md):
            try:
                with open(claude_md, encoding="utf-8") as f:
                    config["claude_md"] = f.read()[:2000]
            except Exception:
                config["claude_md"] = ""
        self._send_json(config)

    def _handle_pick_folder(self):
        """Open a native OS folder picker dialog and return the selected path."""
        if os.name == "nt":
            vbs = (
                'Set o = CreateObject("Shell.Application")\r\n'
                'Set f = o.BrowseForFolder(0, "Select Workspace Folder", 0)\r\n'
                'If Not f Is Nothing Then WScript.StdOut.Write f.Self.Path\r\n'
            )
            import tempfile
            tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".vbs", prefix="ccm_", delete=False, encoding="ascii")
            tmp.write(vbs)
            tmp.close()
            vbs_path = tmp.name
            try:
                cs = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
                r = subprocess.run(
                    ["cscript", "//Nologo", vbs_path],
                    capture_output=True, text=True, timeout=60, creationflags=cs
                )
                self._send_json({"path": r.stdout.strip()})
            except Exception as e:
                self._send_json({"path": "", "error": str(e)})
            finally:
                try:
                    os.remove(vbs_path)
                except OSError:
                    pass
        else:
            self._send_json({"path": "", "error": "当前文件夹选择器仅支持 Windows EXE 环境"}, 400)

    def _handle_api_key_status(self):
        self._send_json({"available": is_ai_available()})

    def _handle_desktop_activate(self):
        """Bring an existing desktop window to the foreground."""
        self._send_json({
            "ok": activate_desktop_window(),
            "desktop": desktop_window_available(),
            "ready": _desktop_ready.is_set(),
            "version": APP_VERSION,
        })

    def _handle_shutdown(self):
        """Stop the desktop window and loopback service after responding."""
        self._discard_request_body()
        self._send_json({"ok": True, "message": "管理器正在关闭"})
        request_application_shutdown(self.server)

    # ── Low-level I/O ──────────────────────────────────────────────────────

    MIME = {
        ".html": "text/html; charset=utf-8",
        ".css":  "text/css; charset=utf-8",
        ".js":   "application/javascript; charset=utf-8",
        ".json": "application/json",
        ".png":  "image/png",
        ".svg":  "image/svg+xml",
        ".ico":  "image/x-icon",
    }

    def _serve_static(self, name, forced_type=None):
        base = MANAGER_DIR if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
        static_dir = os.path.realpath(os.path.join(base, "static"))
        filepath = os.path.realpath(os.path.join(static_dir, name))
        try:
            if os.path.commonpath((static_dir, filepath)) != static_dir:
                self._send_json({"error": "invalid static path"}, 400)
                return
        except ValueError:
            self._send_json({"error": "invalid static path"}, 400)
            return
        if not os.path.isfile(filepath):
            self._send_json({"error": "file not found"}, 404)
            return
        ctype = forced_type or self.MIME.get(os.path.splitext(name)[1].lower(), "application/octet-stream")
        try:
            stat = os.stat(filepath)
            signature = (stat.st_mtime_ns, stat.st_size)
            with _static_cache_lock:
                cached = _static_cache.get(filepath)
                if not cached or cached["signature"] != signature:
                    with open(filepath, "rb") as f:
                        cached = {"signature": signature, "data": f.read()}
                    _static_cache[filepath] = cached
                data = cached["data"]
            etag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
            cache_control = (
                "public, max-age=31536000, immutable"
                if name != "index.html" and "v=" in self.path
                else "no-cache"
            )
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", cache_control)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", cache_control)
            self.send_header("ETag", etag)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _send_json(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, fmt, *args):
        runtime_log(f"[{datetime.now().strftime('%H:%M:%S')}] {fmt % args}")


# =============================================================================
# Entry point
# =============================================================================

def desktop_window_available():
    with _desktop_lock:
        return _desktop_mode and _desktop_window is not None


def activate_desktop_window():
    """Restore and focus the native window; safe to call from an HTTP worker."""
    with _desktop_lock:
        window = _desktop_window
    if window is None:
        return False
    try:
        window.restore()
        window.show()
        return True
    except Exception:
        return False


def request_application_shutdown(server):
    """Close both halves of the desktop app without blocking a request thread."""
    def shutdown_worker():
        time.sleep(0.12)
        with _desktop_lock:
            window = _desktop_window
        if window is not None:
            try:
                window.destroy()
            except Exception:
                pass
        try:
            server.shutdown()
        except Exception:
            pass

    threading.Thread(target=shutdown_worker, name="ccm-shutdown", daemon=True).start()


def open_browser(port=None):
    """Open the app in the default browser after a short delay."""
    if port is None:
        time.sleep(0.6)
        port = PORT
    webbrowser.open(f"http://{HOST}:{port}")


def is_manager_running(port):
    """Return True when a Claude Manager instance is already serving on port."""
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/desktop/activate", timeout=1.2) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        if str(data.get("version", "")).startswith("v2."):
            return True
    except Exception:
        pass
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/", timeout=1.2) as resp:
            body = resp.read(2048).decode("utf-8", "replace")
        return (
            "Claude Code Manager" in body
            or "Claude Manager" in body
            or "Claude Code 管理器" in body
        )
    except Exception:
        return False


def activate_existing_manager(port):
    """Focus a desktop instance, falling back to its browser URL for old builds."""
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/desktop/activate", timeout=1.2) as resp:
            result = json.loads(resp.read().decode("utf-8", "replace"))
        if result.get("desktop") and result.get("ok"):
            return True
    except Exception:
        pass
    open_browser(port)
    return False


def is_port_open(port):
    """Fast TCP probe used only to decide whether an HTTP manager check is needed."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.08)
    try:
        return sock.connect_ex((HOST, port)) == 0
    finally:
        sock.close()


def bind_server():
    """Bind the HTTP server, falling back when Windows reserves the default port."""
    global PORT
    last_error = None
    for port in range(PORT, PORT + PORT_FALLBACK_LIMIT + 1):
        if is_port_open(port):
            if is_manager_running(port):
                activate_existing_manager(port)
                runtime_log(f"Existing Claude Manager instance activated at http://{HOST}:{port}")
                return None
            continue
        try:
            server = ManagerHTTPServer((HOST, port), Handler)
            PORT = port
            return server
        except OSError as e:
            last_error = e
            continue
    runtime_log(f"Cannot bind ports {PORT}-{PORT + PORT_FALLBACK_LIMIT}: {last_error}", error=True)
    return None


def run_desktop_window(server):
    """Run pywebview on the main thread while HTTP work stays in the background."""
    global _desktop_mode, _desktop_window
    try:
        import webview
    except Exception as exc:
        runtime_log(f"Desktop runtime unavailable, using browser mode: {exc}", error=True)
        return False

    icon_path = os.path.join(MANAGER_DIR, "assets", "app-icon.ico")
    window = webview.create_window(
        "Claude Code 管理器",
        f"http://{HOST}:{PORT}",
        width=1380,
        height=860,
        min_size=(980, 640),
        resizable=True,
        background_color="#090b10",
        text_select=True,
        zoomable=False,
    )
    with _desktop_lock:
        _desktop_mode = True
        _desktop_window = window
    _desktop_ready.clear()

    def on_closed():
        threading.Thread(target=server.shutdown, name="ccm-window-close", daemon=True).start()

    window.events.closed += on_closed
    window.events.loaded += _desktop_ready.set
    try:
        webview.start(
            gui="edgechromium" if sys.platform == "win32" else None,
            debug=False,
            private_mode=False,
            storage_path=os.path.join(DATA_DIR, "webview"),
            icon=icon_path if os.path.isfile(icon_path) else None,
        )
        return True
    except Exception as exc:
        runtime_log(f"Desktop window failed, using browser mode: {exc}", error=True)
        return False
    finally:
        with _desktop_lock:
            _desktop_window = None
            _desktop_mode = False
        _desktop_ready.clear()


def main():
    global PORT
    server = bind_server()
    if server is None:
        return

    has_api = "yes" if is_ai_available() else "no"
    runtime_log(f"\n  Claude Manager {APP_VERSION}  |  http://{HOST}:{PORT}  |  data: {CLAUDE_DIR}  |  API: {has_api}\n")
    browser_mode = "--browser" in sys.argv or os.environ.get("CCM_BROWSER_MODE") == "1"
    server_thread = None
    try:
        if not browser_mode:
            server_thread = threading.Thread(
                target=server.serve_forever,
                name="ccm-http",
                daemon=True,
            )
            server_thread.start()
            if run_desktop_window(server):
                server.shutdown()
                server_thread.join(timeout=3)
                return
            threading.Thread(target=open_browser, name="ccm-browser", daemon=True).start()
            server_thread.join()
        else:
            threading.Thread(target=open_browser, name="ccm-browser", daemon=True).start()
            server.serve_forever()
    except KeyboardInterrupt:
        runtime_log("\nServer stopped.")
    finally:
        try:
            server.shutdown()
        except Exception:
            pass
        server.server_close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        runtime_log("Uncaught application error:\n" + traceback.format_exc(), error=True)
        raise
