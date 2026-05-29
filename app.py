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
import urllib.request
import webbrowser
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

# =============================================================================
# Configuration
# =============================================================================
CLAUDE_DIR = os.path.expanduser("~/.claude")
HOST = "127.0.0.1"
PORT = 5141
PROJECTS_DIR = os.path.join(CLAUDE_DIR, "projects")
# Handle both dev and PyInstaller-packaged paths
if getattr(sys, "frozen", False):
    MANAGER_DIR = os.path.dirname(sys.executable)
else:
    MANAGER_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(MANAGER_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

DESCRIPTIONS_FILE = os.path.join(DATA_DIR, "project-descriptions.json")
SESSION_SUMMARIES_FILE = os.path.join(DATA_DIR, "session-summaries.json")
API_CONFIG_FILE = os.path.join(DATA_DIR, "api-config.json")

# ---- Model presets per provider ----

PROVIDER_MODELS = {
    "anthropic": {
        "claude-haiku-4-5-20251001":  "Claude Haiku 4.5 (最快最便宜)",
        "claude-sonnet-4-6-20250514": "Claude Sonnet 4.6 (推荐 速度与质量平衡)",
        "claude-opus-4-7-20250514":   "Claude Opus 4.7 (最贵最准确)",
    },
    "deepseek": {
        "deepseek-chat":     "DeepSeek-V4 (推荐)",
        "deepseek-reasoner": "DeepSeek-R1 (深度推理)",
    },
}

DEFAULT_API_CONFIG = {
    "provider": "deepseek",
    "api_key": "",
    "api_endpoint": "https://api.deepseek.com/v1/chat/completions",
    "api_model": "deepseek-chat",
}


# =============================================================================
# Data helpers
# =============================================================================

def resolve_project_path(folder_name):
    """
    Resolve the encoded project folder name to a real filesystem path.
    Strategy: read the 'cwd' field from the system entry of the first
    available session file.  Falls back to a best-effort heuristic decode.
    """
    folder_path = os.path.join(PROJECTS_DIR, folder_name)
    if not os.path.isdir(folder_path):
        return folder_name

    # 1. Try to read cwd from a session file (most reliable)
    try:
        for fn in sorted(os.listdir(folder_path)):
            if fn.endswith(".jsonl"):
                fp = os.path.join(folder_path, fn)
                entries = _read_jsonl(fp)
                for entry in entries:
                    if entry.get("type") == "system":
                        cwd = entry.get("cwd")
                        if cwd:
                            return cwd
                break  # only need the first session file
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
    return joined


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

        if t == "ai-title" and not meta["title"]:
            meta["title"] = entry.get("aiTitle")

        elif t == "system":
            if not meta["created_at"] and entry.get("timestamp"):
                meta["created_at"] = entry["timestamp"]
            meta["cwd"] = entry.get("cwd") or meta["cwd"]
            meta["git_branch"] = entry.get("gitBranch") or meta["git_branch"]

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


def get_cached_projects():
    """Return cached or freshly scanned project list."""
    now = time.time()
    if _project_cache["data"] is not None and (now - _project_cache["time"]) < _project_cache_ttl:
        return _project_cache["data"]
    data = _scan_all_projects()
    _project_cache["data"] = data
    _project_cache["time"] = now
    return data


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
    return _ai_config.get("api_model", "deepseek-chat")


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

def load_api_config():
    """Load API provider config from disk."""
    if os.path.isfile(API_CONFIG_FILE):
        try:
            with open(API_CONFIG_FILE, encoding="utf-8") as f:
                saved = json.load(f)
                cfg = dict(DEFAULT_API_CONFIG)
                cfg.update(saved)
                return cfg
        except Exception:
            pass
    return dict(DEFAULT_API_CONFIG)


def save_api_config(cfg):
    """Save API provider config to disk."""
    with open(API_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


_ai_config = load_api_config()


def is_ai_available():
    return bool(_ai_config.get("api_key", ""))


def call_ai_api(prompt, max_tokens=300):
    """Call the configured AI provider and return the response text."""
    cfg = _ai_config
    if not cfg.get("api_key"):
        return None

    provider = cfg["provider"]
    model = cfg.get("api_model", "deepseek-chat")
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
            return result["content"][0]["text"]

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
            return result["choices"][0]["message"]["content"]

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
    return call_ai_api(prompt, max_tokens=300)


def ai_describe_project(project_info):
    """Generate a broad overview of what topics a project covers."""
    prompt = (
        "下面是一个项目目录下所有 Claude Code 会话的标题和首条消息。\n"
        "请用 2-3 句中文简要概括：这个目录下的对话主要涉及哪些方面的内容。\n"
        "像在给一个开发者做项目速览，让他一眼知道这里面讨论过什么话题。\n\n" +
        project_info[:2500] + "\n\n项目概览："
    )
    return call_ai_api(prompt, max_tokens=200)


def load_session_summaries():
    """Load stored AI session summaries."""
    if os.path.isfile(SESSION_SUMMARIES_FILE):
        try:
            with open(SESSION_SUMMARIES_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_session_summary(project_id, session_id, summary):
    """Save an AI session summary."""
    summaries = load_session_summaries()
    key = project_id + "/" + session_id
    summaries[key] = {
        "summary": summary.strip(),
        "model": _ai_config.get("api_model", ""),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(SESSION_SUMMARIES_FILE, "w", encoding="utf-8") as f:
        json.dump(summaries, f, ensure_ascii=False, indent=2)


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


def launch_claude(workspace_path):
    """Launch Claude Code in a new terminal window at the given path."""
    if not CLAUDE_EXE:
        return False, "未找到 claude 命令"
    if not os.path.isdir(workspace_path):
        return False, "目录不存在: " + workspace_path
    try:
        if os.name == "nt":
            subprocess.Popen(
                [CLAUDE_EXE],
                cwd=workspace_path,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
                shell=False,
            )
        elif sys.platform == "darwin":
            subprocess.Popen(
                ["open", "-a", "Terminal", CLAUDE_EXE],
                cwd=workspace_path,
            )
        else:
            subprocess.Popen(
                ["x-terminal-emulator", "-e", CLAUDE_EXE],
                cwd=workspace_path,
            )
        return True, "Claude Code 已启动"
    except Exception as e:
        return False, str(e)


# =============================================================================
# HTTP Server
# =============================================================================

class Handler(BaseHTTPRequestHandler):

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
        }

        # Dynamic routes
        if path.startswith("/static/"):
            self._serve_static(path[len("/static/"):])
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
        elif path in routes:
            routes[path]()
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/open-claude":
            self._handle_open_claude()
        elif parsed.path == "/api/describe-project":
            self._handle_describe_project()
        elif parsed.path == "/api/describe-all":
            self._handle_describe_all()
        elif parsed.path == "/api/set-api-config":
            self._handle_set_api_config()
        elif parsed.path == "/api/delete-project":
            self._handle_delete_project()
        elif parsed.path == "/api/delete-session":
            self._handle_delete_session()
        else:
            self._send_json({"error": "not found"}, 404)

    # ── API handlers ───────────────────────────────────────────────────────

    def _handle_stats(self):
        projects = get_cached_projects()
        self._send_json({
            "total_projects": len(projects),
            "total_sessions": sum(p["session_count"] for p in projects),
            "total_messages": sum(p["total_msgs"] for p in projects),
            "total_tokens":   sum(p["total_tokens"] for p in projects),
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
        if summary and not summary.startswith("[API"):
            save_session_summary(proj, sess, summary)
        self._send_json({"summary": summary or "总结生成失败"})

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
        except Exception:
            self._send_json({"ok": False, "message": "请求格式错误"}, 400)
            return

        if not path:
            self._send_json({"ok": False, "message": "缺少 path 参数"}, 400)
            return

        ok, msg = launch_claude(path)
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
        if description.startswith("[API 错误"):
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
                if description and not description.startswith("[API 错误"):
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
        self._send_json({"ok": True, "config": _ai_config})

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

        folder_path = os.path.join(PROJECTS_DIR, project_id)
        if not os.path.isdir(folder_path):
            self._send_json({"ok": False, "message": "项目不存在"}, 404)
            return

        try:
            shutil.rmtree(folder_path)
            return self._send_json({"ok": True, "message": "已删除"})
        except Exception as e:
            return self._send_json({"ok": False, "message": str(e)}, 500)

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

        filepath = os.path.join(PROJECTS_DIR, project_id, session_id + ".jsonl")
        if not os.path.isfile(filepath):
            self._send_json({"ok": False, "message": "会话文件不存在"}, 404)
            return

        try:
            os.remove(filepath)
            return self._send_json({"ok": True, "message": "会话已删除"})
        except Exception as e:
            return self._send_json({"ok": False, "message": str(e)}, 500)

    def _handle_config(self):
        provider = _ai_config.get("provider", "deepseek")
        config = {
            "api_key_available": is_ai_available(),
            "provider": provider,
            "api_model": get_summary_model(),
            "summary_models": PROVIDER_MODELS.get(provider, {}),
            "api_endpoint": _ai_config.get("api_endpoint", ""),
        }
        settings_path = os.path.join(CLAUDE_DIR, "settings.json")
        if os.path.isfile(settings_path):
            try:
                with open(settings_path, encoding="utf-8") as f:
                    config["settings"] = json.load(f)
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

    def _handle_api_key_status(self):
        self._send_json({"available": is_ai_available()})

    # ── Low-level I/O ──────────────────────────────────────────────────────

    MIME = {
        ".html": "text/html; charset=utf-8",
        ".css":  "text/css; charset=utf-8",
        ".js":   "application/javascript; charset=utf-8",
        ".json": "application/json",
        ".png":  "image/png",
        ".svg":  "image/svg+xml",
    }

    def _serve_static(self, name, forced_type=None):
        base = MANAGER_DIR if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
        static_dir = os.path.join(base, "static")
        filepath = os.path.join(static_dir, name)
        if not os.path.isfile(filepath):
            self._send_json({"error": "file not found"}, 404)
            return
        ctype = forced_type or self.MIME.get(os.path.splitext(name)[1].lower(), "application/octet-stream")
        try:
            with open(filepath, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def log_message(self, fmt, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {fmt % args}")


# =============================================================================
# Entry point
# =============================================================================

def open_browser():
    """Open the app in the default browser after a short delay."""
    time.sleep(1)
    webbrowser.open(f"http://{HOST}:{PORT}")


def main():
    global PORT
    # Quick port check with fallback
    port_ok = False
    for tried in [PORT] + list(range(PORT + 1, PORT + 10)):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind((HOST, tried))
            s.close()
            PORT = tried
            port_ok = True
            break
        except OSError:
            s.close()
    if not port_ok:
        print("Cannot bind any port.")
        return

    server = HTTPServer((HOST, PORT), Handler)
    server.allow_reuse_address = True
    threading.Thread(target=open_browser, daemon=True).start()

    has_api = "yes" if is_ai_available() else "no"
    print(f"\n  Claude Manager v1.1  |  http://{HOST}:{PORT}  |  data: {CLAUDE_DIR}  |  API: {has_api}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
