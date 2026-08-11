import os
import sqlite3
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path


CLAUDE_CODE_APP_TYPE = "claude"
SESSION_SOURCE = "session_log"
PROXY_SOURCE = "proxy"


class CCSwitchUsageUnavailable(RuntimeError):
    pass


def default_database_path():
    return os.path.join(os.path.expanduser("~"), ".cc-switch", "cc-switch.db")


def _coerce_date(value):
    if value is None:
        return datetime.now().date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def _decimal(value):
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _connect_read_only(db_path):
    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        raise CCSwitchUsageUnavailable("CC Switch 数据库不存在")
    try:
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA busy_timeout=2000")
        return conn
    except sqlite3.Error as exc:
        raise CCSwitchUsageUnavailable("无法只读打开 CC Switch 数据库") from exc


def _validate_schema(conn):
    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='proxy_request_logs'"
    ).fetchone()
    if not table:
        raise CCSwitchUsageUnavailable("CC Switch 缺少用量记录表")
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(proxy_request_logs)")}
    required = {
        "request_id", "app_type", "model", "request_model", "input_tokens",
        "output_tokens", "cache_read_tokens", "cache_creation_tokens",
        "total_cost_usd", "status_code", "created_at", "data_source",
    }
    if not required.issubset(columns):
        raise CCSwitchUsageUnavailable("CC Switch 用量表结构不兼容")


def _source_for_claude_code(conn, start_epoch, end_epoch):
    rows = conn.execute(
        """
        SELECT data_source, COUNT(*) AS request_count,
               COALESCE(SUM(input_tokens + output_tokens + cache_read_tokens + cache_creation_tokens), 0) AS total_tokens,
               MAX(created_at) AS latest_at
        FROM proxy_request_logs
        WHERE app_type = ? AND created_at >= ? AND created_at < ?
        GROUP BY data_source
        """,
        (CLAUDE_CODE_APP_TYPE, start_epoch, end_epoch),
    ).fetchall()
    by_source = {row["data_source"]: dict(row) for row in rows}

    # Claude Code's imported CLI sessions are the cleanest source when present:
    # they are keyed as app_type=claude and avoid mixing in Codex/Claude Desktop.
    # Never add proxy + session rows together because the same request can appear
    # in both sources when local routing is enabled.
    if SESSION_SOURCE in by_source:
        return SESSION_SOURCE, by_source
    if PROXY_SOURCE in by_source:
        return PROXY_SOURCE, by_source
    if by_source:
        source = max(
            by_source,
            key=lambda key: (
                int(by_source[key].get("total_tokens") or 0),
                int(by_source[key].get("request_count") or 0),
            ),
        )
        return source, by_source
    return SESSION_SOURCE, by_source


def read_claude_code_usage(db_path=None, today=None, days=30):
    """Read CC Switch's Claude Code billing rows without exposing provider secrets."""
    if days < 1:
        raise ValueError("days must be positive")
    end_date = _coerce_date(today)
    start_date = end_date - timedelta(days=days - 1)
    start_epoch = int(datetime.combine(start_date, time.min).timestamp())
    end_epoch = int(datetime.combine(end_date + timedelta(days=1), time.min).timestamp())
    database_path = db_path or default_database_path()

    conn = _connect_read_only(database_path)
    try:
        _validate_schema(conn)
        data_source, source_summary = _source_for_claude_code(conn, start_epoch, end_epoch)
        rows = conn.execute(
            """
            SELECT request_id, model, request_model, input_tokens, output_tokens,
                   cache_read_tokens, cache_creation_tokens, total_cost_usd,
                   status_code, created_at
            FROM proxy_request_logs
            WHERE app_type = ? AND data_source = ?
              AND created_at >= ? AND created_at < ?
            ORDER BY created_at, request_id
            """,
            (CLAUDE_CODE_APP_TYPE, data_source, start_epoch, end_epoch),
        ).fetchall()
    except sqlite3.Error as exc:
        raise CCSwitchUsageUnavailable("读取 CC Switch 用量失败") from exc
    finally:
        conn.close()

    models = {}
    latest_at = 0
    for row in rows:
        model = str(row["model"] or row["request_model"] or "unknown")
        item = models.setdefault(model, {
            "model": model,
            "request_count": 0,
            "unique_responses": 0,
            "success_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "total_tokens": 0,
            "total_cost_usd": Decimal("0"),
        })
        item["request_count"] += 1
        item["unique_responses"] += 1
        item["success_count"] += int(200 <= int(row["status_code"] or 0) < 300)
        item["input_tokens"] += int(row["input_tokens"] or 0)
        item["output_tokens"] += int(row["output_tokens"] or 0)
        item["cache_read_tokens"] += int(row["cache_read_tokens"] or 0)
        item["cache_creation_tokens"] += int(row["cache_creation_tokens"] or 0)
        item["total_cost_usd"] += _decimal(row["total_cost_usd"])
        latest_at = max(latest_at, int(row["created_at"] or 0))

    items = []
    for item in models.values():
        item["total_tokens"] = (
            item["input_tokens"]
            + item["output_tokens"]
            + item["cache_read_tokens"]
            + item["cache_creation_tokens"]
        )
        item["total_cost_usd"] = format(item["total_cost_usd"], "f")
        items.append(item)
    items.sort(key=lambda item: (-item["total_tokens"], item["model"]))

    total_cost = sum((_decimal(item["total_cost_usd"]) for item in items), Decimal("0"))
    totals = {
        "request_count": sum(item["request_count"] for item in items),
        "success_count": sum(item["success_count"] for item in items),
        "input_tokens": sum(item["input_tokens"] for item in items),
        "output_tokens": sum(item["output_tokens"] for item in items),
        "cache_read_tokens": sum(item["cache_read_tokens"] for item in items),
        "cache_creation_tokens": sum(item["cache_creation_tokens"] for item in items),
        "total_tokens": sum(item["total_tokens"] for item in items),
        "total_cost_usd": format(total_cost, "f"),
    }
    return {
        "items": items,
        "totals": totals,
        "period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "days": days,
        },
        "source": {
            "id": "cc_switch",
            "label": "CC Switch · Claude Code",
            "app_type": CLAUDE_CODE_APP_TYPE,
            "data_source": data_source,
            "exact": True,
            "updated_at": (
                datetime.fromtimestamp(latest_at).astimezone().isoformat(timespec="seconds")
                if latest_at else ""
            ),
            "available_sources": sorted(source_summary),
        },
    }


def apply_to_dashboard(dashboard, usage):
    totals = usage["totals"]
    dashboard["api_usage"] = usage["items"]
    dashboard["api_usage_period"] = usage["period"]
    dashboard["usage_source"] = usage["source"]
    stats = dashboard.setdefault("stats", {})
    stats["api_request_count_30d"] = totals["request_count"]
    stats["api_unique_responses_30d"] = totals["request_count"]
    stats["api_input_output_tokens_30d"] = totals["input_tokens"] + totals["output_tokens"]
    stats["api_cache_tokens_30d"] = totals["cache_read_tokens"] + totals["cache_creation_tokens"]
    stats["api_tokens_30d"] = totals["total_tokens"]
    stats["api_cost_usd_30d"] = totals["total_cost_usd"]
    return dashboard


def mark_local_fallback(dashboard):
    dashboard["usage_source"] = {
        "id": "local_index",
        "label": "本机日志索引",
        "app_type": CLAUDE_CODE_APP_TYPE,
        "data_source": "manager_index",
        "exact": False,
        "updated_at": dashboard.get("last_scan", ""),
        "available_sources": [],
    }
    return dashboard
