"""Skeptic Agent: argues against each theme using read-only SQL. It may only lower confidence, with cited rows."""
import json
from concurrent.futures import ThreadPoolExecutor

from ..db import readonly, run_readonly_sql
from ..llm import HEAVY

SCHEMA_DOC = """Read-only SQLite. Useful tables and views (current run is pre-selected in v_* views):
- v_feedback(feedback_id, source, source_ref, account_id, created_at, body, theme_id, urgency, sentiment, mentions_workaround, persona)
- v_cab_items(item_id, meeting_id, line_no, account_id, speaker, kind, text, sentiment, theme_id)
- v_themes(theme_id, title, problem_statement, module_id, feature_key, size)
- v_theme_scores(theme_id, q_score, b_score, c_score, evidence_score, archetype, cod_week_usd, cd3, metrics JSON, ...)
- v_opp_links(opp_id, theme_id, similarity)  -- deals linked to themes by note text
- accounts(account_id, name, domain, segment, industry, is_customer, is_icp, seats, arr_usd, renewal_date, csm_health)
- crm_opportunities(opp_id, account_id, opp_type, stage, status, amount_usd, close_date, loss_reason, notes)
- telemetry_events(event_id, ts, account_id, user_hash, feature_key, event_name in task_started|task_completed|task_abandoned, duration_ms)  -- large: always filter by feature_key
- features(feature_key, module_id, name), jira_epics, jira_links(from_key blocks to_key), roadmap_items
Dates are ISO strings; today is 2026-11-26."""

SYSTEM = f"""You are the Skeptic Agent in a product-evidence pipeline. Your job is to try to REFUTE a product theme before it reaches the roadmap.
Look for: revenue concentrated in one account or prospect; complaints from accounts that don't use the feature; one loud source; duplicated or templated feedback;
friction that is normal for the feature; deals linked by weak text matches; renewal risk that is really about something else.
Run 2-4 focused SQL checks with run_sql, then call submit_verdict exactly once.
Rules: you may only LOWER confidence. extra_penalty is a multiplier between 0.5 and 1.0 (1.0 = the theme stands as scored).
Every claim in your reason must be backed by a check you ran; cite concrete ids (feedback_id, opp_id, account_id) in cited_ids.
Keep the reason to 2-3 plain sentences a product leader can read.

{SCHEMA_DOC}"""

TOOLS = [
    {"name": "run_sql", "description": "Run one read-only SELECT (max 200 rows returned). Filter telemetry_events by feature_key.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["sql"],
                      "properties": {"sql": {"type": "string"}}}, "strict": True},
    {"name": "submit_verdict", "description": "Submit your final verdict on the theme. Call exactly once, at the end.",
     "input_schema": {"type": "object", "additionalProperties": False,
                      "required": ["verdict", "extra_penalty", "reason", "checks", "cited_ids"],
                      "properties": {"verdict": {"type": "string", "enum": ["stands", "weakened", "refuted"]},
                                     "extra_penalty": {"type": "number"}, "reason": {"type": "string"},
                                     "checks": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                                           "required": ["question", "finding"],
                                                                           "properties": {"question": {"type": "string"}, "finding": {"type": "string"}}}},
                                     "cited_ids": {"type": "array", "items": {"type": "string"}}}}, "strict": True},
]


def brief_for(run, tid):
    t = run.q("SELECT title, problem_statement, feature_key FROM themes WHERE run_id=? AND theme_id=?", run.run_id, tid)[0]
    m, o = run.metrics[tid], run.scores[tid]
    return json.dumps({
        "theme_id": tid, "title": t[0], "problem_statement": t[1], "feature_key": t[2],
        "evidence_score_before_skeptic": o["evidence"], "pattern": o["archetype"],
        "pillars": {"say": o["Q"], "do": o["B"], "pay": o["C"]},
        "say": {"mentions": m["mentions"], "accounts": m["n_accounts"], "sources": m["sources"], "avg_urgency": m["urgency"], "workaround_rate": m["workaround"]},
        "do": {"abandon_rate_complainers": m["abandon"], "abandon_rate_others": m["abandon_base"], "complainers_using_feature": m["coverage"],
               "renewal_cohort_usage_decline": m["decline"], "declining_accounts": len(m["declining"])},
        "pay": {"dollars_influenced": round(o["influenced"]), "top_account": o["top_account"], "top_account_share": o["top_share"],
                "linked_deals": [d["id"] for d in m["opps"]][:15]},
        "cost_of_delay_per_week": round(o["cod"]["total"]), "rule_based_notes": o["notes"],
        "sample_feedback_ids": m["feedback_ids"][:12]}, ensure_ascii=False)


def skeptic(run):
    with run.step("skeptic", "Skeptic Agent · audit every theme with SQL") as s:
        tids = list(run.metrics)

        def one(tid):
            conn = readonly(run.db_path, run.run_id)
            trace = []
            ex = lambda name, inp: json.dumps(run_readonly_sql(conn, inp["sql"]), default=str)[:12000] if name == "run_sql" else "Unknown tool"
            v = run.llm.tool_loop("skeptic", model=HEAVY, system=SYSTEM, user="Audit this theme:\n" + brief_for(run, tid),
                                  tools=TOOLS, execute=ex, finish_tool="submit_verdict", effort="high", max_turns=7,
                                  meter=s.meter, trace=trace)
            conn.close()
            v = v or {"verdict": "stands", "extra_penalty": 1.0, "reason": "No verdict returned; score left unchanged.", "checks": [], "cited_ids": []}
            v["extra_penalty"] = max(.5, min(1.0, float(v.get("extra_penalty", 1.0))))
            if v["verdict"] == "stands": v["extra_penalty"] = 1.0
            v["sql"] = [t["input"].get("sql") for t in trace if t["tool"] == "run_sql"]
            return tid, v

        with ThreadPoolExecutor(4) as pool:
            verdicts = dict(pool.map(one, tids))
        run.skeptic = verdicts
        changed = {t: v for t, v in verdicts.items() if v["extra_penalty"] < 1}
        s.detail = {"summary": f"Audited {len(tids)} themes with {sum(len(v['sql']) for v in verdicts.values())} SQL checks; "
                               f"{len(changed)} weakened or refuted",
                    "verdicts": {t: {"verdict": v["verdict"], "penalty": v["extra_penalty"], "sql_checks": len(v["sql"])} for t, v in verdicts.items()}}
