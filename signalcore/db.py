"""Database helpers, including the read-only, allow-listed connection agents use for SQL tools."""
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "signalcore.db"

# Tables an agent may read. Ground-truth tables and columns (gt_*) are never readable.
AGENT_TABLES = {"accounts", "contacts", "crm_opportunities", "qualitative_feedback", "telemetry_events", "features",
                "modules", "feature_estimates", "capability_investments", "roadmap_items", "jira_epics", "jira_links",
                "cab_meetings"}
RUN_VIEWS = {  # temp views pinned to one run, so agents don't need to know run ids
    "v_feedback": "SELECT f.feedback_id, f.source, f.source_ref, f.account_id, f.created_at, f.body, e.theme_id, e.urgency, "
                  "e.sentiment, e.mentions_workaround, e.persona FROM main.qualitative_feedback f "
                  "LEFT JOIN main.feedback_enrichment e ON e.feedback_id = f.feedback_id AND e.run_id = '{run}'",
    "v_cab_items": "SELECT c.item_id, c.meeting_id, c.line_no, c.account_id, c.speaker, c.kind, c.text, c.sentiment, e.theme_id "
                   "FROM main.cab_items c LEFT JOIN main.feedback_enrichment e ON e.feedback_id = c.item_id AND e.run_id = c.run_id "
                   "WHERE c.run_id = '{run}'",
    "v_themes": "SELECT theme_id, title, problem_statement, module_id, feature_key, size FROM main.themes WHERE run_id = '{run}'",
    "v_theme_scores": "SELECT * FROM main.theme_scores WHERE run_id = '{run}'",
    "v_dependency_paths": "SELECT * FROM main.dependency_paths WHERE run_id = '{run}'",
    "v_epic_value": "SELECT * FROM main.epic_value WHERE run_id = '{run}'",
    "v_opp_links": "SELECT opp_id, theme_id, similarity FROM main.opp_links WHERE run_id = '{run}'",
    "v_gpl_links": "SELECT item_id, theme_id, similarity FROM main.gpl_links WHERE run_id = '{run}'",
}
MAX_ROWS = 200
TIMEOUT_S = 8


def connect(path=DEFAULT_DB):
    db = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.row_factory = sqlite3.Row
    return db


def readonly(path, run_id):
    """A connection that can only SELECT from allow-listed tables and run views, with a time limit."""
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    for name, sql in RUN_VIEWS.items():
        db.execute(f"CREATE TEMP VIEW {name} AS " + sql.format(run=run_id.replace("'", "")))
    allowed = AGENT_TABLES | set(RUN_VIEWS) | {"feedback_enrichment", "cab_items", "themes", "theme_scores",
                                               "dependency_paths", "epic_value", "opp_links", "gpl_links"}

    def auth(action, arg1, arg2, dbname, source):
        if action == sqlite3.SQLITE_SELECT or action == sqlite3.SQLITE_FUNCTION:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            if arg1 not in allowed or (arg2 or "").startswith("gt_") or arg1 == "cab_gt":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    db.set_authorizer(auth)
    return db


def run_readonly_sql(conn, sql, max_rows=MAX_ROWS):
    """Execute one SELECT. Returns {columns, rows, truncated} or {error}."""
    s = sql.strip().rstrip(";")
    if ";" in s:
        return {"error": "Only one statement per call."}
    if not s.lower().lstrip("( ").startswith(("select", "with")):
        return {"error": "Only SELECT (or WITH ... SELECT) statements are allowed."}
    deadline = time.time() + TIMEOUT_S
    conn.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 20000)
    try:
        cur = conn.execute(s)
        cols = [d[0] for d in cur.description or []]
        rows = cur.fetchmany(max_rows + 1)
        return {"columns": cols, "rows": [list(r) for r in rows[:max_rows]], "truncated": len(rows) > max_rows}
    except sqlite3.Error as e:
        return {"error": f"{type(e).__name__}: {e}"}
    finally:
        conn.set_progress_handler(None, 0)
