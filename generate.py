"""SignalCore synthetic data generator + reference scorer.

Builds signalcore.db (SQLite, schema.sql) for a fictional identity/device/AI-agent platform
("Keystone Directory") with 12 planted product themes, then runs a deterministic stand-in for the
Cluster -> Triangulation -> Skeptic agents and writes app_data.json for the UX prototype.

    python3 generate.py            # stdlib only, ~5 s
"""
import json, math, random, sqlite3, datetime as dt
from collections import defaultdict
from pathlib import Path

random.seed(42)
HERE = Path(__file__).parent
TODAY = dt.date(2026, 11, 26)
WEEKS = 26
START = TODAY - dt.timedelta(weeks=WEEKS)

# ----------------------------------------------------------------------------- reference data
MODULES = [  # id, name, lifecycle, eng_fte
    ("directory", "Directory & Lifecycle", "mature", 14),
    ("sso", "SSO & Conditional Access", "growth", 16),
    ("devices", "Device Management", "growth", 18),
    ("patch", "Patch Management", "mature", 6),
    ("password_mgr", "Password Manager", "growth", 9),
    ("remote_assist", "Remote Assist", "pilot", 11),
    ("agent_access", "AI Agent Access", "discovery", 7),
    ("access_requests", "Access Requests", "pilot", 5),
    ("console", "Admin Console", "mature", 12),
]
FEATURES = [
    ("user_lifecycle", "directory", "User lifecycle"), ("scim_sync", "directory", "SCIM sync"),
    ("bulk_import", "directory", "Bulk import"), ("saml_config", "sso", "SAML app config"),
    ("conditional_access", "sso", "Conditional access policies"), ("device_inventory", "devices", "Device inventory"),
    ("linux_enroll", "devices", "Linux enrollment"), ("device_trust", "devices", "Device trust"),
    ("patch_policies", "patch", "Patch policies"), ("browser_ext", "password_mgr", "Browser extension"),
    ("remote_session", "remote_assist", "Remote session"), ("agent_policy_editor", "agent_access", "Agent policy editor"),
    ("approval_flow", "access_requests", "Approval flow"), ("console_theme", "console", "Console appearance"),
]
FEATURE_MODULE = {f: m for f, m, _ in FEATURES}
ADOPTION = {  # P(customer uses module) by segment: SMB, MM, ENT
    "directory": (.95, .98, 1), "sso": (.6, .85, .95), "devices": (.55, .8, .9), "patch": (.35, .6, .75),
    "password_mgr": (.5, .45, .3), "remote_assist": (.15, .25, .3), "agent_access": (.03, .18, .35),
    "access_requests": (.1, .3, .45), "console": (1, 1, 1),
}

# Planted themes. n = accounts that mention it; seg = SMB/MM/ENT weights; src = source mix;
# fr = extra abandonment on the feature for mentioning accounts; decay = silent usage decay in
# renewal cohort; urg = typical urgency; opps = (count, type, lo, hi, segment) deals naming the gap.
THEMES = [
    dict(id="T01", title="AI agent permission scoping", feature="agent_policy_editor", n=34, seg=(0, 6, 4),
         src=dict(gong=5, zendesk=3, jira=2, idea_portal=2, cab=2), fr=.34, urg=4.3, wk=.55,
         opps=[(7, "new_logo", 90e3, 420e3, "MM"), (4, "expansion", 60e3, 300e3, "ENT")],
         stmt="Admins can't scope what an AI agent identity may touch, so they block agent rollouts or grant over-broad tokens.",
         says=["We can't give the copilot service account least-privilege scopes, so security won't sign off.",
               "Need per-tool permissions for AI agents, today it's all or nothing on the API token.",
               "Our CISO paused the agent pilot until we can restrict which directories the agent can read.",
               "We're creating a separate tenant just to sandbox agent identities. That's our workaround.",
               "The agent policy editor times out when we add more than a handful of resource scopes."]),
    dict(id="T02", title="Silent SCIM failures to Workday", feature="scim_sync", n=27, seg=(2, 6, 3),
         src=dict(zendesk=6, jira=3, gong=2, cab=1), fr=.26, urg=4.0, wk=.45,
         opps=[(3, "renewal", 80e3, 260e3, "MM"), (2, "expansion", 50e3, 150e3, "ENT")],
         stmt="Provisioning from Workday drops users without an error, so new hires start without access.",
         says=["Two new hires had no laptop access on day one again. SCIM said success.",
               "We export a CSV every Monday to diff Workday against the directory. Pure workaround.",
               "Provisioning errors don't surface anywhere, we only hear about it from angry managers.",
               "SCIM sync is the reason our IT lead is evaluating other vendors at renewal."]),
    dict(id="T03", title="Custom SAML attribute transforms", feature="saml_config", n=3, seg=(1, 0, 0),
         src=dict(gong=8, jira=1), fr=0, urg=4.8, wk=.1, outlier=True,
         opps=[],
         stmt="One prospect needs regex transforms on SAML assertions for a legacy mainframe portal.",
         says=["Globex will not sign unless SAML attributes can be rewritten with regex before assertion.",
               "Their architect walked through the mainframe portal again, it needs a custom transform engine.",
               "Rep says this is the only blocker on the Globex deal and wants it on the Q1 roadmap."]),
    dict(id="T04", title="Patch policies stall after OS upgrades", feature="patch_policies", n=5, seg=(0, 3, 2),
         src=dict(zendesk=1), fr=.08, urg=2.6, wk=.15, decay=.52,
         opps=[],
         stmt="After macOS and Windows feature upgrades, scheduled patch policies stop applying and admins quietly stop using them.",
         says=["Patch policy shows compliant but half the fleet is still on the old build.",
               "We moved patching back to a script after the last OS upgrade."]),
    dict(id="T05", title="Linux fleet enrollment", feature="linux_enroll", n=16, seg=(1, 5, 3),
         src=dict(gong=4, zendesk=3, idea_portal=2), fr=.2, urg=3.4, wk=.35,
         opps=[(4, "new_logo", 40e3, 180e3, "MM")],
         stmt="Ubuntu and RHEL devices need a manual agent install, which blocks engineering-heavy fleets.",
         says=["Our engineers run Ubuntu, enrollment is manual and breaks on every kernel update.",
               "We lost a bake-off because the competitor enrolls Linux with zero touch.",
               "RHEL enrollment needs three scripts and still fails behind our proxy."]),
    dict(id="T06", title="Dark mode for the admin console", feature="console_theme", n=58, seg=(8, 2, 0),
         src=dict(idea_portal=8, zendesk=1), fr=0, urg=1.4, wk=.02,
         opps=[],
         stmt="Admins want a dark theme for the admin console.",
         says=["+1 for dark mode please!", "Would love a dark theme, the console is very bright at night.",
               "Dark mode would be nice to have."]),
    dict(id="T07", title="Approve access requests in Slack", feature="approval_flow", n=22, seg=(1, 5, 3),
         src=dict(gong=3, idea_portal=3, zendesk=2, cab=1), fr=.18, urg=3.3, wk=.3,
         opps=[(3, "expansion", 30e3, 120e3, "MM")],
         stmt="Managers miss approval emails, so access requests sit for days and IT approves on their behalf.",
         says=["Approvals sit for three days because managers never open the email.",
               "IT ends up approving on behalf of managers, which defeats the audit trail.",
               "If approvals lived in Slack we'd roll Access Requests out to the whole company."]),
    dict(id="T08", title="Password manager crashes in Safari", feature="browser_ext", n=19, seg=(7, 3, 0),
         src=dict(zendesk=7, idea_portal=1), fr=.3, urg=3.1, wk=.25,
         opps=[],
         stmt="The browser extension crashes on Safari 19, so Mac users fall back to saved browser passwords.",
         says=["Extension crashes every time Safari opens a new window.", "Our Mac users went back to iCloud Keychain.",
               "Safari extension keeps logging out after the update."]),
    dict(id="T09", title="Remote Assist latency in APAC", feature="remote_session", n=8, seg=(1, 3, 1),
         src=dict(zendesk=3, gong=1), fr=.15, urg=3.0, wk=.2,
         opps=[],
         stmt="Remote sessions to Singapore and Sydney lag by seconds, so helpdesk staff switch tools.",
         says=["Sessions to our Sydney office lag two or three seconds per click.",
               "Helpdesk uses another remote tool for APAC because of latency."]),
    dict(id="T10", title="Device trust for BYOD", feature="device_trust", n=13, seg=(0, 5, 4),
         src=dict(gong=4, cab=2, zendesk=1), fr=.11, urg=3.5, wk=.2,
         opps=[(5, "new_logo", 60e3, 240e3, "ENT")],
         stmt="Security teams want posture checks on unmanaged personal devices before granting app access.",
         says=["We need posture checks for contractors on personal laptops before SSO.",
               "BYOD trust is a checkbox on every enterprise RFP we see."]),
    dict(id="T11", title="Bulk CSV import errors", feature="bulk_import", n=21, seg=(8, 2, 0),
         src=dict(zendesk=6, idea_portal=1), fr=.2, urg=2.5, wk=.4,
         opps=[],
         stmt="Bulk user imports fail on a single bad row with an unhelpful error.",
         says=["Import failed with 'invalid row' and no row number.", "We split our CSV into 20 files to find the bad line."]),
    dict(id="T12", title="Conditional access policy simulator", feature="conditional_access", n=18, seg=(0, 5, 4),
         src=dict(gong=3, cab=2, zendesk=2, jira=1), fr=.22, urg=3.7, wk=.4,
         opps=[(3, "expansion", 70e3, 260e3, "ENT")],
         stmt="Admins can't preview who a conditional access change will lock out, so they avoid tightening policies.",
         says=["We're scared to change conditional access policies because we can't see who gets locked out.",
               "Need a what-if mode before pushing a policy to 4,000 users.",
               "We tested a policy change on the CEO by accident. A simulator would have caught it."]),
]
NOISE = ["How do I reset MFA for a user?", "Invoice question for last month.", "Can you add our new domain?",
         "Login page looked weird yesterday, fine now.", "Feature request: emoji in group names.",
         "Is there an API rate limit doc?", "Training session request for new admins."]

ROADMAP = [  # what the PM org's GPL says today
    ("GPL-101", "Agent permission scopes v2", "T01", "committed", "2027-Q1", "gong,pendo,sfdc"),
    ("GPL-102", "Globex SAML transform engine", "T03", "committed", "2027-Q1", "gong"),
    ("GPL-103", "Admin console dark mode", "T06", "in_build", "2026-Q4", "idea_portal"),
    ("GPL-104", "Zero-touch Linux enrollment", "T05", "proposed", "2027-Q2", "gong,zendesk"),
    ("GPL-105", "Slack approvals for Access Requests", "T07", "proposed", "2027-Q2", "idea_portal"),
    ("GPL-106", "SCIM error surfacing + retry", "T02", "proposed", "2027-Q1", "zendesk,sfdc"),
    ("GPL-107", "BYOD posture checks", "T10", "committed", "2027-Q2", "gong,cab"),
]

# ----------------------------------------------------------------------------- helpers
A1 = "Blue Harbor Cedar Summit Iron North Bright Silver Pine Granite Atlas Lumen Copper Vantage Orbit Maple Red Delta Quartz Echo Fern Cobalt Lark Mesa Tidal Aspen Birch Falcon Juniper Onyx".split()
A2 = "Analytics Health Logistics Labs Capital Robotics Foods Media Systems Bio Freight Energy Retail Studios Networks Insurance Legal Works".split()
IND = ["SaaS", "Healthcare", "Financial services", "Manufacturing", "Education", "Retail", "Professional services"]
ICP_IND = {"SaaS", "Healthcare", "Financial services"}
SEG = ["SMB", "Mid-Market", "Enterprise"]
SEG_KEY = {"SMB": 0, "MM": 1, "ENT": 2}
PERSONA_BY_SRC = dict(gong=["economic_buyer", "security_lead", "it_admin"], zendesk=["it_admin", "end_user"],
                      jira=["it_admin"], idea_portal=["it_admin", "end_user"], cab=["security_lead", "economic_buyer"])

def rdate(a, b):
    return a + dt.timedelta(days=random.randint(0, (b - a).days))

def clip(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))

# ----------------------------------------------------------------------------- build
def build(db):
    db.executescript((HERE / "schema.sql").read_text())
    for mid, name, stage, fte in MODULES:
        db.execute("INSERT INTO modules VALUES (?,?,?,?)", (mid, name, stage, None))
        for q, f in (("2026-Q3", fte * 0.95), ("2026-Q4", fte)):
            db.execute("INSERT INTO capability_investments VALUES (?,?,?)", (mid, q, round(f, 1)))
    db.executemany("INSERT INTO features VALUES (?,?,?)", FEATURES)

    # accounts
    accts, names = [], set()
    plan = [("SMB", 220, (6e3, 38e3), (25, 250)), ("Mid-Market", 140, (40e3, 240e3), (250, 2500)),
            ("Enterprise", 40, (260e3, 1.4e6), (2500, 25000))]
    i = 0
    for seg, n, (lo, hi), (slo, shi) in plan:
        for _ in range(n):
            i += 1
            while True:
                nm = f"{random.choice(A1)} {random.choice(A2)}"
                if nm not in names: names.add(nm); break
            ind = random.choice(IND)
            arr = int(round(math.exp(random.uniform(math.log(lo), math.log(hi))), -2))
            accts.append(dict(id=f"ACC-{i:04d}", name=nm, seg=seg, ind=ind, region=random.choice(["NA", "NA", "EMEA", "APAC"]),
                              cust=1, icp=int(seg != "SMB" and ind in ICP_IND), seats=random.randint(slo, shi), arr=arr,
                              renew=rdate(TODAY + dt.timedelta(days=5), TODAY + dt.timedelta(days=365)),
                              health=random.choice(["green"] * 6 + ["yellow"] * 3 + ["red"])))
    # prospects (including the outlier)
    for j in range(30):
        i += 1
        nm = f"{random.choice(A1)} {random.choice(A2)} (prospect)"
        accts.append(dict(id=f"ACC-{i:04d}", name=nm, seg=random.choice(SEG[1:]), ind=random.choice(IND), region="NA",
                          cust=0, icp=0, seats=random.randint(300, 6000), arr=0, renew=None, health=None))
    globex = dict(id="ACC-9001", name="Globex Holdings", seg="Enterprise", ind="Manufacturing", region="NA", cust=0, icp=0,
                  seats=42000, arr=0, renew=None, health=None)
    accts.append(globex)
    for a in accts:
        a["icp"] = int(a["icp"]); a["segk"] = SEG.index(a["seg"])
        db.execute("INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (a["id"], a["name"], a["seg"], a["ind"], a["region"], a["cust"], a["icp"], a["seats"], a["arr"],
                    a["renew"].isoformat() if a["renew"] else None, a["health"]))
    customers = [a for a in accts if a["cust"]]
    prospects = [a for a in accts if not a["cust"] and a is not globex]

    # contacts
    cid = 0
    contacts = defaultdict(dict)
    for a in accts:
        for p in ["economic_buyer", "it_admin", "security_lead", "end_user"]:
            cid += 1
            contacts[a["id"]][p] = f"CON-{cid:05d}"
            db.execute("INSERT INTO contacts VALUES (?,?,?)", (f"CON-{cid:05d}", a["id"], p))

    # adoption
    uses = {}
    for a in customers:
        mods = {m for m, p in ADOPTION.items() if random.random() < p[a["segk"]]}
        uses[a["id"]] = {f for f, m, _ in FEATURES if m in mods}

    # theme membership
    members = {}
    for t in THEMES:
        feat, w = t["feature"], t["seg"]
        if t.get("outlier"):
            pool = [a for a in customers if a["seg"] == "SMB"]
            members[t["id"]] = [globex] + random.sample(pool, t["n"] - 1)
            continue
        pool = [a for a in customers if feat in uses[a["id"]] or random.random() < 0.15]
        weights = [w[a["segk"]] + 1e-9 for a in pool]
        chosen = set()
        while len(chosen) < min(t["n"], len(pool)):
            chosen.add(random.choices(range(len(pool)), weights)[0])
        members[t["id"]] = [pool[k] for k in chosen]
        for a in members[t["id"]]:
            if random.random() < 0.85: uses[a["id"]].add(feat)   # most complainers really use it

    # silent-decay cohort for T04: MM/ENT using patch policies renewing within 150 days
    decay_cohort = {a["id"] for a in customers if "patch_policies" in uses[a["id"]] and a["seg"] != "SMB"
                    and (a["renew"] - TODAY).days <= 150}

    # qualitative feedback
    fid = 0
    def add_fb(a, src, theme, body, when):
        nonlocal fid
        fid += 1
        persona = random.choice(PERSONA_BY_SRC[src])
        ref = {"gong": f"GONG-{random.randint(10000, 99999)}@{random.randint(1, 48):02d}:{random.randint(0, 59):02d}",
               "zendesk": f"ZD-{random.randint(30000, 59999)}", "jira": f"SUP-{random.randint(1000, 9999)}",
               "idea_portal": f"IDEA-{random.randint(100, 999)}", "cab": f"CAB-2026-{random.randint(1, 4)}"}[src]
        db.execute("INSERT INTO qualitative_feedback VALUES (?,?,?,?,?,?,?,?,?)",
                   (f"FB-{fid:05d}", src, ref, a["id"], contacts[a["id"]][persona], persona,
                    when.isoformat(timespec="minutes"), body, theme))
        return f"FB-{fid:05d}"

    fb_meta = {}
    for t in THEMES:
        srcs, sw = list(t["src"]), list(t["src"].values())
        for a in members[t["id"]]:
            k = 9 if a is globex else max(1, int(random.expovariate(1 / (2.6 if a["segk"] else 1.6))))
            for _ in range(min(k, 9)):
                src = "gong" if a is globex else random.choices(srcs, sw)[0]
                when = dt.datetime.combine(rdate(TODAY - dt.timedelta(days=175), TODAY - dt.timedelta(days=1)),
                                           dt.time(random.randint(8, 18), random.randint(0, 59)))
                fb = add_fb(a, src, t["id"], random.choice(t["says"]), when)
                fb_meta[fb] = (t, src)
    for _ in range(900):  # unclustered noise
        a = random.choice(customers)
        src = random.choice(["zendesk", "zendesk", "idea_portal", "gong"])
        when = dt.datetime.combine(rdate(TODAY - dt.timedelta(days=175), TODAY), dt.time(random.randint(8, 18), 0))
        fb = add_fb(a, src, None, random.choice(NOISE), when)
        fb_meta[fb] = (None, src)

    # opportunities
    oid = 0
    def add_opp(a, typ, status, amt, theme, notes, loss=None):
        nonlocal oid
        oid += 1
        close = rdate(TODAY - dt.timedelta(days=150), TODAY + dt.timedelta(days=120))
        stage = "closed" if status != "open" else random.choice(["discovery", "eval", "negotiation"])
        db.execute("INSERT INTO crm_opportunities VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (f"OPP-{oid:05d}", a["id"], typ, stage, status, int(round(amt, -3)), close.isoformat(), loss, notes, theme))
    for a in customers:  # renewals + background expansion
        add_opp(a, "renewal", "open", a["arr"], None, "Standard renewal")
        if random.random() < .25:
            add_opp(a, "expansion", random.choice(["open", "won", "lost"]), a["arr"] * random.uniform(.1, .5), None, "Seat expansion")
    for p in prospects:
        add_opp(p, "new_logo", random.choice(["open", "won", "lost"]), random.uniform(30e3, 300e3), None, "Inbound evaluation")
    add_opp(globex, "new_logo", "open", 1_240_000, "T03", "Only blocker per AE: custom SAML regex transforms for mainframe portal")
    for t in THEMES:
        for n, typ, lo, hi, seg in t["opps"]:
            for _ in range(n):
                status = random.choice(["open", "open", "lost"])
                if typ == "new_logo":
                    a = random.choice([p for p in prospects]);
                else:
                    a = random.choice(members[t["id"]])
                add_opp(a, typ, status, random.uniform(lo, hi), t["id"], f"Gap: {t['title'].lower()}",
                        f"Missing capability: {t['title'].lower()}" if status == "lost" else None)

    # telemetry
    eid = 0
    member_feat = {(a["id"], t["feature"]): t for t in THEMES for a in members[t["id"]]}
    rows = []
    for a in customers:
        lam_base = 0.8 + min(3.0, a["seats"] / 900)
        for f in sorted(uses[a["id"]]):
            t = member_feat.get((a["id"], f))
            p_ab = 0.11 + (t["fr"] if t else 0)
            for w in range(WEEKS):
                lam = lam_base
                if f == "patch_policies" and a["id"] in decay_cohort and w >= WEEKS - 12:
                    lam *= 1 - 0.52 * (w - (WEEKS - 12) + 1) / 12
                if f == "agent_policy_editor":
                    lam *= 0.5 + w / WEEKS          # young module, growing
                n = sum(1 for _ in range(6) if random.random() < lam / 6)
                for _ in range(n):
                    ts = dt.datetime.combine(START + dt.timedelta(weeks=w, days=random.randint(0, 4)), dt.time(random.randint(7, 19), random.randint(0, 59)))
                    u = f"{a['id']}-u{random.randint(1, 30):02d}"
                    eid += 1; rows.append((f"EV-{eid:07d}", ts.isoformat(timespec="minutes"), a["id"], u, f, "task_started", None))
                    ab = random.random() < p_ab
                    eid += 1; rows.append((f"EV-{eid:07d}", ts.isoformat(timespec="minutes"), a["id"], u, f,
                                           "task_abandoned" if ab else "task_completed", int(random.gauss(95e3 if ab else 60e3, 2e4))))
    db.executemany("INSERT INTO telemetry_events VALUES (?,?,?,?,?,?,?)", rows)

    # simulated Cluster Agent output (92% label accuracy, as a real clusterer would be imperfect)
    themes_by_id = {t["id"]: t for t in THEMES}
    for fb, (t, src) in fb_meta.items():
        label = t["id"] if t else None
        if t and random.random() < .08: label = None
        if not t and random.random() < .02: label = random.choice(THEMES)["id"]
        tt = themes_by_id.get(label)
        urg = int(clip(round(random.gauss(tt["urg"], .7)), 1, 5)) if tt else random.randint(1, 3)
        wk = int(random.random() < (tt["wk"] if tt else .02))
        sent = round(clip(random.gauss(-0.15 * urg, .2), -1, 1), 2)
        db.execute("INSERT INTO feedback_enrichment VALUES (?,?,?,?,?,?)", (fb, label, sent, urg, wk, None))
    for t in THEMES:
        db.execute("INSERT INTO themes VALUES (?,?,?,?,?)", (t["id"], t["title"], t["stmt"], FEATURE_MODULE[t["feature"]], t["feature"]))
    db.executemany("INSERT INTO roadmap_items VALUES (?,?,?,?,?,?)", ROADMAP)
    db.commit()

# ----------------------------------------------------------------------------- reference scorer
def score(db):
    q = lambda sql, *a: db.execute(sql, a).fetchall()
    acct = {r[0]: dict(id=r[0], name=r[1], seg=r[2], icp=r[3], arr=r[4], renew=r[5], cust=r[6])
            for r in q("SELECT account_id,name,segment,is_icp,arr_usd,renewal_date,is_customer FROM accounts")}
    # abandonment per account/feature and weekly usage
    ab = defaultdict(lambda: [0, 0])
    weekly = defaultdict(lambda: [0] * WEEKS)
    for a, f, ev, ts in q("SELECT account_id,feature_key,event_name,ts FROM telemetry_events WHERE event_name!='task_started'"):
        ab[(a, f)][0] += ev == "task_abandoned"; ab[(a, f)][1] += 1
        w = (dt.date.fromisoformat(ts[:10]) - START).days // 7
        if 0 <= w < WEEKS: weekly[(a, f)][w] += 1
    feat_users = defaultdict(set)
    for (a, f) in ab: feat_users[f].add(a)
    base_ab = {f: sum(ab[(a, f)][0] for a in us) / max(1, sum(ab[(a, f)][1] for a in us)) for f, us in feat_users.items()}

    out, run = [], "run-2026-11-26"
    for tid, title, stmt, mod, feat in q("SELECT * FROM themes ORDER BY theme_id"):
        fb = q("""SELECT f.feedback_id,f.source,f.account_id,f.persona,f.created_at,f.body,f.source_ref,e.urgency,e.mentions_workaround
                  FROM qualitative_feedback f JOIN feedback_enrichment e USING(feedback_id) WHERE e.theme_id=?""", tid)
        accts = sorted({r[2] for r in fb})
        sources = sorted({r[1] for r in fb})
        urg = sum(r[7] for r in fb) / len(fb); wkr = sum(r[8] for r in fb) / len(fb)
        Q = clip(0.45 * clip(math.log1p(len(accts)) / math.log1p(50)) + 0.2 * len(sources) / 5 + 0.25 * (urg - 1) / 4 + 0.1 * clip(wkr / .5))
        # behavioral: friction among complainers who use the feature, and cohort decay on the feature
        users = [a for a in accts if (a, feat) in ab]
        coverage = len(users) / len(accts)
        if users:
            m_ab = sum(ab[(a, feat)][0] for a in users) / max(1, sum(ab[(a, feat)][1] for a in users))
        else:
            m_ab = base_ab.get(feat, .11)
        others = [a for a in feat_users[feat] if a not in set(accts)]
        base = sum(ab[(a, feat)][0] for a in others) / max(1, sum(ab[(a, feat)][1] for a in others))
        delta = m_ab - base
        fric = clip(delta / 0.3) * (0.4 + 0.6 * coverage)
        # cohort decay: MM/ENT customers renewing in 150d, last 6 weeks vs weeks 6-12
        cohort = [a for a in feat_users[feat] if acct[a]["seg"] != "SMB" and acct[a]["renew"]
                  and (dt.date.fromisoformat(acct[a]["renew"]) - TODAY).days <= 150]
        early = sum(sum(weekly[(a, feat)][6:12]) for a in cohort); late = sum(sum(weekly[(a, feat)][-6:]) for a in cohort)
        decline = clip(1 - late / early) if early > 20 else 0
        declining = [a for a in cohort if sum(weekly[(a, feat)][-6:]) < 0.7 * max(1, sum(weekly[(a, feat)][6:12]))] if decline > .2 else []
        B = clip(max(fric, decline / 0.45))
        # commercial
        urg_w = clip((urg - 1) / 3)
        dollars = defaultdict(float)
        for a in accts:
            if acct[a]["cust"]: dollars[a] += acct[a]["arr"] * urg_w
        for a in declining: dollars[a] = max(dollars[a], acct[a]["arr"])
        opps = q("SELECT opp_id,account_id,opp_type,status,amount_usd FROM crm_opportunities WHERE gt_theme_id=? AND status IN ('open','lost')", tid)
        # (gt_theme_id stands in for the Triangulation Agent's notes->theme match on crm_opportunities.notes)
        for o in opps: dollars[o[1]] += o[4]
        total = sum(dollars.values())
        top = max(dollars.items(), key=lambda kv: kv[1]) if dollars else (None, 0)
        top_share = top[1] / total if total else 0
        icp_share = sum(v for k, v in dollars.items() if acct[k]["icp"]) / total if total else 0
        C = clip((math.log10(max(total, 1)) - 4.6) / 2.1) * (0.75 + 0.25 * icp_share)
        arr_at_risk = sum(acct[a]["arr"] for a in set(accts) | set(declining)
                          if acct[a]["cust"] and acct[a]["renew"] and (dt.date.fromisoformat(acct[a]["renew"]) - TODAY).days <= 180)
        pipeline = sum(o[4] for o in opps)
        # skeptic
        pen, notes = 1.0, []
        if top_share > .6:
            pen *= .55; notes.append(f"{top_share:.0%} of the dollars come from one account ({acct[top[0]]['name']}).")
        elif top_share > .35:
            pen *= .85; notes.append(f"{top_share:.0%} of the dollars sit with {acct[top[0]]['name']}.")
        if len(sources) == 1:
            pen *= .85; notes.append(f"Only one source ({sources[0]}).")
        if coverage < .5 and decline < .2:
            pen *= .85; notes.append(f"Only {coverage:.0%} of complaining accounts use {feat}.")
        if urg < 2 and B < .2:
            notes.append("Many voices, low urgency and no behavioural friction.")
        raw = 0.3 * Q + 0.35 * B + 0.35 * C
        ev = int(round(100 * raw * pen))
        if top_share > .6 and B < .3: arche = "commercial_mirage"
        elif decline >= .3 and Q < .5: arche = "silent_churn"
        elif Q >= .45 and B < .25 and C < .65: arche = "vocal_minority"
        elif ev >= 70 and min(Q, B, C) >= .45: arche = "high_signal"
        else: arche = "emerging"
        if not notes: notes.append("Three pillars agree; no concentration or single-source risk found.")
        db.execute("INSERT INTO theme_scores VALUES (?,?,?,?,?,?,?,?,?)", (run, tid, Q, B, C, pen, ev, arche, " ".join(notes)))

        quotes = sorted(fb, key=lambda r: -r[7])
        seen, qsel = set(), []
        for r in quotes:
            if r[5] in seen: continue
            seen.add(r[5]); qsel.append(dict(id=r[0], src=r[1], ref=r[6], acct=acct[r[2]]["name"], seg=acct[r[2]]["seg"], persona=r[3], at=r[4][:10], body=r[5]))
            if len(qsel) == 4: break
        out.append(dict(id=tid, title=title, stmt=stmt, module=mod, feature=feat, mentions=len(fb), accounts=len(accts),
                        sources={s: sum(1 for r in fb if r[1] == s) for s in sources}, urgency=round(urg, 1), workaround=round(wkr, 2),
                        abandon=round(m_ab, 3), abandon_base=round(base, 3), coverage=round(coverage, 2),
                        decline=round(decline, 2), declining_accounts=len(declining), cohort=len(cohort),
                        influenced=int(total), arr_at_risk=int(arr_at_risk), pipeline=int(pipeline), opps=len(opps),
                        top_account=acct[top[0]]["name"] if top[0] else None, top_share=round(top_share, 2), icp_share=round(icp_share, 2),
                        Q=round(Q, 2), B=round(B, 2), C=round(C, 2), penalty=round(pen, 2), score=ev, archetype=arche,
                        skeptic=" ".join(notes), quotes=qsel,
                        segments={s: sum(1 for a in accts if acct[a]["seg"] == s) for s in SEG}))
    db.commit()
    return out, acct, weekly, feat_users

def portfolio(db, themes, acct, weekly, feat_users):
    q = lambda sql, *a: db.execute(sql, a).fetchall()
    mods = []
    tot_fte = sum(r[0] for r in q("SELECT eng_fte FROM capability_investments WHERE quarter='2026-Q4'"))
    demand = defaultdict(float)
    for t in themes: demand[t["module"]] += t["score"] * t["C"]
    tot_dem = sum(demand.values())
    for mid, name, stage, _ in q("SELECT * FROM modules"):
        fte = q("SELECT eng_fte FROM capability_investments WHERE module_id=? AND quarter='2026-Q4'", mid)[0][0]
        feats = [r[0] for r in q("SELECT feature_key FROM features WHERE module_id=?", mid)]
        users = set().union(*[feat_users[f] for f in feats]) if feats else set()
        arr = sum(acct[a]["arr"] for a in users)
        w_active = [sum(1 for a in users if any(weekly[(a, f)][w] for f in feats)) for w in range(WEEKS)]
        vel = (sum(w_active[-8:]) / 8) / max(1, sum(w_active[:8]) / 8) - 1
        mods.append(dict(id=mid, name=name, stage=stage, fte=fte, fte_share=round(fte / tot_fte, 3),
                         demand_share=round(demand[mid] / tot_dem, 3), arr=int(arr), accounts=len(users),
                         velocity=round(vel, 3), wau=w_active))
    return mods

def extras(db, themes, acct, weekly):
    q = lambda sql, *a: db.execute(sql, a).fetchall()
    cutoff = (TODAY - dt.timedelta(days=60)).isoformat()
    rows = q("""SELECT f.account_id, COUNT(*), MAX(f.created_at), MIN(f.source_ref) FROM qualitative_feedback f
                JOIN feedback_enrichment e USING(feedback_id) JOIN accounts a USING(account_id)
                WHERE e.theme_id='T01' AND f.source='gong' AND a.segment='Mid-Market' AND f.created_at>=?
                GROUP BY f.account_id""", cutoff)
    qa = []
    for a, n, last, ref in rows:
        wk = weekly[(a, "agent_policy_editor")]
        sticky = sum(1 for x in wk[-8:] if x) / 8
        qa.append(dict(account=acct[a]["name"], id=a, calls=n, last=last[:10], ref=ref, stickiness=round(sticky, 2),
                       arr=acct[a]["arr"], renewal=acct[a]["renew"]))
    qa.sort(key=lambda r: -r["arr"])
    pim = []
    for r in q("""SELECT f.feedback_id,f.source_ref,f.account_id,f.created_at,f.body,e.theme_id FROM qualitative_feedback f
                  JOIN feedback_enrichment e USING(feedback_id) WHERE f.source='idea_portal' AND e.theme_id IS NOT NULL
                  AND f.feedback_id IN (SELECT MAX(feedback_id) FROM qualitative_feedback JOIN feedback_enrichment USING(feedback_id)
                  WHERE source='idea_portal' AND theme_id = gt_theme_id GROUP BY theme_id) ORDER BY f.created_at DESC LIMIT 5""") + q("""SELECT f.feedback_id,f.source_ref,f.account_id,f.created_at,f.body,e.theme_id
                  FROM qualitative_feedback f JOIN feedback_enrichment e USING(feedback_id) WHERE f.source='idea_portal'
                  AND e.theme_id IS NULL ORDER BY f.created_at DESC LIMIT 2"""):
        pim.append(dict(id=r[0], ref=r[1], account=acct[r[2]]["name"], seg=acct[r[2]]["seg"], arr=acct[r[2]]["arr"], at=r[3][:10], body=r[4], theme=r[5]))
    gpl = [dict(id=r[0], title=r[1], theme=r[2], status=r[3], quarter=r[4], cited=r[5].split(",")) for r in q("SELECT * FROM roadmap_items")]
    counts = dict(feedback=q("SELECT COUNT(*) FROM qualitative_feedback")[0][0], events=q("SELECT COUNT(*) FROM telemetry_events")[0][0],
                  opps=q("SELECT COUNT(*) FROM crm_opportunities")[0][0], accounts=q("SELECT COUNT(*) FROM accounts WHERE is_customer=1")[0][0],
                  arr=q("SELECT SUM(arr_usd) FROM accounts")[0][0],
                  clustered=q("SELECT COUNT(*) FROM feedback_enrichment WHERE theme_id IS NOT NULL")[0][0],
                  cluster_precision=round(q("""SELECT AVG(CASE WHEN e.theme_id = f.gt_theme_id THEN 1.0 ELSE 0 END) FROM feedback_enrichment e
                                                JOIN qualitative_feedback f USING(feedback_id) WHERE e.theme_id IS NOT NULL""")[0][0], 3),
                  cluster_recall=round(q("""SELECT AVG(CASE WHEN e.theme_id = f.gt_theme_id THEN 1.0 ELSE 0 END) FROM feedback_enrichment e
                                             JOIN qualitative_feedback f USING(feedback_id) WHERE f.gt_theme_id IS NOT NULL""")[0][0], 3))
    return qa, pim, gpl, counts

if __name__ == "__main__":
    dbp = HERE / "signalcore.db"
    dbp.unlink(missing_ok=True)
    db = sqlite3.connect(dbp)
    build(db)
    themes, acct, weekly, fu = score(db)
    mods = portfolio(db, themes, acct, weekly, fu)
    qa, pim, gpl, counts = extras(db, themes, acct, weekly)
    data = dict(generated=TODAY.isoformat(), counts=counts, themes=themes, modules=mods, qa=qa, pim=pim, gpl=gpl)
    (HERE / "app_data.json").write_text(json.dumps(data, separators=(",", ":")))
    for t in sorted(themes, key=lambda t: -t["score"]):
        print(f"{t['id']} {t['score']:>3} {t['archetype']:<18} Q{t['Q']:.2f} B{t['B']:.2f} C{t['C']:.2f} pen{t['penalty']:.2f} "
              f"acc{t['accounts']:>3} infl${t['influenced']/1e6:.2f}M top{t['top_share']:.0%} dec{t['decline']:.2f} ab{t['abandon']:.2f}  {t['title']}")
    print(counts)
    for m in mods: print(m["id"], m["fte_share"], m["demand_share"], m["velocity"], m["arr"])
    print(len(qa), qa[:3])
