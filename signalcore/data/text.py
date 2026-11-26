"""Compositional, deliberately messy customer-feedback text.

Each planted theme has pools of symptom / impact / workaround / ask fragments and a synonym table.
Items are assembled per source (Gong transcript turns, Zendesk ticket, Jira bug, idea-portal post,
advisory-board note), then roughened with typos, sarcasm, filler and occasional mixed topics.
"""
import random

THEME_TEXT = {
    "T01": dict(
        syn={"AGENT": ["AI agent", "copilot", "our LLM assistant", "the agent service account", "AI bot", "agent identity", "the GPT integration"],
             "SCOPE": ["least-privilege scopes", "per-tool permissions", "fine-grained access", "resource-level scoping", "read-only access to specific OUs"]},
        symptom=["we can't give {AGENT} {SCOPE}, it's all or nothing on the API token",
                 "there's no way to restrict which directories {AGENT} can read",
                 "the agent policy editor times out once you add more than a handful of resource scopes",
                 "{AGENT} ends up with admin-level tokens because the policy editor won't save narrower rules",
                 "permissions for {AGENT} can't be limited to a group or OU",
                 "every time we try to scope {AGENT} the policy editor throws a validation error",
                 "we can't tell what {AGENT} actually touched, and there's no way to cap it"],
        impact=["security won't sign off on the rollout", "our CISO paused the pilot", "we're stuck at 20 users instead of 2,000",
                "this blocks the expansion we discussed", "audit flagged it as a finding", "legal said no until it's fixed"],
        workaround=["we spun up a separate tenant just to sandbox agent identities", "we proxy every agent call through our own gateway",
                    "we rotate the token daily by hand", "we gave it a throwaway account and hope for the best"],
        ask=["we need {SCOPE} for {AGENT}", "can {AGENT} get scoped permissions like a normal user", "is fine-grained agent access on the roadmap"]),
    "T02": dict(
        syn={"SCIM": ["SCIM", "Workday provisioning", "the Workday sync", "HR-driven provisioning", "auto-provisioning from Workday"],
             "NEW": ["new hires", "new starters", "Monday's joiners", "contractors", "people who transferred teams"]},
        symptom=["{SCIM} reports success but {NEW} never show up in the directory",
                 "{SCIM} silently drops users with special characters in their names",
                 "provisioning errors don't surface anywhere, the job just says completed",
                 "{NEW} get created without group memberships after the sync",
                 "{SCIM} stopped updating manager fields and nobody noticed for weeks",
                 "the sync log is green but half the accounts are missing"],
        impact=["{NEW} had no laptop or email access on day one", "managers are escalating to our CIO", "IT spends Monday mornings firefighting",
                "it's the main reason we're looking at other vendors at renewal", "onboarding NPS tanked"],
        workaround=["we export a CSV every Monday and diff it against the directory", "we re-run the sync manually three times a day",
                    "we create the missing users by hand"],
        ask=["please surface {SCIM} errors and retry failed users", "we need alerts when provisioning fails", "can you show which users failed and why"]),
    "T03": dict(
        syn={"SAML": ["SAML assertions", "SAML attributes", "the assertion payload", "attribute statements"],
             "XFORM": ["regex transforms", "custom attribute rewriting", "a transform engine", "scripted attribute mapping"]},
        symptom=["Globex needs {XFORM} on {SAML} before they hit the mainframe portal",
                 "their legacy mainframe portal only accepts a rewritten employee ID in {SAML}",
                 "Globex's architect walked through the portal again and it needs {XFORM}",
                 "the Globex team wants to rewrite {SAML} with their own scripts"],
        impact=["Globex won't sign without it", "the AE says it's the only blocker on the Globex deal",
                "Globex procurement made it a hard requirement", "their VP wants it in writing before Q1"],
        workaround=["their SI offered to build a proxy, but they want it native"],
        ask=["the rep wants {XFORM} on the Q1 roadmap", "can we commit to {XFORM} for Globex"]),
    "T04": dict(
        syn={"PATCH": ["patch policies", "scheduled patching", "the patch schedule", "OS update policies"],
             "OS": ["the macOS 16 upgrade", "the Windows 11 feature update", "the last OS upgrade", "Sequoia point releases"]},
        symptom=["{PATCH} show compliant but half the fleet is still on the old build after {OS}",
                 "{PATCH} quietly stopped applying after {OS}",
                 "after {OS} the deferral settings in {PATCH} are ignored"],
        impact=["we only found out from a vulnerability scan", "auditors asked why devices were behind"],
        workaround=["we moved patching back to a script", "we switched patching to another tool for now"],
        ask=["is {PATCH} supposed to survive {OS}"]),
    "T05": dict(
        syn={"LINUX": ["Ubuntu", "RHEL", "Linux", "Debian boxes", "our Linux dev fleet", "Fedora laptops"]},
        symptom=["enrolling {LINUX} devices is manual and breaks on every kernel update",
                 "{LINUX} enrollment needs three scripts and still fails behind our proxy",
                 "the agent install on {LINUX} has no zero-touch option",
                 "{LINUX} devices fall out of inventory after a reboot"],
        impact=["engineering refuses to enroll their laptops", "we lost a bake-off to a competitor that enrolls {LINUX} zero-touch",
                "a third of our fleet is invisible to IT"],
        workaround=["we keep {LINUX} machines in a spreadsheet", "we wrote our own Ansible role to install the agent"],
        ask=["we need zero-touch enrollment for {LINUX}", "please support {LINUX} the way you support macOS"]),
    "T06": dict(
        syn={"DARK": ["dark mode", "a dark theme", "night mode", "a darker admin console theme"]},
        symptom=["would love {DARK} for the admin console", "the console is really bright at night, {DARK} please",
                 "+1 for {DARK}", "any plans for {DARK}?"],
        impact=["it'd be easier on the eyes", "would make late-night on-call nicer", "nice to have, not urgent"],
        workaround=["we use a browser extension to invert colors"],
        ask=["please add {DARK}", "{DARK} would be great"]),
    "T07": dict(
        syn={"APPR": ["access request approvals", "approval emails", "approvals", "access requests"],
             "CHAT": ["Slack", "Teams", "Slack or Teams", "chat"]},
        symptom=["{APPR} sit for days because managers never open the email",
                 "managers miss {APPR} and IT ends up approving on their behalf",
                 "there's no way to approve from {CHAT}, so requests pile up",
                 "approvers don't get reminders, so {APPR} go stale"],
        impact=["it defeats the audit trail", "employees wait three days for a tool they need today",
                "we can't roll Access Requests out company-wide like this"],
        workaround=["IT chases managers on {CHAT} manually", "we built a Zapier hook that pings managers"],
        ask=["let managers approve in {CHAT}", "we need {CHAT} approvals with one click"]),
    "T08": dict(
        syn={"EXT": ["the browser extension", "the password manager extension", "the Safari extension", "the autofill extension"]},
        symptom=["{EXT} crashes every time Safari opens a new window", "{EXT} keeps logging out after the Safari update",
                 "autofill from {EXT} stopped working on Safari 19", "{EXT} spins forever on Safari and never unlocks"],
        impact=["our Mac users went back to iCloud Keychain", "people are reusing passwords again", "helpdesk tickets doubled this week"],
        workaround=["we told everyone to use Chrome for now", "users copy-paste from the desktop app"],
        ask=["please fix {EXT} on Safari", "is there an ETA on the Safari fix"]),
    "T09": dict(
        syn={"RA": ["remote sessions", "Remote Assist", "screen sharing sessions", "remote support"],
             "APAC": ["Singapore", "Sydney", "our APAC offices", "Tokyo", "Manila"]},
        symptom=["{RA} to {APAC} lag two or three seconds per click", "{RA} to {APAC} drop after a few minutes",
                 "video quality on {RA} to {APAC} is unusable"],
        impact=["helpdesk uses another tool for APAC", "resolution times in {APAC} doubled"],
        workaround=["we fall back to Zoom screen share"],
        ask=["do you have relay servers in {APAC}"]),
    "T10": dict(
        syn={"BYOD": ["personal devices", "BYOD laptops", "unmanaged devices", "contractor laptops"]},
        symptom=["we can't check posture on {BYOD} before granting SSO", "there's no device trust signal for {BYOD}",
                 "{BYOD} get the same access as managed devices"],
        impact=["it's a checkbox on every enterprise RFP we see", "our auditors flagged it", "security won't allow contractors in without it"],
        workaround=["we force contractors onto VDI"],
        ask=["we need posture checks for {BYOD}", "is device trust for {BYOD} coming"]),
    "T11": dict(
        syn={"CSV": ["bulk import", "the CSV import", "user import", "bulk user upload"]},
        symptom=["{CSV} failed with 'invalid row' and no row number", "{CSV} rejects the whole file because of one bad line",
                 "{CSV} errors don't say which column is wrong", "{CSV} chokes on accented names"],
        impact=["it took an afternoon to onboard 40 people", "we gave up and added users by hand"],
        workaround=["we split the CSV into 20 files to find the bad line", "we strip all accents before uploading"],
        ask=["show the failing row in {CSV} errors", "let {CSV} skip bad rows and continue"]),
    "T12": dict(
        syn={"CA": ["conditional access", "access policies", "conditional access rules", "sign-in policies"]},
        symptom=["we can't preview who a {CA} change will lock out", "there's no what-if mode for {CA}",
                 "changing {CA} is a leap of faith with 4,000 users", "we tested a {CA} change and locked out the CEO by accident"],
        impact=["we avoid tightening policies at all", "change advisory board won't approve policy changes", "we had a sev-2 from a bad rule"],
        workaround=["we test changes on a single pilot group for a week first", "we keep a break-glass admin just in case"],
        ask=["we need a policy simulator for {CA}", "a dry-run mode for {CA} would be huge"]),
}

NOISE = [
    "How do I reset MFA for {who}?", "Question about last month's invoice, we were billed for {n} extra seats.",
    "Can you add {dom} as a verified domain?", "Login page looked weird yesterday, fine now.",
    "Feature request: emoji support in group names lol", "Where is the API rate limit documented?",
    "Can we get a training session for our {n} new admins?", "Is there a SOC 2 report we can share with our auditors?",
    "Our renewal paperwork needs a W-9, who do I ask?", "How do I export the audit log to our SIEM?",
    "Is the status page accurate? We saw a blip around {t}.", "Can {who} be made a read-only admin?",
    "Please update our billing contact to {who}.", "Does the agent support ARM laptops?",
    "We'd like a quarterly business review with our CSM.", "Thanks for the quick fix on the login issue!",
    "What's the difference between the Core and Platform plans?", "Can we move our tenant to the EU region?",
    "How do I bulk-assign a policy to a device group?", "Is there a Terraform provider?",
    "We're seeing duplicate emails from the notification service.", "Can you remove {who} from our account?",
    "Do you integrate with {tool}?", "Password reset emails go to spam for some users.",
    "Reminder that we're closed for the holidays from {t}.", "What are the IP ranges for your SSO service?",
]
NOISE_FILL = dict(who=["Priya", "our CFO", "a contractor", "John in finance", "the helpdesk lead"], n=["5", "12", "40", "3"],
                  dom=["acme-labs.io", "northstar.co", "example.org"], t=["2pm UTC", "Dec 23", "last Tuesday 09:40"],
                  tool=["ServiceNow", "Okta", "Jamf", "CrowdStrike", "Snowflake"])

SARCASM = ["Love that {x}. /s", "Great, so {x}. Fantastic.", "Cool cool cool, {x}.", "Shocking news: {x}.", "Another week, another round of: {x}."]
FILLER_OPEN = ["Hi team,", "Hey folks -", "Hello,", "Hi support,", "", "", "Quick one:", "Following up again:"]
FILLER_CLOSE = ["Thanks.", "Thx", "Appreciate any help.", "", "", "Let us know ASAP.", "Cheers"]
FIRST = "Priya Marcus Lena Tomás Aisha Kenji Olu Sara Dmitri Grace Ravi Ines Noah Mei Carlos Zoe Femi Hana Leo Maya".split()
TITLES = ["IT Director", "Head of IT", "Security Engineer", "CISO", "Sysadmin", "VP Engineering", "IT Manager", "Identity Architect"]


def typo(s, rng, p=0.035):
    out, words = [], s.split(" ")
    for w in words:
        if len(w) > 4 and rng.random() < p:
            i = rng.randrange(1, len(w) - 2)
            w = w[:i] + w[i + 1] + w[i] + w[i + 2:] if rng.random() < .6 else w[:i] + w[i + 1:]
        out.append(w)
    return " ".join(out)


def fill(tmpl, syn, rng):
    for k, vals in syn.items():
        while "{" + k + "}" in tmpl:
            tmpl = tmpl.replace("{" + k + "}", rng.choice(vals), 1)
    return tmpl


def cap(s):
    return s[:1].upper() + s[1:] if s else s


def theme_sentences(tid, rng):
    t = THEME_TEXT[tid]
    f = lambda pool: fill(rng.choice(pool), t["syn"], rng)
    parts = [f(t["symptom"])]
    if rng.random() < .75: parts.append(f(t["impact"]))
    wk = rng.random() < (.55 if tid in ("T01", "T02", "T11") else .25)
    if wk: parts.append(f(t["workaround"]))
    if rng.random() < .45: parts.append(f(t["ask"]))
    return parts, wk


def render(source, tid, rng, company, second_tid=None):
    """Return (body, mentions_workaround) for one feedback item. tid None => noise."""
    if tid is None:
        tmpl = rng.choice(NOISE)
        for k, v in NOISE_FILL.items():
            tmpl = tmpl.replace("{" + k + "}", rng.choice(v))
        body = tmpl
        if source == "gong":
            body = f"[{rng.randint(1, 50):02d}:{rng.randint(0, 59):02d}] {rng.choice(FIRST)} ({rng.choice(TITLES)}): {body}"
        return typo(body, rng), False
    parts, wk = theme_sentences(tid, rng)
    if second_tid:
        p2, _ = theme_sentences(second_tid, rng)
        parts.append("Also, unrelated: " + p2[0])
    if rng.random() < .12:
        parts[0] = rng.choice(SARCASM).format(x=parts[0])
    sents = [cap(p.strip()) + ("" if p.strip().endswith((".", "?", "!")) else ".") for p in parts]
    if source == "gong":
        who, ae = rng.choice(FIRST), rng.choice(FIRST)
        ts = lambda: f"[{rng.randint(1, 50):02d}:{rng.randint(0, 59):02d}]"
        lines = [f"{ts()} {who} ({rng.choice(TITLES)}, {company}): {' '.join(sents[:2])}"]
        lines.append(f"{ts()} {ae} (AE): " + rng.choice(["Got it, can you say more about the impact?", "Understood. How are you handling it today?",
                                                         "Okay, I'll take that back to product.", "Is that a blocker for the renewal?"]))
        if len(sents) > 2:
            lines.append(f"{ts()} {who}: {' '.join(sents[2:])}")
        body = "\n".join(lines)
    elif source == "zendesk":
        subj = sents[0][:70].rstrip(".")
        body = f"Subject: {subj}\n\n{rng.choice(FILLER_OPEN)} {' '.join(sents)} {rng.choice(FILLER_CLOSE)}".strip()
    elif source == "jira":
        body = f"Summary: {sents[0]}\nCustomer: {company}\nImpact: {sents[1] if len(sents) > 1 else 'n/a'}\nNotes: {' '.join(sents[2:]) or '-'}"
    elif source == "idea_portal":
        body = f"{cap(sents[-1].rstrip('.'))}\n\n{' '.join(sents[:-1])}" if len(sents) > 1 else sents[0]
    else:  # cab
        body = f"CAB note: attendee from {company} flagged that {parts[0]}. " + " ".join(sents[1:])
    return typo(body, rng), wk
