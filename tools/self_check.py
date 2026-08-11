import pathlib
import py_compile
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
EXPECTED_UI_VERSION = "v2.0 preview.14"


def read(path):
    return path.read_text(encoding="utf-8")


def check(name, ok, detail=""):
    mark = "OK" if ok else "FAIL"
    suffix = f" - {detail}" if detail else ""
    print(f"[{mark}] {name}{suffix}")
    return ok


def main():
    app = read(ROOT / "app.py")
    index = read(ROOT / "static" / "index.html")
    js = read(ROOT / "static" / "app.js")
    css = read(ROOT / "static" / "style.css")
    v2 = read(ROOT / "v2_index.py")
    cc_usage = read(ROOT / "cc_switch_usage.py")
    spec = read(ROOT / "ClaudeCodeManager.spec")
    requirements = read(ROOT / "requirements.txt")

    checks = []
    try:
        py_compile.compile(str(ROOT / "app.py"), doraise=True)
        py_compile.compile(str(ROOT / "v2_index.py"), doraise=True)
        checks.append(check("python syntax", True))
    except py_compile.PyCompileError as exc:
        checks.append(check("python syntax", False, str(exc)))

    checks.append(check("index sidebar version", EXPECTED_UI_VERSION in index))
    checks.append(check("v2 module imported", "import v2_index" in app))
    checks.append(check("sqlite index path", "manager-index.sqlite3" in app))
    checks.append(check("shared sqlite index", "INDEX_DATA_DIR" in app and "LOCALAPPDATA" in app))
    checks.append(check("v2 routes mounted", "_handle_v2_get" in app and "/api/v2/reindex" in app))
    checks.append(check("incremental scan exists", "scan_incremental" in v2 and "scan_files" in v2))
    checks.append(check("fts search exists", "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts" in v2))
    checks.append(check("project pagination api", "list_projects" in v2 and "LIMIT ? OFFSET ?" in v2))
    checks.append(check("session pagination api", "session_detail" in v2 and "messages" in v2))
    checks.append(check("new frontend uses v2 api", "/api/v2/dashboard" in js and "/api/v2/session/" in js))
    checks.append(check("api usage schema exists", "api_usage_events" in v2 and "response_id" in v2))
    checks.append(check("dashboard API usage is deduplicated", "PARTITION BY response_id" in v2 and "按唯一响应去重" in js))
    checks.append(check("dashboard uses 30 day window", "timedelta(days=29)" in v2 and "近 30 天 Token" in js))
    checks.append(check("CC Switch usage integration", "import cc_switch_usage" in app and "app_type = ?" in cc_usage and "CLAUDE_CODE_APP_TYPE" in cc_usage))
    checks.append(check("CC Switch usage endpoint", 'subpath == "usage"' in app and "/api/v2/usage" in js))
    checks.append(check("dashboard usage auto refresh", "scheduleUsagePolling" in js and "60000" in js and "每分钟" in js))
    checks.append(check("v2 soft delete exists", "/api/v2/trash-project" in app and "/api/v2/trash-session" in app))
    checks.append(check("ai actions restored", "describeProject" in js and "summarizeSession" in js and "summarizeProject" in js))
    checks.append(check("one-click descriptions visible", "一键生成全部简介" in js and "/api/describe-all" in js))
    checks.append(check("legacy API config recovery", "legacy_api_config_candidates" in app and "Recovered API configuration" in app))
    checks.append(check("API key stays masked", "api_key_masked" in app and "留空保留原密钥" in js))
    checks.append(check("permission selector restored", "const PERMISSIONS" in js and "launch-permission" in js))
    checks.append(check("structured Agent action folding", "appendConversationMessages" in js and "pairAgentActions" in js and "agent-action-group" in css))
    checks.append(check("tool calls pair with results", "tool_use_id" in js and "callsById" in js and "执行结果" in js))
    checks.append(check("human-readable messages stay visible", 'segment.type === "action"' in js and "messageBlock(message, segment.text)" in js))
    checks.append(check("machine context folds away", "machineContextSegment" in js and "上下文与本地命令记录" in js))
    checks.append(check("directory browser restored", "project-dirs" in app and "directoryBrowser" in js and "dirParts" in js))
    checks.append(check("session list actions restored", "sessionEntry" in js and "open-launch" in js))
    checks.append(check("session row click target", 'className: `list-row${canSelect ? " has-check" : " is-clickable"}' in js and ".list-row.is-clickable" in css))
    checks.append(check("breadcrumb actions keep project id", js.index('closest("[data-action]")') < js.index('closest("[data-route]")')))
    checks.append(check("session folder opener", 'button("打开所在文件夹", "open-project-directory"' in js))
    checks.append(check("portable Claude data discovery", "resolve_claude_dir" in app and "CLAUDE_CONFIG_DIR" in app and "--claude-dir" in app))
    checks.append(check("project folder opener", "/api/open-directory" in app and "open_directory_in_file_manager" in app and "open-project-directory" in js))
    checks.append(check("batch trash restored", "/api/v2/trash-projects" in app and "/api/v2/trash-sessions" in app and "trashSelectedProjects" in js and "trashSelectedSessions" in js))
    checks.append(check("sessions nav exists", "data-route=\"sessions\"" in index))
    checks.append(check("responsive layout exists", "@media (max-width: 780px)" in css))
    checks.append(check("standard permission default preserved", '"std":   None' in app))
    checks.append(check("resume launch preserved", "--resume" in app and "resolve_session_launch_path" in app))
    checks.append(check("resume uses project cwd", 'meta.get("cwd_initial")' in app and 'project_path = resolve_project_path(project_id)' in app))
    checks.append(check("project cwd stays root", "cwd = COALESCE(NULLIF(name, ''), cwd)" in v2))
    checks.append(check("port fallback exists", "PORT_FALLBACK_LIMIT" in app and "bind_server" in app and "is_manager_running" in app))
    checks.append(check("desktop window runtime", "run_desktop_window" in app and "import webview" in app and "edgechromium" in app))
    checks.append(check("desktop dependencies", "pywebview==" in requirements and "webview.platforms.winforms" in spec))
    checks.append(check("desktop runtime DLLs", "libexpat.dll" in spec and "liblzma.dll" in spec and "libbz2.dll" in spec))
    checks.append(check("desktop package slimming", "'numpy'" in spec and "'PIL'" in spec and "'webview.platforms.qt'" in spec))
    checks.append(check("single instance activates window", "/api/desktop/activate" in app and "activate_existing_manager" in app))
    checks.append(check("concurrent HTTP server", "ThreadingHTTPServer" in app and "daemon_threads = True" in app))
    checks.append(check("HTTP response caching", "_static_cache" in app and "ETag" in app and "Content-Length" in app))
    checks.append(check("unchanged index fast path", "known_files" in v2 and "index_changed" in v2 and "_refresh_project_path_state" in v2))
    checks.append(check("path mapping exists", "PATH_MAPPINGS_FILE" in app and "/api/v2/path-map" in app and "apply_path_mapping" in app))
    checks.append(check("session migration exists", "/api/v2/migrate-project" in app and "migrate_project_records" in app and "write_migrated_jsonl" in app))
    checks.append(check("resume migration guard exists", "resume_migration_hint" in app and "needs_migration" in app))
    checks.append(check("mapping ui exists", "map-project" in js and "migrateProject" in js and "目录重定向" in js))
    checks.append(check("session lineage schema", "session_kind" in v2 and "parent_session_id" in v2 and "child_count" in v2))
    checks.append(check("subagent discovery", "_discover_session_files" in v2 and "isSidechain" in v2))
    checks.append(check("session lineage ui", "child-session-group" in js and "automaticSessionsPanel" in js))
    checks.append(check("source data dir exists", (ROOT / "data").exists()))

    if not all(checks):
        sys.exit(1)
    print("\nSelf-check passed.")


if __name__ == "__main__":
    main()
