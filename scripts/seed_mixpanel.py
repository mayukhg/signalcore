"""Seed a Mixpanel project with ~60 days of simulated SignalCore usage (every event has demo=true).

    python scripts/seed_mixpanel.py --project-id 1234567 [--days 60] [--dry-run]

Uses the Mixpanel import API (https://api.mixpanel.com/import), authenticated with a project service account.
In this repo's cloud environment the service account is injected by the network proxy; elsewhere set
MIXPANEL_SA_USER and MIXPANEL_SA_SECRET. The event schema matches docs/METRICS.md and signalcore/analytics.py.
Deterministic (seed 7): rerunning sends identical events, and Mixpanel de-duplicates them by $insert_id.
"""
import argparse
import base64
import datetime as dt
import hashlib
import json
import math
import os
import random

VIEWS = {"PM": ["prioritize", "prioritize", "triangulation", "ask", "risks", "dependencies", "cab"],
         "ProductOps": ["run", "pbr", "risks", "prioritize", "cab", "triangulation", "method"],
         "Exec": ["executive", "pbr", "risks", "prioritize"],
         "EngLead": ["dependencies", "prioritize", "risks", "method"]}
ACTIVE = {"PM": .55, "ProductOps": .7, "Exec": .28, "EngLead": .32}
THEMES = [("TH-14", "silent_churn", "Validate fast", 1, 59, 197840), ("TH-04", "high_signal", "Do now", 2, 72, 58992),
          ("TH-02", "high_signal", "Do now", 3, 91, 213404), ("TH-11", "emerging", "Validate fast", 4, 49, 22333),
          ("TH-03", "emerging", "Do now", 5, 60, 54606), ("TH-08", "high_signal", "Do now", 6, 72, 75499),
          ("TH-05", "high_signal", "Do now", 7, 73, 38052), ("TH-10", "emerging", "Validate fast", 8, 50, 63426),
          ("TH-18", "commercial_mirage", "Park", 18, 8, 29135), ("TH-01", "vocal_minority", "Park", 15, 26, 7746)]
DOCS = ["portfolio", "agent_access", "patch", "directory", "sso", "devices"]


def build(days, seed=7):
    rng = random.Random(seed)
    end = dt.datetime(2026, 11, 27, 18, 0)
    start = end - dt.timedelta(days=days)
    users = ([("PM", i) for i in range(10)] + [("ProductOps", i) for i in range(5)] +
             [("Exec", i) for i in range(5)] + [("EngLead", i) for i in range(4)])
    # staged rollout: pilot team first, then wider; two users churn
    join = {}
    for k, (role, i) in enumerate(users):
        join[(role, i)] = 0 if k in (0, 1, 10, 11, 15, 20) else rng.randint(5, int(days * .7))
    churn = {users[7]: int(days * .6), users[19]: int(days * .75)}
    events = []

    def ev(name, uid, t, **p):
        p = {k: v for k, v in p.items() if v is not None}
        iid = hashlib.md5(f"{name}|{uid}|{t.isoformat()}|{json.dumps(p, sort_keys=True)}".encode()).hexdigest()
        events.append({"event": name, "properties": {"distinct_id": uid, "time": int(t.timestamp() * 1000), "$insert_id": iid,
                                                     "app_version": "2.0", "mode": "live", "demo": True, **p}})

    for d in range(days):
        day = start + dt.timedelta(days=d)
        progress = d / days                          # product matures: more trust, better quality
        weekend = day.weekday() >= 5
        # nightly pipeline run
        t = day.replace(hour=2, minute=rng.randint(0, 20))
        ok = rng.random() > .04
        ev("Pipeline Run Started", "signalcore-scheduler", t, role="system", run_id=f"run-{day:%Y%m%d}", trigger="schedule")
        fp = min(.9, .64 + .2 * progress + rng.gauss(0, .03))
        ev("Pipeline Run Completed", "signalcore-scheduler", t + dt.timedelta(seconds=rng.randint(170, 320)), role="system",
           run_id=f"run-{day:%Y%m%d}", trigger="schedule", status="done" if ok else "failed",
           duration_s=rng.randint(170, 320) if ok else rng.randint(30, 140), cost_usd=round(rng.uniform(2.4, 3.5), 3) if ok else round(rng.uniform(.2, 1.2), 3),
           themes=19 if ok else None, skeptic_weakened=rng.randint(11, 16) if ok else None,
           cod_adj_week_usd=int(rng.gauss(540000, 18000) * (1 - .08 * progress)) if ok else None,
           risks=rng.randint(12, 15) if ok else None, silent_churn_risks=1 if ok else None,
           grounded_first_pass=round(fp, 3) if ok else None, claims_dropped=max(0, int(rng.gauss(9 - 6 * progress, 1.5))) if ok else None,
           cluster_precision=round(min(.995, rng.gauss(.982, .006)), 3) if ok else None, pattern_recovery=1.0 if ok else None)
        if ok:
            committed = 4
            strong = min(committed, round(1 + 2.2 * progress + rng.random() * .4))
            ev("Roadmap Audited", "signalcore-scheduler", t + dt.timedelta(minutes=6), role="system", run_id=f"run-{day:%Y%m%d}",
               committed_items=committed, strong_evidence_items=strong, weak_bets=max(0, 2 - int(2 * progress + rng.random() * .5)),
               strong_share=round(strong / committed, 3))
        for (role, i) in users:
            if d < join[(role, i)] or ((role, i) in churn and d > churn[(role, i)]):
                continue
            p = ACTIVE[role] * (.25 if weekend else 1) * (.75 + .35 * min(1, (d - join[(role, i)]) / 21))
            if rng.random() > p:
                continue
            uid = f"demo-{role.lower()}-{i:02d}"
            t = day.replace(hour=rng.randint(8, 17), minute=rng.randint(0, 59))
            views = VIEWS[role]
            ev("App Opened", uid, t, role=role, view=views[0])
            for _ in range(rng.randint(2, 6)):
                t += dt.timedelta(seconds=rng.randint(20, 240))
                v = rng.choice(views)
                ev("View Viewed", uid, t, role=role, view=v)
                if v in ("prioritize", "triangulation", "risks") and role in ("PM", "ProductOps", "EngLead"):
                    for _ in range(rng.randint(1, 4 if role == "PM" else 2)):
                        th = rng.choices(THEMES, weights=[10, 7, 9, 3, 4, 4, 4, 3, 5, 2])[0]
                        t += dt.timedelta(seconds=rng.randint(15, 120))
                        ev("Theme Opened", uid, t, role=role, theme_id=th[0], archetype=th[1], quadrant=th[2], rank=th[3],
                           evidence_score=th[4], cod_week_usd=th[5])
                        if rng.random() < .3 + .3 * progress:
                            t += dt.timedelta(seconds=rng.randint(10, 60))
                            ev("Evidence Inspected", uid, t, role=role, kind=rng.choice(["skeptic_checks", "skeptic_checks", "linked_deals", "cited_facts"]),
                               theme_id=th[0], view=v)
                        if role == "PM" and rng.random() < .05 + .06 * progress:
                            t += dt.timedelta(seconds=rng.randint(30, 200))
                            old = rng.choice([4, 5, 6, 7, 9, 10, 11])
                            new = max(1, old + rng.choice([-4, -3, -2, 2, 3]))
                            rb = th[3]
                            ra = max(1, rb + (-rng.randint(1, 3) if new < old else rng.randint(1, 3)))
                            ev("Estimate Overridden", uid, t, role=role, theme_id=th[0], old_weeks=old, new_weeks=new, rank_before=rb, rank_after=ra)
                            ev("Decision Recorded", uid, t, role=role, kind="override", theme_id=th[0])
                if v == "ask" or (role != "Exec" and rng.random() < .1):
                    t += dt.timedelta(seconds=rng.randint(10, 90))
                    ev("Question Asked", uid, t, role=role, question_length=rng.randint(40, 160))
                    okq = rng.random() < .9 + .06 * progress
                    lat = round(max(6, rng.gauss(28 - 6 * progress, 9)), 1)
                    t += dt.timedelta(seconds=lat)
                    ev("Question Answered", uid, t, role=role, success=okq, latency_s=lat,
                       tool_calls=rng.randint(3, 9) if okq else None, cited_count=rng.randint(2, 7) if okq else None,
                       cost_usd=round(rng.uniform(.06, .3), 3), error=None if okq else rng.choice(["Timeout", "StepLimit"]))
                    if okq and rng.random() < .35:
                        ev("Evidence Inspected", uid, t + dt.timedelta(seconds=20), role=role, kind="sql", view="ask")
                if v == "pbr" and rng.random() < (.3 if role == "ProductOps" else .12):
                    t += dt.timedelta(seconds=rng.randint(30, 300))
                    doc = rng.choice(DOCS)
                    if rng.random() < .5:
                        ev("Evidence Inspected", uid, t - dt.timedelta(seconds=15), role=role, kind="cited_facts", view="pbr")
                    ev("PBR Exported", uid, t, role=role, doc=doc, format="markdown")
                    ev("Decision Recorded", uid, t, role=role, kind="pbr_export", doc=doc)
            if role == "ProductOps" and rng.random() < .15:
                t += dt.timedelta(minutes=rng.randint(1, 30))
                rid = f"run-{t:%Y%m%d-%H%M}"
                ev("Pipeline Run Started", uid, t, role=role, run_id=rid, trigger="manual")
                ev("Pipeline Run Completed", uid, t + dt.timedelta(seconds=rng.randint(180, 300)), role=role, run_id=rid, trigger="manual",
                   status="done", duration_s=rng.randint(180, 300), cost_usd=round(rng.uniform(2.4, 3.4), 3), themes=19,
                   skeptic_weakened=rng.randint(11, 16), cod_adj_week_usd=int(rng.gauss(535000, 15000)), risks=rng.randint(12, 15),
                   silent_churn_risks=1, grounded_first_pass=round(min(.9, .66 + .2 * progress + rng.gauss(0, .03)), 3),
                   claims_dropped=max(0, int(rng.gauss(8 - 5 * progress, 1.5))), cluster_precision=round(min(.995, rng.gauss(.982, .006)), 3),
                   pattern_recovery=1.0)
    return events


def send(events, project_id):
    import httpx
    user, secret = os.environ.get("MIXPANEL_SA_USER", "proxy"), os.environ.get("MIXPANEL_SA_SECRET", "injected")
    auth = "Basic " + base64.b64encode(f"{user}:{secret}".encode()).decode()   # replaced by the proxy where it injects the credential
    url = f"https://api.mixpanel.com/import?strict=1&project_id={project_id}"
    total = 0
    for i in range(0, len(events), 2000):
        batch = events[i:i + 2000]
        r = httpx.post(url, json=batch, headers={"Authorization": auth, "Content-Type": "application/json"}, timeout=60)
        if r.status_code != 200:
            raise SystemExit(f"import failed ({r.status_code}): {r.text[:500]}")
        total += r.json().get("num_records_imported", 0)
    return total


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-id", type=int)
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    evs = build(a.days)
    counts = {}
    for e in evs: counts[e["event"]] = counts.get(e["event"], 0) + 1
    print(len(evs), "events,", len({e["properties"]["distinct_id"] for e in evs}), "users")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]): print(f"  {k}: {v}")
    if not a.dry_run:
        if not a.project_id:
            raise SystemExit("--project-id is required")
        print("imported", send(evs, a.project_id))
