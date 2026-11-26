"""PBR Agent writes Product Business Reviews from a fixed fact table; the Grounding Judge checks every claim.

The model never sees raw tables here: only numbered facts computed in SQL/code. Every claim must cite fact ids,
every number in a claim must match a cited fact (checked in code), and a second model checks the meaning."""
import json
import re
from concurrent.futures import ThreadPoolExecutor

from ..llm import HEAVY, JUDGE


def money(v):
    v = float(v)
    return f"${v / 1e6:.2f}M" if abs(v) >= 1e6 else f"${v / 1e3:.0f}K" if abs(v) >= 1e3 else f"${v:.0f}"


def build_facts(run):
    """Fact table per module + one portfolio doc ('portfolio'). Returns {doc_id: [facts]}."""
    titles = {r[0]: (r[1], r[2]) for r in run.q("SELECT theme_id, title, module_id FROM themes WHERE run_id=?", run.run_id)}
    mods = {r[0]: (r[1], r[2]) for r in run.q("SELECT module_id, name, lifecycle_stage FROM modules")}
    fte = dict(run.q("SELECT module_id, eng_fte FROM capability_investments WHERE quarter='2026-Q4'"))
    risks = run.q("SELECT risk_id, kind, severity, title, detail, cod_week, theme_id, module_id FROM risks WHERE run_id=?", run.run_id)
    feats = {}
    for f, m in run.q("SELECT feature_key, module_id FROM features"): feats.setdefault(m, []).append(f)
    docs, rows = {}, []

    def fact(doc, fid, label, value, theme=None, sql=None, hint=None):
        docs.setdefault(doc, []).append({"fact_id": fid, "label": label, "value": str(value), "section_hint": hint})
        rows.append((run.run_id, f"{doc}:{fid}", theme, label, str(value), sql))

    ranked = sorted(run.scores.items(), key=lambda kv: kv[1]["rank"])
    for mid, (name, stage) in mods.items():
        users = set().union(*[run.feat_users.get(f, set()) for f in feats.get(mid, [])]) if feats.get(mid) else set()
        arr = sum(run.acct[a]["arr"] for a in users)
        wau = [sum(1 for a in users if any(run.weekly[(a, f)][w] for f in feats[mid])) for w in range(26)] if users else [0] * 26
        vel = (sum(wau[-8:]) / 8) / max(1, sum(wau[:8]) / 8) - 1
        d = mid
        fact(d, "F1", f"{name} lifecycle stage", stage, hint="health")
        fact(d, "F2", f"Customer accounts using {name}", len(users), sql="distinct account_id in telemetry_events for module features", hint="health")
        fact(d, "F3", f"ARR of accounts using {name}", money(arr), hint="health")
        fact(d, "F4", f"Weekly active accounts change, last 8 vs first 8 weeks", f"{vel * 100:+.1f}%", hint="health")
        fact(d, "F5", f"Engineering FTE on {name} (2026-Q4)", fte.get(mid, 0), hint="health")
        n = 5
        for tid, o in ranked:
            if titles[tid][1] != mid: continue
            m = run.metrics[tid]
            dep = run.deps.get(tid, {})
            n += 1; fact(d, f"F{n}", f"Theme {tid} '{titles[tid][0]}': evidence score", o["evidence"], tid, hint="evidence")
            n += 1; fact(d, f"F{n}", f"Theme {tid}: pattern", o["archetype"].replace("_", " "), tid, hint="evidence")
            n += 1; fact(d, f"F{n}", f"Theme {tid}: accounts raising it", m["n_accounts"], tid, hint="evidence")
            n += 1; fact(d, f"F{n}", f"Theme {tid}: Cost of Delay per week", money(o["cod"]["total"]), tid, hint="priorities")
            n += 1; fact(d, f"F{n}", f"Theme {tid}: confidence-adjusted Cost of Delay per week", money(o["cod_adj"]), tid, hint="priorities")
            n += 1; fact(d, f"F{n}", f"Theme {tid}: CD3 portfolio rank", f"{o['rank']} of {len(ranked)}", tid, hint="priorities")
            n += 1; fact(d, f"F{n}", f"Theme {tid}: build estimate (weeks)", o["effort"], tid, hint="priorities")
            if m["decline"] >= .2:
                n += 1; fact(d, f"F{n}", f"Theme {tid}: usage decline in renewal cohort", f"{m['decline']:.0%}", tid, hint="risks")
            if m["abandon"] > m["abandon_base"] + .05:
                n += 1; fact(d, f"F{n}", f"Theme {tid}: task abandonment, complaining accounts vs others", f"{m['abandon']:.0%} vs {m['abandon_base']:.0%}", tid, hint="evidence")
            if dep.get("blocked_weeks"):
                n += 1; fact(d, f"F{n}", f"Theme {tid}: blocked by unfinished epics", f"{', '.join(dep['blockers'])} ({dep['blocked_weeks']:.0f} weeks on the critical path)", tid, hint="dependencies")
        for r in risks:
            if r[7] == mid:
                n += 1; fact(d, f"F{n}", f"Risk {r[0]} ({r[2]}): {r[3]}", r[4], r[6], hint="risks")
    # portfolio
    d = "portfolio"
    fact(d, "P1", "Customer ARR", money(sum(a["arr"] for a in run.acct.values())), hint="health")
    fact(d, "P2", "Themes scored this run", len(ranked), hint="evidence")
    n = 2
    for tid, o in ranked[:6]:
        n += 1; fact(d, f"P{n}", f"CD3 rank {o['rank']}: {tid} '{titles[tid][0]}' (evidence, pattern, CoD/week)",
                     f"{o['evidence']}, {o['archetype'].replace('_', ' ')}, {money(o['cod']['total'])}", tid, hint="priorities")
    for r in risks[:8]:
        n += 1; fact(d, f"P{n}", f"Risk {r[0]} ({r[2]}): {r[3]}", r[4], r[6], hint="risks")
    run.db.executemany("INSERT OR REPLACE INTO facts VALUES (?,?,?,?,?,?)", rows)
    run.db.commit()
    return docs


PBR_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["headline", "claims"], "properties": {
    "headline": {"type": "string"},
    "claims": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["claim_id", "section", "text", "fact_ids"],
                                          "properties": {"claim_id": {"type": "string"},
                                                         "section": {"type": "string", "enum": ["health", "evidence", "priorities", "risks", "dependencies", "asks"]},
                                                         "text": {"type": "string"}, "fact_ids": {"type": "array", "items": {"type": "string"}}}}}}}
PBR_SYSTEM = """You are the PBR Agent. You write a Product Business Review for a product leadership audience.
Use ONLY the facts provided. Every claim cites the fact_ids it relies on. Every number you write must appear in a cited fact (same value; you may round $138,339 to $138K but never invent or compute new numbers).
Structure: a headline with no numbers, then 6-10 short claims across sections health, evidence, priorities (ranked by CD3 = Cost of Delay ÷ duration), risks, dependencies, and asks (decisions you need from leadership).
Write plainly. One idea per claim, at most two sentences. Prefer what to do next over description."""

JUDGE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["verdicts"], "properties": {"verdicts": {"type": "array", "items": {
    "type": "object", "additionalProperties": False, "required": ["claim_id", "grounded", "reason"],
    "properties": {"claim_id": {"type": "string"}, "grounded": {"type": "boolean"}, "reason": {"type": "string"}}}}}}
JUDGE_SYSTEM = """You are the Grounding Judge. For each claim, decide whether it is fully supported by its cited facts.
Fail a claim if it states something the facts don't say, overstates certainty, implies causation the facts don't show, or recommends building something the facts label a commercial mirage or vocal minority.
Numbers have already been checked by code. Be strict but brief: one sentence of reason."""

ID = re.compile(r"\b([A-Z]{2,4}-\d+|TH-\d+|R\d{2}|[PF]\d+|\d{4}-Q\d|Q[1-4]|20\d\d-\d\d-\d\d)\b")
NUM = re.compile(r"\$?\d[\d,]*(?:\.\d+)?\s*[KkMm%]?")


def nums(text):
    out = []
    for t in NUM.findall(ID.sub(" ", text)):
        t = t.strip().replace(",", "")
        mult = 1e3 if t[-1:] in "Kk" else 1e6 if t[-1:] in "Mm" else 1
        try:
            out.append(float(t.strip("$%KkMm ")) * mult)
        except ValueError:
            pass
    return out


def numbers_ok(text, facts):
    have = [n for f in facts for n in nums(f["value"] + " " + f["label"])]
    bad = []
    for n in nums(text):
        if not any(abs(n - h) <= max(.5, .02 * abs(h)) for h in have):
            bad.append(n)
    return bad


def write_pbrs(run, only=None, feedback=None, attempt=1):
    label = "PBR Agent · write Product Business Reviews" + (f" (retry {attempt - 1})" if attempt > 1 else "")
    with run.step("pbr", label) as s:
        if not hasattr(run, "facts"):
            run.facts = build_facts(run)
        docs = [d for d in run.facts if (only is None or d in only)]
        names = dict(run.q("SELECT module_id, name FROM modules")) | {"portfolio": "Portfolio (executive summary)"}

        def one(doc):
            fx = run.facts[doc]
            extra = ""
            if feedback and doc in feedback:
                extra = "\n\nYour previous draft had claims the judge rejected. Fix or drop them:\n" + json.dumps(feedback[doc], ensure_ascii=False)
            user = f"Review for: {names[doc]}\n\nFACTS:\n{json.dumps(fx, ensure_ascii=False)}\n\nINSTRUCTIONS: cite fact_ids exactly as given.{extra}"
            out = run.llm.structured("pbr", model=HEAVY, system=PBR_SYSTEM, user=user, schema=PBR_SCHEMA, effort="high", meter=s.meter)
            return doc, out

        with ThreadPoolExecutor(4) as pool:
            res = dict(pool.map(one, docs))
        run.pbr = getattr(run, "pbr", {}) | res
        s.detail = {"summary": f"Drafted {len(res)} reviews with {sum(len(v['claims']) for v in res.values())} claims", "docs": list(res)}


def judge(run, attempt=1):
    with run.step("judge", "Grounding Judge · verify every claim" + (f" (round {attempt})" if attempt > 1 else "")) as s:
        failed, rows, cites = {}, [], []
        stats = dict(grounded=0, failed=0, number_fail=0)

        def one(doc):
            draft = run.pbr[doc]
            fx = {f["fact_id"]: f for f in run.facts[doc]}
            pre = {}
            for c in draft["claims"]:
                cf = [fx[i] for i in c["fact_ids"] if i in fx]
                problems = []
                if not cf: problems.append("cites no valid fact ids")
                bad = numbers_ok(c["text"], cf)
                if bad: problems.append("numbers not in cited facts: " + ", ".join(f"{b:g}" for b in bad))
                pre[c["claim_id"]] = problems
            payload = [{"claim_id": c["claim_id"], "text": c["text"], "facts": [fx[i] for i in c["fact_ids"] if i in fx]} for c in draft["claims"]]
            v = run.llm.structured("judge", model=JUDGE, system=JUDGE_SYSTEM, user="CLAIMS:\n" + json.dumps(payload, ensure_ascii=False),
                                   schema=JUDGE_SCHEMA, effort="medium", meter=s.meter)["verdicts"]
            return doc, pre, {x["claim_id"]: x for x in v}

        with ThreadPoolExecutor(4) as pool:
            results = list(pool.map(one, [d for d in run.pbr if d in getattr(run, "to_judge", run.pbr)]))
        for doc, pre, verdicts in results:
            run.db.execute("DELETE FROM brief_claims WHERE run_id=? AND claim_id LIKE ?", (run.run_id, doc + ":%"))
            run.db.execute("DELETE FROM evidence_citations WHERE run_id=? AND claim_id LIKE ?", (run.run_id, doc + ":%"))
            for c in run.pbr[doc]["claims"]:
                cid = f"{doc}:{c['claim_id']}"
                v = verdicts.get(c["claim_id"], {"grounded": False, "reason": "No verdict returned."})
                problems = pre[c["claim_id"]] + ([] if v["grounded"] else [v["reason"]])
                ok = not problems
                stats["grounded" if ok else "failed"] += 1
                stats["number_fail"] += bool(any("numbers" in p for p in pre[c["claim_id"]]))
                rows.append((run.run_id, cid, c["section"], c["text"], attempt, "grounded" if ok else "failed", "; ".join(problems) or v["reason"]))
                cites += [(run.run_id, cid, f"{doc}:{f}") for f in c["fact_ids"]]
                if not ok: failed.setdefault(doc, []).append({"claim_id": c["claim_id"], "text": c["text"], "problems": problems})
        run.db.executemany("INSERT OR REPLACE INTO brief_claims VALUES (?,?,?,?,?,?,?)", rows)
        run.db.executemany("INSERT OR REPLACE INTO evidence_citations VALUES (?,?,?)", cites)
        for doc in run.pbr:
            run.db.execute("INSERT OR REPLACE INTO pbr_docs VALUES (?,?,?)", (run.run_id, doc, json.dumps(run.pbr[doc], ensure_ascii=False)))
        run.db.commit()
        run.failed = failed
        s.detail = {"summary": f"{stats['grounded']} claims grounded, {stats['failed']} failed ({stats['number_fail']} on numbers)", **stats}
    return failed


def drop_failed(run):
    """After the last retry, drop claims that still fail."""
    with run.step("judge", "Grounding Judge · drop claims that still fail") as s:
        n = run.db.execute("UPDATE brief_claims SET status='dropped' WHERE run_id=? AND status='failed'", (run.run_id,)).rowcount
        for doc, fails in run.failed.items():
            ids = {f["claim_id"] for f in fails}
            run.pbr[doc]["claims"] = [c for c in run.pbr[doc]["claims"] if c["claim_id"] not in ids]
            run.db.execute("INSERT OR REPLACE INTO pbr_docs VALUES (?,?,?)", (run.run_id, doc, json.dumps(run.pbr[doc], ensure_ascii=False)))
        run.db.commit()
        s.detail = {"summary": f"Dropped {n} unsupported claims"}
