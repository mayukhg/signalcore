"""Jira epics with cross-module dependencies, and long-form CAB meeting notes."""
import datetime as dt
import random

from .text import THEME_TEXT, fill, cap, typo, FIRST, TITLES

# epic_key, module, title, status, feature_key, remaining_weeks, team, roadmap_item, gt_theme
EPICS = [
    ("SSO-88", "sso", "Policy engine v3 (shared authorization core)", "not_started", None, 8, "Identity Platform", None, None),
    ("DIR-41", "directory", "Fine-grained ACL API for directory objects", "not_started", "user_lifecycle", 5, "Directory", None, None),
    ("AGT-12", "agent_access", "Agent permission scopes v2", "not_started", "agent_policy_editor", 10, "Agent Access", "GPL-101", "T01"),
    ("SSO-90", "sso", "Conditional access policy simulator", "not_started", "conditional_access", 7, "Identity Platform", None, "T12"),
    ("DEV-55", "devices", "BYOD posture checks", "not_started", "device_trust", 11, "Devices", "GPL-107", "T10"),
    ("SSO-95", "sso", "Globex SAML transform engine", "in_progress", "saml_config", 14, "Identity Platform", "GPL-102", "T03"),
    ("DIR-33", "directory", "SCIM error surfacing and retry", "not_started", "scim_sync", 5, "Directory", "GPL-106", "T02"),
    ("CON-14", "console", "Notifications service v2 (Slack/Teams)", "not_started", None, 4, "Console", None, None),
    ("ACR-9", "access_requests", "Slack and Teams approvals", "not_started", "approval_flow", 5, "Access Requests", "GPL-105", "T07"),
    ("PAT-21", "patch", "Patch policy resilience across OS upgrades", "not_started", "patch_policies", 4, "Patch", None, "T04"),
    ("DEV-58", "devices", "Cross-platform agent installer rewrite", "in_progress", None, 6, "Devices", None, None),
    ("DEV-60", "devices", "Zero-touch Linux enrollment", "not_started", "linux_enroll", 9, "Devices", "GPL-104", "T05"),
    ("CON-20", "console", "Design tokens refactor and dark mode", "in_progress", "console_theme", 6, "Console", "GPL-103", "T06"),
    ("PWM-7", "password_mgr", "Safari 19 extension stability", "not_started", "browser_ext", 2, "Password Manager", None, "T08"),
    ("RA-31", "remote_assist", "APAC relay servers", "not_started", "remote_session", 12, "Remote Assist", None, "T09"),
    ("DIR-36", "directory", "Bulk import row-level errors", "not_started", "bulk_import", 2, "Directory", None, "T11"),
    ("CON-22", "console", "Audit log export v2", "in_progress", None, 3, "Console", None, None),
    ("DEV-61", "devices", "Device inventory search", "done", "device_inventory", 0, "Devices", None, None),
]
LINKS = [("SSO-88", "DIR-41"), ("DIR-41", "AGT-12"), ("SSO-88", "SSO-90"), ("SSO-88", "DEV-55"), ("SSO-88", "SSO-95"),
         ("CON-14", "ACR-9"), ("CON-14", "PAT-21"), ("DEV-58", "DEV-60"), ("DEV-58", "DEV-55")]


def build_jira(db):
    db.executemany("INSERT INTO jira_epics VALUES (?,?,?,?,?,?,?,?,?)", EPICS)
    db.executemany("INSERT INTO jira_links VALUES (?,?,'blocks')", LINKS)


CAB_THEMES = ["T01", "T02", "T12", "T10", "T04", "T07", "T05"]
PRAISE = ["the new device inventory search saved us hours", "support response times have been great this quarter",
          "SSO setup for new apps is now painless", "the audit log export is exactly what our auditors wanted"]


def build_cab(db, members, customers, contacts, today):
    rng = random.Random(7)
    ent = [a for a in customers if a["seg"] != "SMB"]
    for m in range(1, 7):
        held = today - dt.timedelta(days=175 - m * 28)
        attendees = []
        for tid in rng.sample(CAB_THEMES, 4):
            pool = [a for a in members[tid] if a["seg"] != "SMB" and a.get("cust", 1)]
            if pool: attendees.append((rng.choice(pool), tid))
        for a in rng.sample(ent, 2): attendees.append((a, None))
        lines, gt = [], []
        add = lambda text, acc=None, tid=None: (lines.append(text), gt.append((len(lines), acc, tid)) if acc else None)
        add(f"Keystone Directory · Customer Advisory Board · Session {m}")
        add(f"Date: {held.isoformat()} · Facilitator: {rng.choice(FIRST)} (Product)")
        add("")
        add("Attendees:")
        speakers = {}
        for a, _ in attendees:
            c = rng.choice([c for c in contacts[a["id"]] if c["persona"] in ("security_lead", "economic_buyer", "it_admin")])
            speakers[a["id"]] = c["name"]
            add(f"- {c['name']} ({rng.choice(TITLES)}, {a['name']})")
        add("")
        add("1. Roadmap readout")
        add("Product walked through the H1 roadmap. Questions were mostly about AI agents and policy changes.")
        add("")
        add("2. Open discussion")
        for a, tid in attendees:
            who = speakers[a["id"]].split()[0]
            if tid:
                t = THEME_TEXT[tid]
                s1 = fill(rng.choice(t["symptom"]), t["syn"], rng)
                s2 = fill(rng.choice(t["impact"]), t["syn"], rng)
                add(typo(f"- {who} ({a['name']}): {cap(s1)}. {cap(s2)}.", rng, .02), a["id"], tid)
                if rng.random() < .6:
                    add(typo(f"  {who} added: {cap(fill(rng.choice(t['ask']), t['syn'], rng))}.", rng, .02), a["id"], tid)
            else:
                add(f"- {who} ({a['name']}): {cap(rng.choice(PRAISE))}.", a["id"], None)
        add("")
        add("3. Decisions")
        add(f"- Product will share a design preview for {rng.choice(['agent permissions', 'the policy simulator', 'SCIM error handling'])} at the next session.")
        add("")
        add("4. Action items")
        for a, tid in attendees[:3]:
            add(f"- AI: Keystone to follow up with {a['name']} on {('their ' + tid + ' issue') if tid else 'a reference call'} by {(held + dt.timedelta(days=14)).isoformat()}.")
        body = "\n".join(lines)
        # strip internal theme ids from action items so agents can't read ground truth
        body = body.replace("their T", "their issue T").replace("issue T01 issue", "agent permission concern")
        import re
        body = re.sub(r"their issue T\d\d issue", "the issue they raised", body)
        db.execute("INSERT INTO cab_meetings VALUES (?,?,?,?)", (f"CAB-M{m:02d}", held.isoformat(), f"Customer Advisory Board · Session {m}", body))
        db.executemany("INSERT INTO cab_gt VALUES (?,?,?,?)", [(f"CAB-M{m:02d}", ln, acc, tid) for ln, acc, tid in gt])
