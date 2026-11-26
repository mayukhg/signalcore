"""Assemble everything the UI needs for one run into a single JSON document."""
import json
from collections import defaultdict

from .db import connect
from .pipeline.score import COD, W, START, WEEKS


def latest_run(db):
    r = db.execute("SELECT run_id FROM agent_runs WHERE status='done' ORDER BY started_at DESC LIMIT 1").fetchone()
    return r[0] if r else None


def build_state(db_path, run_id=None):
    db = connect(db_path)
    run_id = run_id or latest_run(db)
    if not run_id:
        return {"run": None}
    q = lambda sql, *a: [dict(r) for r in db.execute(sql, a).fetchall()]
    run = q("SELECT * FROM agent_runs WHERE run_id=?", run_id)[0]
    acct = {r["account_id"]: r for r in q("SELECT account_id, name, segment, arr_usd, renewal_date, is_customer FROM accounts")}
    modules = {r["module_id"]: r for r in q("SELECT * FROM modules")}
    fte = {r["module_id"]: r["eng_fte"] for r in q("SELECT module_id, eng_fte FROM capability_investments WHERE quarter='2026-Q4'")}
    gpl = q("""SELECT r.item_id, r.title, r.description, r.status, r.target_quarter, r.cited_sources, l.theme_id, l.similarity
               FROM roadmap_items r LEFT JOIN gpl_links l ON l.item_id = r.item_id AND l.run_id = ?""", run_id)
    themes = []
    for t in q("""SELECT t.*, s.* FROM themes t JOIN theme_scores s USING(run_id, theme_id) WHERE t.run_id=? ORDER BY s.priority_rank""", run_id):
        m = json.loads(t["metrics"])
        quotes = q("""SELECT e.feedback_id id, COALESCE(f.source,'cab_note') source, COALESCE(f.source_ref, c.meeting_id || ' line ' || c.line_no) ref,
                             COALESCE(f.account_id, c.account_id) account_id, COALESCE(f.created_at, m.held_on) at, COALESCE(f.body, c.text) body, e.urgency
                      FROM feedback_enrichment e LEFT JOIN qualitative_feedback f ON f.feedback_id = e.feedback_id
                      LEFT JOIN cab_items c ON c.item_id = e.feedback_id AND c.run_id = e.run_id
                      LEFT JOIN cab_meetings m ON m.meeting_id = c.meeting_id
                      WHERE e.run_id=? AND e.theme_id=? ORDER BY e.urgency DESC, e.feedback_id LIMIT 40""", run_id, t["theme_id"])
        seen, qs = set(), []
        for x in quotes:
            key = x["body"][:60]
            if key in seen: continue
            seen.add(key)
            a = acct.get(x["account_id"]) or {}
            qs.append({**x, "account": a.get("name"), "segment": a.get("segment"), "at": (x["at"] or "")[:10]})
            if len(qs) == 5: break
        sk = json.loads(t["skeptic_notes"]) if t["skeptic_notes"] else None
        opps = [{**o, "account_name": (acct.get(o["account"]) or {}).get("name")} for o in m.get("opps", [])]
        themes.append({
            "id": t["theme_id"], "title": t["title"], "stmt": t["problem_statement"], "module": t["module_id"], "feature": t["feature_key"],
            "keywords": t["keywords"], "size": t["size"],
            "Q": t["q_score"], "B": t["b_score"], "C": t["c_score"], "rule_penalty": t["rule_penalty"], "skeptic_penalty": t["skeptic_penalty"],
            "evidence": t["evidence_score"], "archetype": t["archetype"], "cod": t["cod_week_usd"], "cod_adj": t["cod_adj_week_usd"],
            "effort": t["effort_weeks"], "cd3": t["cd3"], "profile": t["urgency_profile"], "rank": t["priority_rank"],
            "cod_parts": m["cod"], "influenced": m["influenced"], "top_account": m["top_account"], "top_share": m["top_share"],
            "icp_share": m["icp_share"], "effort_conf": m["effort_conf"], "blocked_weeks": m["blocked_weeks"], "duration": m["duration"],
            "deps": m["deps"], "mentions": m["mentions"], "accounts": m["n_accounts"], "sources": m["sources"], "urgency": m["urgency"],
            "workaround": m["workaround"], "abandon": m["abandon"], "abandon_base": m["abandon_base"], "coverage": m["coverage"],
            "decline": m["decline"], "declining": len(m["declining"]), "cohort": m["cohort"], "opps": opps,
            "rule_notes": t["rule_notes"], "skeptic": sk, "skeptic_cited": json.loads(t["skeptic_citations"] or "[]"),
            "quotes": qs, "gpl": [g["item_id"] for g in gpl if g["theme_id"] == t["theme_id"]],
        })
    # modules: adoption + demand
    feats = defaultdict(list)
    for r in q("SELECT feature_key, module_id FROM features"): feats[r["module_id"]].append(r["feature_key"])
    wk = defaultdict(lambda: [set() for _ in range(WEEKS)])
    for r in db.execute("""SELECT f.module_id, t.account_id, CAST((julianday(substr(t.ts,1,10)) - julianday(?)) / 7 AS INT) w
                           FROM telemetry_events t JOIN features f USING(feature_key) WHERE t.event_name='task_started' GROUP BY 1,2,3""", (START.isoformat(),)):
        if 0 <= r[2] < WEEKS: wk[r[0]][r[2]].add(r[1])
    demand = defaultdict(float)
    for t in themes: demand[t["module"]] += t["cod_adj"]
    tf, td = sum(fte.values()), sum(demand.values()) or 1
    mods = []
    for mid, mm in modules.items():
        users = set().union(*wk[mid]) if wk[mid] else set()
        wau = [len(s) for s in wk[mid]]
        vel = (sum(wau[-8:]) / 8) / max(1, sum(wau[:8]) / 8) - 1 if wau else 0
        mods.append({"id": mid, "name": mm["name"], "stage": mm["lifecycle_stage"], "fte": fte.get(mid, 0), "fte_share": fte.get(mid, 0) / tf,
                     "demand_share": demand[mid] / td, "cod_adj": demand[mid], "arr": sum(acct[a]["arr_usd"] for a in users if a in acct),
                     "accounts": len(users), "velocity": vel, "wau": wau, "themes": [t["id"] for t in themes if t["module"] == mid]})
    epics = q("SELECT * FROM jira_epics")
    ev = {r["epic_key"]: r for r in q("SELECT * FROM epic_value WHERE run_id=?", run_id)}
    for e in epics:
        v = ev.get(e["epic_key"])
        e["own_cod"] = v["own_cod_week"] if v else 0
        e["inherited_cod"] = v["inherited_cod_week"] if v else 0
        e["unblocks"] = json.loads(v["unblocks"]) if v else []
        e["cd3"] = v["cd3"] if v else 0
        e["theme_id"] = next((t["id"] for t in themes if t["deps"].get("epic") == e["epic_key"]), None)
    links = q("SELECT from_key, to_key FROM jira_links")
    risks = q("SELECT * FROM risks WHERE run_id=? ORDER BY risk_id", run_id)
    for r in risks: r["citations"] = json.loads(r["citations"] or "[]")
    facts = {r["fact_id"]: r for r in q("SELECT fact_id, label, value, theme_id FROM facts WHERE run_id=?", run_id)}
    claims = {r["claim_id"]: r for r in q("SELECT * FROM brief_claims WHERE run_id=?", run_id)}
    cites = defaultdict(list)
    for r in q("SELECT claim_id, fact_id FROM evidence_citations WHERE run_id=?", run_id): cites[r["claim_id"]].append(r["fact_id"])
    pbr = {}
    names = {m["id"]: m["name"] for m in mods} | {"portfolio": "Portfolio"}
    for r in q("SELECT module_id, doc FROM pbr_docs WHERE run_id=?", run_id):
        d = json.loads(r["doc"])
        out = []
        for c in d["claims"]:
            cid = f"{r['module_id']}:{c['claim_id']}"
            cl = claims.get(cid, {})
            out.append({"id": cid, "section": c["section"], "text": c["text"], "status": cl.get("status", "grounded"), "attempt": cl.get("attempt", 1),
                        "judge": cl.get("judge_reason"), "facts": [facts[f] for f in cites.get(cid, []) if f in facts]})
        dropped = [c for c in claims.values() if c["claim_id"].startswith(r["module_id"] + ":") and c["status"] == "dropped"]
        pbr[r["module_id"]] = {"name": names.get(r["module_id"], r["module_id"]), "headline": d["headline"], "claims": out,
                               "dropped": [{"text": c["text"], "judge": c["judge_reason"]} for c in dropped]}
    cab = q("SELECT * FROM cab_meetings ORDER BY meeting_id")
    items = q("""SELECT c.*, a.name account_name, e.theme_id FROM cab_items c LEFT JOIN accounts a USING(account_id)
                 LEFT JOIN feedback_enrichment e ON e.feedback_id = c.item_id AND e.run_id = c.run_id WHERE c.run_id=?""", run_id)
    for m in cab: m["items"] = [i for i in items if i["meeting_id"] == m["meeting_id"]]
    steps = q("SELECT step_no, node, label, ms, model, tokens_in, tokens_out, cost_usd, detail FROM agent_steps WHERE run_id=? ORDER BY step_no", run_id)
    for s in steps: s["detail"] = json.loads(s["detail"] or "{}")
    evals = q("SELECT metric, value, detail FROM evals WHERE run_id=?", run_id)
    counts = {"feedback": db.execute("SELECT COUNT(*) FROM qualitative_feedback").fetchone()[0],
              "events": db.execute("SELECT COUNT(*) FROM telemetry_events").fetchone()[0],
              "opps": db.execute("SELECT COUNT(*) FROM crm_opportunities").fetchone()[0],
              "customers": db.execute("SELECT COUNT(*) FROM accounts WHERE is_customer=1").fetchone()[0],
              "arr": db.execute("SELECT SUM(arr_usd) FROM accounts").fetchone()[0],
              "cab_meetings": len(cab), "epics": len(epics)}
    runs = q("SELECT run_id, started_at, finished_at, mode, status, cost_usd FROM agent_runs ORDER BY started_at DESC LIMIT 20")
    overrides = q("SELECT * FROM pm_overrides ORDER BY override_id DESC LIMIT 50")
    asks = [json.loads(r["answer"]) for r in q("SELECT answer FROM ask_log ORDER BY ask_id DESC LIMIT 20")]
    estimates = q("SELECT * FROM feature_estimates")
    db.close()
    return {"run": run, "runs": runs, "counts": counts, "params": {"weights": W, "cod": COD}, "themes": themes, "modules": mods,
            "gpl": gpl, "epics": epics, "links": links, "risks": risks, "pbr": pbr, "cab": cab, "steps": steps, "evals": evals,
            "overrides": overrides, "asks": asks, "estimates": estimates}
