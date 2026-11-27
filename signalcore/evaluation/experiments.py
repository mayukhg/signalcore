"""Langfuse datasets and experiments for SignalCore.

    python -m signalcore.evaluation.experiments sync                     # create/refresh the three datasets
    python -m signalcore.evaluation.experiments run --suite planted      # no model calls; scores the latest pipeline run
    python -m signalcore.evaluation.experiments run --suite ask          # live Claude: golden questions, code + LLM-judge scores
    python -m signalcore.evaluation.experiments run --suite judge        # live Claude: calibrate the Grounding Judge
    python -m signalcore.evaluation.experiments run --suite all

Datasets (expected outputs come from ground truth the agents never see):
  signalcore-planted-themes      12 planted problems: was each found, mapped to the right feature, given the right pattern?
  signalcore-ask-golden          10 questions with required entities/numbers computed from the database
  signalcore-judge-calibration   real grounded PBR claims plus perturbed (unsupported) versions with known labels
"""
import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict

from .. import observability as obs
from ..ask import Retriever, ask
from ..db import DEFAULT_DB, connect
from ..llm import LLM, Meter
from ..pipeline.pbr import nums
from ..state import latest_run
from . import scorers

DS_PLANTED, DS_ASK, DS_JUDGE = "signalcore-planted-themes", "signalcore-ask-golden", "signalcore-judge-calibration"
PLANTED = {  # planted id -> (feature, expected pattern or None, short description)
    "T01": ("agent_policy_editor", "high_signal", "AI agent permissions can't be scoped"),
    "T02": ("scim_sync", "high_signal", "Workday SCIM provisioning fails silently"),
    "T03": ("saml_config", "commercial_mirage", "One prospect (Globex) wants SAML transforms"),
    "T04": ("patch_policies", "silent_churn", "Patch policies stall after OS upgrades; usage decays quietly"),
    "T05": ("linux_enroll", None, "Linux fleet enrollment is manual"),
    "T06": ("console_theme", "vocal_minority", "Dark mode for the admin console"),
    "T07": ("approval_flow", None, "Access-request approvals go stale"),
    "T08": ("browser_ext", None, "Password manager extension crashes in Safari"),
    "T09": ("remote_session", None, "Remote Assist latency in APAC"),
    "T10": ("device_trust", None, "No device trust for BYOD"),
    "T11": ("bulk_import", None, "Bulk CSV import errors"),
    "T12": ("conditional_access", None, "No conditional access policy simulator"),
}


def _id(*parts):
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:24]


# ------------------------------------------------------------------ dataset builders
def golden_questions(db):
    q = lambda sql, *a: db.execute(sql, a).fetchall()
    arr = q("SELECT COUNT(*), SUM(arr_usd) FROM accounts WHERE is_customer=1")[0]
    globex_amt = q("SELECT amount_usd FROM crm_opportunities o JOIN accounts a USING(account_id) WHERE a.name='Globex Holdings' AND status='open'")[0][0]
    fte = q("SELECT m.name, c.eng_fte FROM capability_investments c JOIN modules m USING(module_id) WHERE quarter='2026-Q4' ORDER BY eng_fte DESC LIMIT 1")[0]
    scim_renew = [r[0] for r in q("""SELECT DISTINCT a.name FROM qualitative_feedback f JOIN accounts a ON a.account_id = f.gt_account_id
                                     WHERE f.gt_theme_id='T02' AND a.is_customer=1 AND a.renewal_date <= date('2026-11-26','+90 day')
                                     ORDER BY a.arr_usd DESC LIMIT 3""")]
    agent_pipe = q("SELECT SUM(amount_usd) FROM crm_opportunities WHERE gt_theme_id='T01' AND status='open'")[0][0]
    cab = q("SELECT COUNT(*) FROM cab_meetings")[0][0]
    blockers = Counter(r[0] for r in q("SELECT from_key FROM jira_links"))
    top_blocker = blockers.most_common(1)[0][0]
    return [
        ("Which prospect is behind the request for custom SAML attribute transforms, and how large is that deal?",
         {"must_mention": ["Globex"], "numbers": [globex_amt], "notes": f"Globex Holdings, open new-logo deal of ${globex_amt:,}; a single-account request."}, "commercial_mirage"),
        ("Which Jira epic blocks the largest number of other epics, and has it started?",
         {"must_mention": [top_blocker], "notes": f"{top_blocker} blocks {blockers[top_blocker]} epics and is not started."}, "dependencies"),
        ("Which epic blocks the Slack and Teams approvals work for Access Requests?",
         {"must_mention": ["CON-14"], "notes": "CON-14 Notifications service v2 blocks ACR-9."}, "dependencies"),
        ("How many customer accounts are there, and what is their total ARR?",
         {"numbers": [arr[0], arr[1]], "notes": f"{arr[0]} customers, ${arr[1]:,} ARR."}, "lookup"),
        ("Which committed roadmap item depends on a single prospect?",
         {"must_mention": ["GPL-102"], "notes": "GPL-102 Globex SAML transform engine."}, "roadmap"),
        ("How many Customer Advisory Board meetings are recorded?",
         {"numbers": [cab], "notes": f"{cab} meetings."}, "lookup"),
        ("Which product module has the most engineering FTE this quarter, and how many?",
         {"must_mention": [fte[0].split(" ")[0]], "numbers": [fte[1]], "notes": f"{fte[0]} with {fte[1]} FTE in 2026-Q4."}, "lookup"),
        ("Which customers renewing in the next 90 days have complained about Workday or SCIM provisioning?",
         {"must_mention": scim_renew[:2], "notes": "Top by ARR: " + ", ".join(scim_renew)}, "renewal_risk"),
        ("Which feature shows the biggest gap in task abandonment between accounts that complain about it and everyone else?",
         {"must_mention": [["agent_policy_editor", "agent policy editor", "policy editor"]], "notes": "agent_policy_editor: ~44% vs ~11%."}, "telemetry"),
        ("How much open pipeline is blocked by AI agent permission gaps?",
         {"numbers": [agent_pipe], "notes": f"About ${agent_pipe:,} of open deals cite agent permission gaps.", "tolerance": .15}, "pipeline"),
    ]


def judge_cases(db, run_id):
    """Grounded claims with their facts, plus perturbed copies that should fail."""
    rows = db.execute("""SELECT c.claim_id, c.text FROM brief_claims c WHERE c.run_id=? AND c.status='grounded' ORDER BY c.claim_id""", (run_id,)).fetchall()
    facts = defaultdict(list)
    for cid, fid in db.execute("SELECT claim_id, fact_id FROM evidence_citations WHERE run_id=?", (run_id,)).fetchall():
        facts[cid].append(fid)
    fx = {r[0]: {"fact_id": r[0].split(":")[1], "label": r[1], "value": r[2]} for r in
          db.execute("SELECT fact_id, label, value FROM facts WHERE run_id=?", (run_id,)).fetchall()}
    cases = []
    for cid, text in rows:
        f = [fx[i] for i in facts.get(cid, []) if i in fx]
        if not f or not nums(text):
            continue
        cases.append((cid, "original", text, f, True))
        n = nums(text)[0]
        swapped = re.sub(r"\d[\d,]*(\.\d+)?", lambda m: f"{float(m.group().replace(',', '')) * 1.6:,.0f}", text, count=1)
        cases.append((cid, "number_changed", swapped, f, False))
        cases.append((cid, "causal_overclaim", text.rstrip(".") + ", which proves it is the main cause of churn across the whole portfolio.", f, False))
        if len(cases) >= 24:
            break
    return cases


def sync(db_path=DEFAULT_DB):
    lf = obs.client()
    db = connect(db_path)
    rid = latest_run(db)
    for name, desc in ((DS_PLANTED, "Planted problems in the synthetic tenant; expected feature and pattern"),
                       (DS_ASK, "Golden questions for Ask the evidence; expected entities/numbers from ground truth"),
                       (DS_JUDGE, "Grounding Judge calibration: grounded claims and perturbed copies with known labels")):
        lf.create_dataset(name=name, description=desc, metadata={"source": "signalcore", "seed": 42})
    for pid, (feat, pattern, desc) in PLANTED.items():
        lf.create_dataset_item(dataset_name=DS_PLANTED, id=_id(DS_PLANTED, pid), input={"planted_id": pid, "description": desc},
                               expected_output={"feature_key": feat, "pattern": pattern}, metadata={"planted_id": pid})
    for qtext, exp, cat in golden_questions(db):
        lf.create_dataset_item(dataset_name=DS_ASK, id=_id(DS_ASK, qtext), input={"question": qtext}, expected_output=exp, metadata={"category": cat})
    jc = judge_cases(db, rid)
    for cid, kind, text, facts, label in jc:
        lf.create_dataset_item(dataset_name=DS_JUDGE, id=_id(DS_JUDGE, cid, kind), input={"claim": text, "facts": facts},
                               expected_output={"grounded": label}, metadata={"kind": kind, "source_claim": cid, "source_run": rid})
    obs.flush()
    db.close()
    return {"planted": len(PLANTED), "ask": len(golden_questions(connect(db_path))), "judge": len(jc)}


# ------------------------------------------------------------------ suites
def _get(item, attr):
    return getattr(item, attr, None) if not isinstance(item, dict) else item.get(attr)


def run_planted(lf, db_path, run_id):
    db = connect(db_path)
    rows = db.execute("""SELECT e.theme_id, f.gt_theme_id FROM feedback_enrichment e JOIN qualitative_feedback f USING(feedback_id)
                         WHERE e.run_id=? AND e.theme_id IS NOT NULL""", (run_id,)).fetchall()
    counts = defaultdict(Counter)
    for th, gt in rows:
        counts[gt][th] += 1
    scores = {r[0]: r for r in db.execute("""SELECT s.theme_id, t.title, t.feature_key, s.archetype, s.evidence_score, s.priority_rank
                                            FROM theme_scores s JOIN themes t USING(run_id, theme_id) WHERE s.run_id=?""", (run_id,)).fetchall()}
    db.close()

    def task(*, item, **kw):
        pid = _get(item, "input")["planted_id"]
        if not counts.get(pid):
            return {"found": False}
        th = counts[pid].most_common(1)[0][0]
        s = scores.get(th)
        purity = counts[pid][th] / sum(counts[pid].values())
        return {"found": True, "theme_id": th, "title": s[1], "feature_key": s[2], "pattern": s[3], "evidence": s[4], "rank": s[5],
                "share_of_items_in_main_cluster": round(purity, 3)}

    def ev_found(*, output, **kw):
        return {"name": "theme_found", "value": 1.0 if output.get("found") else 0.0}

    def ev_feature(*, output, expected_output, **kw):
        ok = output.get("feature_key") == expected_output["feature_key"]
        return {"name": "feature_match", "value": 1.0 if ok else 0.0, "comment": f"got {output.get('feature_key')}, want {expected_output['feature_key']}"}

    def ev_pattern(*, output, expected_output, **kw):
        want = expected_output.get("pattern")
        if not want:
            return []
        ok = output.get("pattern") == want
        return {"name": "pattern_match", "value": 1.0 if ok else 0.0, "comment": f"got {output.get('pattern')}, want {want}"}

    return lf.run_experiment(name=DS_PLANTED, run_name=f"pipeline {run_id}", description="Recovery of planted themes by a pipeline run",
                             data=lf.get_dataset(DS_PLANTED).items, task=task, evaluators=[ev_found, ev_feature, ev_pattern],
                             run_evaluators=[_mean("theme_found"), _mean("feature_match"), _mean("pattern_match")],
                             metadata={"pipeline_run": run_id}, max_concurrency=4)


def run_ask(lf, db_path, run_id, llm):
    retr = Retriever(db_path, run_id)
    known = {r["id"] for r in retr.rows}
    judge_llm = llm

    def task(*, item, **kw):
        from ..observability import Ctx
        parent = Ctx(lf.get_current_trace_id(), lf.get_current_observation_id())
        return ask(_get(item, "input")["question"], db_path, run_id, llm, retr, parent_ctx=parent)

    def ev_code(*, output, expected_output, **kw):
        res = [scorers.expected_entities(output, expected_output), scorers.numbers_grounded(output),
               scorers.citation_validity(output, known), _expected_numbers(output, expected_output)]
        return [r for r in res if r]

    def ev_judge(*, input, output, expected_output, **kw):
        if judge_llm.mode == "stub":
            return []
        return scorers.llm_judge_ask(judge_llm, input["question"], output, expected_output, meter=Meter())

    def ev_cost(*, output, **kw):
        return [{"name": "cost_usd", "value": float(output.get("cost_usd", 0))}, {"name": "latency_s", "value": float(output.get("seconds", 0))}]

    return lf.run_experiment(name=DS_ASK, run_name=f"ask {run_id} {llm.mode}", description="Ask the evidence on golden questions",
                             data=lf.get_dataset(DS_ASK).items, task=task, evaluators=[ev_code, ev_judge, ev_cost],
                             run_evaluators=[_mean("expected_entities"), _mean("expected_numbers"), _mean("numbers_grounded"),
                                             _mean("judge_correctness"), _mean("judge_groundedness"), _mean("cost_usd")],
                             metadata={"pipeline_run": run_id, "mode": llm.mode}, max_concurrency=3)


def run_judge(lf, llm):
    def task(*, item, **kw):
        inp = _get(item, "input")
        return scorers.grounding_judge_single(llm, inp["claim"], inp["facts"], meter=Meter())

    def ev(*, output, expected_output, metadata, **kw):
        want = expected_output["grounded"]
        got = bool(output.get("grounded"))
        res = [{"name": "label_correct", "value": 1.0 if got == want else 0.0, "comment": output.get("reason", "")[:300]}]
        if not want:
            res.append({"name": "false_pass", "value": 1.0 if got else 0.0, "comment": f"perturbation: {(metadata or {}).get('kind')}"})
        return res

    return lf.run_experiment(name=DS_JUDGE, run_name=f"grounding judge {llm.mode}", description="Grounding Judge accuracy on labelled claims",
                             data=lf.get_dataset(DS_JUDGE).items, task=task, evaluators=[ev],
                             run_evaluators=[_mean("label_correct"), _mean("false_pass")], max_concurrency=4)


# ------------------------------------------------------------------ helpers
def _mean(name):
    def run_eval(*, item_results, **kw):
        vals = [e.value for r in item_results for e in (r.evaluations or []) if e.name == name and isinstance(e.value, (int, float))]
        if not vals:
            return []
        return {"name": f"avg_{name}", "value": round(sum(vals) / len(vals), 4), "comment": f"n={len(vals)}"}
    run_eval.__name__ = f"avg_{name}"
    return run_eval


def _expected_numbers(out, expected):
    want = expected.get("numbers") or []
    if not want:
        return None
    have = nums(out.get("answer", ""))
    tol = expected.get("tolerance", .02)
    hit = [w for w in want if any(abs(h - w) <= max(.5, tol * abs(w)) for h in have)]
    return {"name": "expected_numbers", "value": round(len(hit) / len(want), 3), "comment": f"{len(hit)}/{len(want)} expected numbers present"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["sync", "run"])
    ap.add_argument("--suite", default="planted", choices=["planted", "ask", "judge", "all"])
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--mode", default=None, help="live | replay | stub for the ask/judge suites")
    a = ap.parse_args()
    if not obs.enabled():
        raise SystemExit("Set LANGFUSE_BASE_URL (and keys, unless your proxy injects them).")
    lf = obs.client()
    if a.cmd == "sync":
        print("datasets synced:", sync())
        return
    db = connect(DEFAULT_DB)
    rid = a.run_id or latest_run(db)
    db.close()
    llm = LLM(a.mode)
    results = []
    if a.suite in ("planted", "all"):
        results.append(run_planted(lf, DEFAULT_DB, rid))
    if a.suite in ("ask", "all"):
        results.append(run_ask(lf, DEFAULT_DB, rid, llm))
    if a.suite in ("judge", "all"):
        results.append(run_judge(lf, llm))
    obs.flush()
    for r in results:
        print(f"\n== {r.name} · {r.run_name}")
        for e in r.run_evaluations:
            print(f"  {e.name}: {e.value}  ({e.comment})")
        print("  ", r.experiment_url or "")


if __name__ == "__main__":
    main()
