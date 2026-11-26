"""SignalCore v2 synthetic data generator (deterministic, stdlib only).

    python -m signalcore.data.generate [--db path]

Builds the raw tenant: accounts, contacts, deals, product telemetry and messy feedback text with
planted themes and hidden ground truth (gt_* columns). Nothing derived is written here: themes,
scores, Cost of Delay and briefs are produced by the pipeline.
"""
import argparse, datetime as dt, math, random, re, sqlite3
from collections import defaultdict
from pathlib import Path

from .text import render, FIRST

ROOT = Path(__file__).resolve().parents[2]
TODAY = dt.date(2026, 11, 26)
WEEKS = 26
START = TODAY - dt.timedelta(weeks=WEEKS)

MODULES = [("directory", "Directory & Lifecycle", "mature", 14), ("sso", "SSO & Conditional Access", "growth", 16),
           ("devices", "Device Management", "growth", 18), ("patch", "Patch Management", "mature", 6),
           ("password_mgr", "Password Manager", "growth", 9), ("remote_assist", "Remote Assist", "pilot", 11),
           ("agent_access", "AI Agent Access", "discovery", 7), ("access_requests", "Access Requests", "pilot", 5),
           ("console", "Admin Console", "mature", 12)]
FEATURES = [("user_lifecycle", "directory", "User lifecycle"), ("scim_sync", "directory", "SCIM sync"),
            ("bulk_import", "directory", "Bulk import"), ("saml_config", "sso", "SAML app config"),
            ("conditional_access", "sso", "Conditional access policies"), ("device_inventory", "devices", "Device inventory"),
            ("linux_enroll", "devices", "Linux enrollment"), ("device_trust", "devices", "Device trust"),
            ("patch_policies", "patch", "Patch policies"), ("browser_ext", "password_mgr", "Browser extension"),
            ("remote_session", "remote_assist", "Remote session"), ("agent_policy_editor", "agent_access", "Agent policy editor"),
            ("approval_flow", "access_requests", "Approval flow"), ("console_theme", "console", "Console appearance")]
ESTIMATES = {  # team-weeks, confidence  (engineering's rough sizing)
    "agent_policy_editor": (10, "medium"), "scim_sync": (5, "high"), "saml_config": (14, "low"), "patch_policies": (4, "medium"),
    "linux_enroll": (9, "medium"), "console_theme": (6, "high"), "approval_flow": (5, "medium"), "browser_ext": (2, "high"),
    "remote_session": (12, "low"), "device_trust": (11, "low"), "bulk_import": (2, "high"), "conditional_access": (7, "medium"),
    "user_lifecycle": (6, "medium"), "device_inventory": (6, "medium")}
ADOPTION = {"directory": (.95, .98, 1), "sso": (.6, .85, .95), "devices": (.55, .8, .9), "patch": (.35, .6, .75),
            "password_mgr": (.5, .45, .3), "remote_assist": (.15, .25, .3), "agent_access": (.03, .18, .35),
            "access_requests": (.1, .3, .45), "console": (1, 1, 1)}

# Planted themes: n accounts, segment weights (SMB, MM, ENT), source mix, extra abandonment, decay, deals.
THEMES = [
    dict(id="T01", feature="agent_policy_editor", n=34, seg=(0, 6, 4), src=dict(gong=5, zendesk=3, jira=2, idea_portal=2, cab=2), fr=.34,
         opps=[(7, "new_logo", 90e3, 420e3), (4, "expansion", 60e3, 300e3)]),
    dict(id="T02", feature="scim_sync", n=27, seg=(2, 6, 3), src=dict(zendesk=6, jira=3, gong=2, cab=1), fr=.26,
         opps=[(3, "renewal_risk", 80e3, 260e3), (2, "expansion", 50e3, 150e3)]),
    dict(id="T03", feature="saml_config", n=3, seg=(1, 0, 0), src=dict(gong=8, jira=1), fr=0, outlier=True, opps=[]),
    dict(id="T04", feature="patch_policies", n=5, seg=(0, 3, 2), src=dict(zendesk=1), fr=.08, decay=.52, opps=[]),
    dict(id="T05", feature="linux_enroll", n=16, seg=(1, 5, 3), src=dict(gong=4, zendesk=3, idea_portal=2), fr=.2,
         opps=[(4, "new_logo", 40e3, 180e3)]),
    dict(id="T06", feature="console_theme", n=58, seg=(8, 2, 0), src=dict(idea_portal=8, zendesk=1), fr=0, opps=[]),
    dict(id="T07", feature="approval_flow", n=22, seg=(1, 5, 3), src=dict(gong=3, idea_portal=3, zendesk=2, cab=1), fr=.18,
         opps=[(3, "expansion", 30e3, 120e3)]),
    dict(id="T08", feature="browser_ext", n=19, seg=(7, 3, 0), src=dict(zendesk=7, idea_portal=1), fr=.3, opps=[]),
    dict(id="T09", feature="remote_session", n=8, seg=(1, 3, 1), src=dict(zendesk=3, gong=1), fr=.15, opps=[]),
    dict(id="T10", feature="device_trust", n=13, seg=(0, 5, 4), src=dict(gong=4, cab=2, zendesk=1), fr=.11,
         opps=[(5, "new_logo", 60e3, 240e3)]),
    dict(id="T11", feature="bulk_import", n=21, seg=(8, 2, 0), src=dict(zendesk=6, idea_portal=1), fr=.2, opps=[]),
    dict(id="T12", feature="conditional_access", n=18, seg=(0, 5, 4), src=dict(gong=3, cab=2, zendesk=2, jira=1), fr=.22,
         opps=[(3, "expansion", 70e3, 260e3)]),
]
ROADMAP = [
    ("GPL-101", "Agent permission scopes v2", "Fine-grained, least-privilege scopes for AI agent identities in the agent policy editor.", "committed", "2027-Q1", "gong,pendo,sfdc", "T01"),
    ("GPL-102", "Globex SAML transform engine", "Regex-based rewriting of SAML assertion attributes for Globex's mainframe portal.", "committed", "2027-Q1", "gong", "T03"),
    ("GPL-103", "Admin console dark mode", "A dark theme for the admin console.", "in_build", "2026-Q4", "idea_portal", "T06"),
    ("GPL-104", "Zero-touch Linux enrollment", "Automated agent install and enrollment for Ubuntu and RHEL devices.", "proposed", "2027-Q2", "gong,zendesk", "T05"),
    ("GPL-105", "Slack approvals for Access Requests", "Let managers approve access requests in Slack or Teams.", "proposed", "2027-Q2", "idea_portal", "T07"),
    ("GPL-106", "SCIM error surfacing + retry", "Show failed Workday provisioning users and retry them automatically.", "proposed", "2027-Q1", "zendesk,sfdc", "T02"),
    ("GPL-107", "BYOD posture checks", "Device trust and posture checks for unmanaged personal devices before SSO.", "committed", "2027-Q2", "gong,cab", "T10"),
]

A1 = "Blue Harbor Cedar Summit Iron North Bright Silver Pine Granite Atlas Lumen Copper Vantage Orbit Maple Red Delta Quartz Echo Fern Cobalt Lark Mesa Tidal Aspen Birch Falcon Juniper Onyx".split()
A2 = "Analytics Health Logistics Labs Capital Robotics Foods Media Systems Bio Freight Energy Retail Studios Networks Insurance Legal Works".split()
IND = ["SaaS", "Healthcare", "Financial services", "Manufacturing", "Education", "Retail", "Professional services"]
ICP_IND = {"SaaS", "Healthcare", "Financial services"}
SEG = ["SMB", "Mid-Market", "Enterprise"]
LAST = "Shah Okafor Nguyen Garcia Kim Patel Rossi Novak Silva Haddad Tanaka Brown Mensah Larsen Costa".split()
PERSONAS = ["economic_buyer", "it_admin", "security_lead", "end_user"]
PERSONAL = ["gmail.com", "outlook.com", "yahoo.com", "proton.me"]


def slug(s):
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def mangle_company(name, rng):
    r = rng.random()
    if r < .25: return name.lower()
    if r < .45: return name + rng.choice([" Inc", " Inc.", " LLC", " Ltd", " Group", " (EMEA)"])
    if r < .6:
        w = name.split()
        return w[0] + " " + w[1][:-1] if len(w[1]) > 4 else name.upper()
    if r < .7: return name.split()[0]
    return name


def rdate(rng, a, b):
    return a + dt.timedelta(days=rng.randint(0, (b - a).days))


def build(db_path):
    rng = random.Random(42)
    db_path = Path(db_path)
    db_path.unlink(missing_ok=True)
    db = sqlite3.connect(db_path)
    db.executescript((ROOT / "schema.sql").read_text())
    for mid, name, stage, fte in MODULES:
        db.execute("INSERT INTO modules VALUES (?,?,?)", (mid, name, stage))
        for q, f in (("2026-Q3", fte * .95), ("2026-Q4", fte)):
            db.execute("INSERT INTO capability_investments VALUES (?,?,?)", (mid, q, round(f, 1)))
    db.executemany("INSERT INTO features VALUES (?,?,?)", FEATURES)
    db.executemany("INSERT INTO feature_estimates VALUES (?,?,?)", [(k, v[0], v[1]) for k, v in ESTIMATES.items()])
    db.executemany("INSERT INTO roadmap_items VALUES (?,?,?,?,?,?,?)", ROADMAP)

    # accounts ------------------------------------------------------------------------
    accts, names = [], set()
    plan = [("SMB", 220, (6e3, 38e3), (25, 250)), ("Mid-Market", 140, (40e3, 240e3), (250, 2500)),
            ("Enterprise", 40, (260e3, 1.4e6), (2500, 25000))]
    i = 0
    for seg, n, (lo, hi), (slo, shi) in plan:
        for _ in range(n):
            i += 1
            while True:
                nm = f"{rng.choice(A1)} {rng.choice(A2)}"
                if nm not in names: names.add(nm); break
            ind = rng.choice(IND)
            accts.append(dict(id=f"ACC-{i:04d}", name=nm, seg=seg, ind=ind, region=rng.choice(["NA", "NA", "EMEA", "APAC"]), cust=1,
                              icp=int(seg != "SMB" and ind in ICP_IND), seats=rng.randint(slo, shi),
                              arr=int(round(math.exp(rng.uniform(math.log(lo), math.log(hi))), -2)),
                              renew=rdate(rng, TODAY + dt.timedelta(days=5), TODAY + dt.timedelta(days=365)),
                              health=rng.choice(["green"] * 6 + ["yellow"] * 3 + ["red"])))
    for _ in range(30):
        i += 1
        while True:
            nm = f"{rng.choice(A1)} {rng.choice(A2)}"
            if nm not in names: names.add(nm); break
        accts.append(dict(id=f"ACC-{i:04d}", name=nm, seg=rng.choice(SEG[1:]), ind=rng.choice(IND), region="NA", cust=0, icp=0,
                          seats=rng.randint(300, 6000), arr=0, renew=None, health=None))
    globex = dict(id="ACC-9001", name="Globex Holdings", seg="Enterprise", ind="Manufacturing", region="NA", cust=0, icp=0,
                  seats=42000, arr=0, renew=None, health=None)
    accts.append(globex)
    for a in accts:
        a["segk"] = SEG.index(a["seg"])
        a["domain"] = slug(a["name"]) + rng.choice([".com", ".io", ".co"])
        db.execute("INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (a["id"], a["name"], a["domain"], a["seg"], a["ind"], a["region"], a["cust"], a["icp"], a["seats"], a["arr"],
                    a["renew"].isoformat() if a["renew"] else None, a["health"]))
    customers = [a for a in accts if a["cust"]]
    prospects = [a for a in accts if not a["cust"] and a is not globex]

    contacts = defaultdict(list)
    cid = 0
    for a in accts:
        for p in PERSONAS:
            cid += 1
            fn, ln = rng.choice(FIRST), rng.choice(LAST)
            c = dict(id=f"CON-{cid:05d}", name=f"{fn} {ln}", email=f"{fn.lower()}.{ln.lower()}@{a['domain']}".replace("á", "a"), persona=p)
            contacts[a["id"]].append(c)
            db.execute("INSERT INTO contacts VALUES (?,?,?,?,?)", (c["id"], a["id"], c["name"], c["email"], p))

    uses = {}
    for a in customers:
        mods = [m for m, p in ADOPTION.items() if rng.random() < p[a["segk"]]]
        uses[a["id"]] = {f for f, m, _ in FEATURES if m in mods}

    members = {}
    for t in THEMES:
        feat, w = t["feature"], t["seg"]
        if t.get("outlier"):
            members[t["id"]] = [globex] + rng.sample([a for a in customers if a["seg"] == "SMB"], t["n"] - 1)
            continue
        pool = [a for a in customers if feat in uses[a["id"]] or rng.random() < .15]
        wts = [w[a["segk"]] + 1e-9 for a in pool]
        chosen = []
        while len(chosen) < min(t["n"], len(pool)):
            k = rng.choices(range(len(pool)), wts)[0]
            if k not in chosen: chosen.append(k)
        members[t["id"]] = [pool[k] for k in chosen]
        for a in members[t["id"]]:
            if rng.random() < .85: uses[a["id"]].add(feat)
    decay_cohort = {a["id"] for a in customers if "patch_policies" in uses[a["id"]] and a["seg"] != "SMB" and (a["renew"] - TODAY).days <= 150}

    # feedback --------------------------------------------------------------------------
    fid = 0
    def reporter(a):
        r = rng.random()
        c = rng.choice(contacts[a["id"]])
        if r < .62: return c["email"], rng.choice([a["name"], None, None])
        if r < .74: return f"{rng.choice(FIRST).lower()}{rng.randint(1, 99)}@{a['domain']}", None            # unknown person, right domain
        if r < .9: return f"{c['name'].split()[0].lower()}.{rng.randint(10, 99)}@{rng.choice(PERSONAL)}", mangle_company(a["name"], rng)
        if r < .96: return f"{c['name'].split()[0].lower()}@{rng.choice(PERSONAL)}", None                    # unresolvable
        return c["email"].replace(a["domain"], slug(a["name"])[:-2] + "-corp.com"), mangle_company(a["name"], rng)  # alias domain

    def add_fb(a, src, tid, second=None):
        nonlocal fid
        fid += 1
        when = dt.datetime.combine(rdate(rng, TODAY - dt.timedelta(days=175), TODAY - dt.timedelta(days=1)), dt.time(rng.randint(7, 19), rng.randint(0, 59)))
        ref = {"gong": f"GONG-{rng.randint(10000, 99999)}", "zendesk": f"ZD-{rng.randint(30000, 59999)}", "jira": f"SUP-{rng.randint(1000, 9999)}",
               "idea_portal": f"IDEA-{rng.randint(100, 999)}", "cab": f"CAB-2026-{rng.randint(1, 4)}"}[src]
        body, _ = render(src, tid, rng, a["name"], second)
        email, comp = reporter(a)
        db.execute("INSERT INTO qualitative_feedback VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (f"FB-{fid:05d}", src, ref, email, comp, when.isoformat(timespec="minutes"), body, None, None, None, a["id"], tid, second))

    ids = [t["id"] for t in THEMES]
    for t in THEMES:
        srcs, sw = list(t["src"]), list(t["src"].values())
        for a in members[t["id"]]:
            k = 9 if a is globex else max(1, int(rng.expovariate(1 / (2.6 if a["segk"] else 1.6))))
            for _ in range(min(k, 9)):
                src = "gong" if a is globex else rng.choices(srcs, sw)[0]
                second = rng.choice([x for x in ids if x not in (t["id"], "T03")]) if rng.random() < .07 and a is not globex else None
                add_fb(a, src, t["id"], second)
    for _ in range(900):
        add_fb(rng.choice(customers), rng.choice(["zendesk", "zendesk", "idea_portal", "gong", "jira"]), None)

    # deals -----------------------------------------------------------------------------
    oid = 0
    def add_opp(a, typ, status, amt, theme, notes, loss=None, close=None):
        nonlocal oid
        oid += 1
        close = close or rdate(rng, TODAY - dt.timedelta(days=150), TODAY + dt.timedelta(days=150))
        stage = "closed" if status != "open" else rng.choice(["discovery", "eval", "negotiation"])
        db.execute("INSERT INTO crm_opportunities VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (f"OPP-{oid:05d}", a["id"], typ, stage, status, int(round(amt, -3)), close.isoformat(), loss, notes, theme))
    for a in customers:
        add_opp(a, "renewal", "open", a["arr"], None, "Standard renewal", close=a["renew"])
        if rng.random() < .25:
            add_opp(a, "expansion", rng.choice(["open", "won", "lost"]), a["arr"] * rng.uniform(.1, .5), None, "Seat expansion")
    for p in prospects:
        add_opp(p, "new_logo", rng.choice(["open", "won", "lost"]), rng.uniform(30e3, 300e3), None, "Inbound evaluation")
    add_opp(globex, "new_logo", "open", 1_240_000, "T03", "AE: only blocker is custom SAML regex transforms for their mainframe portal",
            close=TODAY + dt.timedelta(days=75))
    gap_note = {"T01": "agent permissions too coarse, security blocked rollout", "T02": "Workday SCIM failures, champion frustrated",
                "T05": "no zero-touch Linux enrollment", "T07": "wants Slack approvals before company-wide rollout",
                "T10": "RFP requires BYOD posture checks", "T12": "needs policy simulator before expanding CA"}
    for t in THEMES:
        for n, typ, lo, hi in t["opps"]:
            for _ in range(n):
                status = rng.choice(["open", "open", "lost"])
                if typ == "renewal_risk":
                    a = rng.choice(members[t["id"]]); typ2 = "expansion"
                elif typ == "new_logo":
                    a = rng.choice(prospects); typ2 = typ
                else:
                    a = rng.choice(members[t["id"]]); typ2 = typ
                add_opp(a, typ2, status, rng.uniform(lo, hi), t["id"], f"Gap: {gap_note[t['id']]}",
                        f"Missing capability: {gap_note[t['id']]}" if status == "lost" else None)

    # telemetry -------------------------------------------------------------------------
    eid, rows = 0, []
    member_feat = {(a["id"], t["feature"]): t for t in THEMES for a in members[t["id"]]}
    for a in customers:
        lam_base = .8 + min(3.0, a["seats"] / 900)
        for f in sorted(uses[a["id"]]):
            t = member_feat.get((a["id"], f))
            p_ab = .11 + (t["fr"] if t else 0)
            for w in range(WEEKS):
                lam = lam_base
                if f == "patch_policies" and a["id"] in decay_cohort and w >= WEEKS - 12:
                    lam *= 1 - .52 * (w - (WEEKS - 12) + 1) / 12
                if f == "agent_policy_editor":
                    lam *= .5 + w / WEEKS
                for _ in range(sum(1 for _ in range(6) if rng.random() < lam / 6)):
                    ts = dt.datetime.combine(START + dt.timedelta(weeks=w, days=rng.randint(0, 4)), dt.time(rng.randint(7, 19), rng.randint(0, 59)))
                    u = f"{a['id']}-u{rng.randint(1, 30):02d}"
                    ab = rng.random() < p_ab
                    eid += 1; rows.append((f"EV-{eid:07d}", ts.isoformat(timespec="minutes"), a["id"], u, f, "task_started", None))
                    eid += 1; rows.append((f"EV-{eid:07d}", ts.isoformat(timespec="minutes"), a["id"], u, f,
                                           "task_abandoned" if ab else "task_completed", int(rng.gauss(95e3 if ab else 60e3, 2e4))))
    db.executemany("INSERT INTO telemetry_events VALUES (?,?,?,?,?,?,?)", rows)
    db.commit()
    db.close()
    return db_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "signalcore.db"))
    p = build(ap.parse_args().db)
    db = sqlite3.connect(p)
    for t in ["accounts", "contacts", "crm_opportunities", "qualitative_feedback", "telemetry_events"]:
        print(t, db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
