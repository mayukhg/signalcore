"""Deterministic core: triangulation metrics, Evidence Score, Cost of Delay, CD3 and dependency tracing.

Evidence Score (0-100) = confidence that a theme is real and material.
Cost of Delay ($/week) = what waiting one more week costs, before confidence.
CD3 = CoD x (evidence/100) / (build weeks + weeks blocked by unfinished dependencies).
"""
import datetime as dt
import json
import math
from collections import defaultdict

TODAY = dt.date(2026, 11, 26)
WEEKS = 26
START = TODAY - dt.timedelta(weeks=WEEKS)

# Cost of Delay parameters (shown in the app; tune per business)
COD = dict(churn_base=.03, churn_severity=.22, horizon_weeks=52, min_weeks=4,
           win_uplift=.25, lost_echo=.10, lost_echo_weeks=26, deal_min_weeks=2)
W = dict(q=.30, b=.35, c=.35)


def clip(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def weeks_until(d):
    return (dt.date.fromisoformat(d) - TODAY).days / 7


def triangulate(run):
    """Per-theme pillar metrics from SQL over the three pillars."""
    with run.step("triangulate", "Triangulation · join themes to telemetry and revenue") as s:
        q = run.q
        acct = {r[0]: dict(id=r[0], name=r[1], seg=r[2], icp=r[3], arr=r[4], renew=r[5], cust=r[6])
                for r in q("SELECT account_id, name, segment, is_icp, arr_usd, renewal_date, is_customer FROM accounts")}
        ab = defaultdict(lambda: [0, 0])
        weekly = defaultdict(lambda: [0] * WEEKS)
        for a, f, ev, wk, n in q("""SELECT account_id, feature_key, event_name,
                                         CAST((julianday(substr(ts,1,10)) - julianday(?)) / 7 AS INT) AS wk, COUNT(*)
                                    FROM telemetry_events WHERE event_name != 'task_started' GROUP BY 1,2,3,4""", START.isoformat()):
            ab[(a, f)][0] += n if ev == "task_abandoned" else 0
            ab[(a, f)][1] += n
            if 0 <= wk < WEEKS: weekly[(a, f)][wk] += n
        feat_users = defaultdict(set)
        for (a, f) in ab: feat_users[f].add(a)
        run.acct, run.weekly, run.feat_users = acct, weekly, feat_users
        metrics = {}
        for tid, title, feat in q("SELECT theme_id, title, feature_key FROM themes WHERE run_id=?", run.run_id):
            fb = q("""SELECT e.feedback_id, COALESCE(f.source, 'cab_note'), COALESCE(f.account_id, c.account_id), e.urgency, e.mentions_workaround, e.persona
                      FROM feedback_enrichment e LEFT JOIN qualitative_feedback f ON f.feedback_id = e.feedback_id
                      LEFT JOIN cab_items c ON c.item_id = e.feedback_id AND c.run_id = e.run_id
                      WHERE e.run_id=? AND e.theme_id=?""", run.run_id, tid)
            accts = sorted({r[2] for r in fb if r[2]})
            sources = defaultdict(int)
            for r in fb: sources[r[1]] += 1
            urg = sum(r[3] for r in fb) / len(fb)
            wkr = sum(r[4] for r in fb) / len(fb)
            users = [a for a in accts if (a, feat) in ab]
            coverage = len(users) / len(accts) if accts else 0
            m_ab = sum(ab[(a, feat)][0] for a in users) / max(1, sum(ab[(a, feat)][1] for a in users)) if users else 0
            others = [a for a in feat_users.get(feat, ()) if a not in set(accts)]
            base = sum(ab[(a, feat)][0] for a in others) / max(1, sum(ab[(a, feat)][1] for a in others)) if others else .11
            cohort = [a for a in feat_users.get(feat, ()) if acct[a]["seg"] != "SMB" and acct[a]["renew"] and weeks_until(acct[a]["renew"]) <= 150 / 7]
            early = sum(sum(weekly[(a, feat)][6:12]) for a in cohort)
            late = sum(sum(weekly[(a, feat)][-6:]) for a in cohort)
            decline = clip(1 - late / early) if early > 20 else 0
            declining = [a for a in cohort if sum(weekly[(a, feat)][-6:]) < .7 * max(1, sum(weekly[(a, feat)][6:12]))] if decline > .2 else []
            opps = q("""SELECT o.opp_id, o.account_id, o.opp_type, o.status, o.amount_usd, o.close_date FROM opp_links l
                        JOIN crm_opportunities o USING(opp_id) WHERE l.run_id=? AND l.theme_id=? AND o.status IN ('open','lost')""", run.run_id, tid)
            metrics[tid] = dict(feature=feat, mentions=len(fb), accounts=accts, n_accounts=len(accts), sources=dict(sources),
                                urgency=round(urg, 2), workaround=round(wkr, 2), abandon=round(m_ab, 3), abandon_base=round(base, 3),
                                coverage=round(coverage, 2), decline=round(decline, 2), declining=declining, cohort=len(cohort),
                                opps=[dict(id=o[0], account=o[1], type=o[2], status=o[3], amount=o[4], close=o[5]) for o in opps],
                                feedback_ids=[r[0] for r in fb])
        run.metrics = metrics
        s.detail = {"summary": f"Computed Say/Do/Pay metrics for {len(metrics)} themes",
                    "sql": ["abandonment by account × feature (telemetry_events)", "renewal-cohort usage decline, weeks 6-12 vs last 6",
                            "linked open/lost deals (opp_links × crm_opportunities)"]}


def trace_dependencies(run):
    """Dependency Tracer: theme -> Jira epic -> unfinished blockers (transitive) and critical-path weeks."""
    with run.step("deps", "Dependency Tracer · cross-portfolio Jira links") as s:
        epics = {r[0]: dict(key=r[0], module=r[1], title=r[2], status=r[3], feature=r[4], weeks=r[5], team=r[6])
                 for r in run.q("SELECT epic_key, module_id, title, status, feature_key, remaining_weeks, owner_team FROM jira_epics")}
        preds = defaultdict(list)
        for a, b in run.q("SELECT from_key, to_key FROM jira_links"): preds[b].append(a)

        def chain(k, seen=()):
            """Longest remaining-weeks path of unfinished predecessors."""
            best, path = 0.0, []
            for p in preds[k]:
                if p in seen or epics[p]["status"] == "done": continue
                w, pth = chain(p, seen + (k,))
                w += epics[p]["weeks"]
                if w > best: best, path = w, pth + [p]
            return best, path

        def ancestors(k, acc=None):
            acc = acc if acc is not None else set()
            for p in preds[k]:
                if p not in acc and epics[p]["status"] != "done":
                    acc.add(p); ancestors(p, acc)
            return acc

        by_feat = {e["feature"]: k for k, e in epics.items() if e["feature"]}
        rows, out = [], {}
        for tid, m in run.metrics.items():
            ek = by_feat.get(m["feature"])
            if not ek:
                out[tid] = dict(epic=None, blockers=[], blocked_weeks=0, path=[]); continue
            w, path = chain(ek)
            bl = sorted(ancestors(ek))
            out[tid] = dict(epic=ek, blockers=bl, blocked_weeks=w, path=path + [ek])
            rows.append((run.run_id, tid, ek, json.dumps(bl), w, " → ".join(path + [ek])))
        run.db.executemany("INSERT OR REPLACE INTO dependency_paths VALUES (?,?,?,?,?,?)", rows)
        run.db.commit()
        run.epics, run.deps, run.preds = epics, out, preds
        blocked = [t for t, d in out.items() if d["blocked_weeks"] > 0]
        s.detail = {"summary": f"Mapped {len(rows)} themes to epics; {len(blocked)} are blocked by unfinished cross-team work",
                    "paths": {t: d["path"] for t, d in out.items() if d["path"]}}


def _cod(m, acct, sev):
    """Cost of Delay per week, by component, with the accounts/deals behind it."""
    p_churn = COD["churn_base"] + COD["churn_severity"] * sev
    retention, near, parts, biggest_dated = 0.0, 0.0, [], 0.0
    for a in set(m["accounts"]) | set(m["declining"]):
        x = acct[a]
        if not x["cust"] or not x["renew"]: continue
        wk = weeks_until(x["renew"])
        if wk > COD["horizon_weeks"]: continue
        w = x["arr"] * p_churn / max(wk, COD["min_weeks"])
        retention += w
        if wk <= 13:
            near += w; biggest_dated = max(biggest_dated, w)
        parts.append((a, round(w)))
    pipeline = 0.0
    for o in m["opps"]:
        if o["status"] == "open":
            wk = weeks_until(o["close"])
            if wk < 0: wk = COD["deal_min_weeks"]
            w = o["amount"] * COD["win_uplift"] / max(wk, COD["deal_min_weeks"])
        else:
            w = o["amount"] * COD["lost_echo"] / COD["lost_echo_weeks"]
        pipeline += w
        if o["status"] == "open" and 0 <= weeks_until(o["close"]) <= 13:
            near += w; biggest_dated = max(biggest_dated, w)
    total = retention + pipeline
    return dict(total=total, retention=retention, pipeline=pipeline, near_share=(near / total if total else 0),
                dated_share=(biggest_dated / total if total else 0),
                p_churn=round(p_churn, 3), top_accounts=sorted(parts, key=lambda x: -x[1])[:5])


def score(run, skeptic=None):
    """Evidence Score, pattern, Cost of Delay and CD3 for every theme. `skeptic` = {theme_id: verdict} to apply."""
    with run.step("score", "Scoring · Evidence Score, Cost of Delay, CD3" + (" (after skeptic)" if skeptic else "")) as s:
        acct = run.acct
        est = {r[0]: (r[1], r[2]) for r in run.q("SELECT feature_key, effort_weeks, estimate_confidence FROM feature_estimates")}
        for tid, fk, v in run.q("""SELECT theme_id, field, new_value FROM pm_overrides o
                                   WHERE field LIKE 'effort:%' ORDER BY override_id"""):
            est[fk.split(":", 1)[1]] = (float(v), "pm override")
        out = {}
        for tid, m in run.metrics.items():
            Q = clip(.45 * clip(math.log1p(m["n_accounts"]) / math.log1p(50)) + .2 * len(m["sources"]) / 6
                     + .25 * (m["urgency"] - 1) / 4 + .1 * clip(m["workaround"] / .5))
            fric = clip((m["abandon"] - m["abandon_base"]) / .3) * (.4 + .6 * m["coverage"])
            B = clip(max(fric, m["decline"] / .45))
            urg_w = clip((m["urgency"] - 1) / 3)
            dollars = defaultdict(float)
            for a in m["accounts"]:
                if acct[a]["cust"]: dollars[a] += acct[a]["arr"] * urg_w
            for a in m["declining"]: dollars[a] = max(dollars[a], acct[a]["arr"])
            for o in m["opps"]: dollars[o["account"]] += o["amount"]
            total = sum(dollars.values())
            top = max(dollars.items(), key=lambda kv: kv[1]) if dollars else (None, 0)
            top_share = top[1] / total if total else 0
            icp = sum(v for k, v in dollars.items() if acct[k]["icp"]) / total if total else 0
            C = clip((math.log10(max(total, 1)) - 4.6) / 2.1) * (.75 + .25 * icp)
            pen, notes = 1.0, []
            if top_share > .6:
                pen *= .55; notes.append(f"{top_share:.0%} of the dollars come from one account ({acct[top[0]]['name']}).")
            elif top_share > .35:
                pen *= .85; notes.append(f"{top_share:.0%} of the dollars sit with {acct[top[0]]['name']}.")
            if len(m["sources"]) == 1:
                pen *= .85; notes.append(f"Only one source ({next(iter(m['sources']))}).")
            if m["coverage"] < .5 and m["decline"] < .2:
                pen *= .85; notes.append(f"Only {m['coverage']:.0%} of complaining accounts use {m['feature']}.")
            if m["urgency"] < 2 and B < .2:
                notes.append("Many voices, low urgency and no behavioural friction.")
            sk = (skeptic or {}).get(tid)
            spen = sk["extra_penalty"] if sk else 1.0
            ev = int(round(100 * (W["q"] * Q + W["b"] * B + W["c"] * C) * pen * spen))
            if top_share > .6 and B < .3: arch = "commercial_mirage"
            elif m["decline"] >= .3 and Q < .55: arch = "silent_churn"
            elif Q >= .45 and B < .25 and C < .65: arch = "vocal_minority"
            elif ev >= 70 and min(Q, B, C) >= .45: arch = "high_signal"
            else: arch = "emerging"
            sev = clip(.5 * (m["urgency"] - 1) / 4 + .5 * B)
            cod = _cod(m, acct, sev)
            adj = cod["total"] * ev / 100
            e_w, e_conf = est.get(m["feature"], (6, "low"))
            dep = run.deps.get(tid, {})
            dur = e_w + dep.get("blocked_weeks", 0)
            cd3 = adj / dur if dur else 0
            # Urgency profile (Reinertsen): how CoD behaves over time
            if cod["total"] < 2000: prof = "intangible"
            elif arch == "silent_churn" or (B > .85 and cod["total"] > 50000): prof = "expedite"
            elif cod["dated_share"] > .35: prof = "fixed_date"
            else: prof = "standard"
            out[tid] = dict(Q=round(Q, 3), B=round(B, 3), C=round(C, 3), rule_penalty=round(pen, 3), skeptic_penalty=spen,
                            evidence=ev, archetype=arch, cod=cod, cod_adj=adj, effort=e_w, effort_conf=e_conf,
                            blocked_weeks=dep.get("blocked_weeks", 0), duration=dur, cd3=cd3, profile=prof,
                            influenced=total, top_account=acct[top[0]]["name"] if top[0] else None, top_share=round(top_share, 3),
                            icp_share=round(icp, 3), notes=" ".join(notes) or "Three pillars agree; no concentration or single-source risk found.")
        for rank, tid in enumerate(sorted(out, key=lambda t: -out[t]["cd3"]), 1):
            out[tid]["rank"] = rank
        rows = []
        for tid, o in out.items():
            m = run.metrics[tid]
            sk = (skeptic or {}).get(tid) or {}
            metrics = {k: v for k, v in m.items() if k not in ("feedback_ids",)} | {
                "cod": o["cod"], "influenced": o["influenced"], "top_account": o["top_account"], "top_share": o["top_share"],
                "icp_share": o["icp_share"], "effort_conf": o["effort_conf"], "blocked_weeks": o["blocked_weeks"], "duration": o["duration"],
                "deps": run.deps.get(tid, {})}
            rows.append((run.run_id, tid, o["Q"], o["B"], o["C"], o["rule_penalty"], o["skeptic_penalty"], o["evidence"], o["archetype"],
                         o["cod"]["total"], o["cod_adj"], o["effort"], o["cd3"], o["profile"], o["rank"], json.dumps(metrics, default=str),
                         o["notes"], json.dumps({k: sk.get(k) for k in ("verdict", "reason", "checks")}) if sk else None,
                         json.dumps(sk.get("cited_ids", [])) if sk else None))
        run.db.executemany("INSERT OR REPLACE INTO theme_scores VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        # epic value: CoD inherited through blocking links
        ev_rows = []
        theme_by_epic = {d["epic"]: t for t, d in run.deps.items() if d.get("epic")}
        succ = defaultdict(list)
        for b, ps in run.preds.items():
            for p in ps: succ[p].append(b)

        def downstream(k, acc=None):
            acc = acc if acc is not None else set()
            for n in succ[k]:
                if n not in acc: acc.add(n); downstream(n, acc)
            return acc

        for k, e in run.epics.items():
            if e["status"] == "done": continue
            own = out[theme_by_epic[k]]["cod_adj"] if k in theme_by_epic else 0
            ds = downstream(k)
            inh = sum(out[theme_by_epic[d]]["cod_adj"] for d in ds if d in theme_by_epic)
            ev_rows.append((run.run_id, k, own, inh, json.dumps(sorted(ds)), (own + inh) / max(e["weeks"], .5)))
        run.db.executemany("INSERT OR REPLACE INTO epic_value VALUES (?,?,?,?,?,?)", ev_rows)
        run.db.commit()
        run.scores = out
        top = sorted(out.items(), key=lambda kv: kv[1]["rank"])[:3]
        s.detail = {"summary": "Top by CD3: " + "; ".join(f"{t} ${o['cd3']:,.0f}/wk²" for t, o in top),
                    "params": {"weights": W, "cod": COD}}
