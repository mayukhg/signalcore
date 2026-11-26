"""Intake nodes: identity resolution (code), CAB Agent (Claude), enrichment (Claude, batched)."""
import difflib
import json
import re
from concurrent.futures import ThreadPoolExecutor

from ..llm import JUDGE, LIGHT

PERSONAL = {"gmail.com", "outlook.com", "yahoo.com", "proton.me", "hotmail.com", "icloud.com"}
SUFFIX = re.compile(r"\b(inc|llc|ltd|group|corp|co|plc|gmbh)\b\.?|\(.*?\)", re.I)


def norm(s):
    return re.sub(r"[^a-z0-9]+", "", SUFFIX.sub("", (s or "").lower()))


class Resolver:
    def __init__(self, run):
        self.email = {r[0].lower(): r[1] for r in run.q("SELECT email, account_id FROM contacts")}
        self.domain = {r[0]: r[1] for r in run.q("SELECT domain, account_id FROM accounts")}
        self.names = {norm(r[0]): r[1] for r in run.q("SELECT name, account_id FROM accounts")}
        self.first = {}
        for n, a in run.q("SELECT name, account_id FROM accounts"):
            self.first.setdefault(norm(n.split()[0]), []).append(a)

    def by_name(self, company):
        n = norm(company)
        if not n:
            return None, None, 0
        if n in self.names:
            return self.names[n], "company_name", .85
        best = difflib.get_close_matches(n, list(self.names), n=1, cutoff=.84)
        if best:
            return self.names[best[0]], "fuzzy_name", .7
        if n in self.first and len(self.first[n]) == 1:
            return self.first[n][0], "first_word", .55
        return None, None, 0

    def resolve(self, email, company):
        e = (email or "").lower()
        if e in self.email:
            return self.email[e], "contact_email", 1.0
        dom = e.split("@")[-1] if "@" in e else ""
        if dom in self.domain:
            return self.domain[dom], "email_domain", .9
        if dom and dom not in PERSONAL:
            base = norm(dom.split(".")[0].replace("-corp", ""))
            best = difflib.get_close_matches(base, list(self.names), n=1, cutoff=.8)
            if best:
                return self.names[best[0]], "domain_alias", .65
        return self.by_name(company)


def resolve_identities(run):
    with run.step("resolve", "Identity resolver") as s:
        r = Resolver(run)
        rows = run.q("SELECT feedback_id, reporter_email, reporter_company FROM qualitative_feedback")
        out, methods = [], {}
        for fid, email, comp in rows:
            acc, method, conf = r.resolve(email, comp)
            out.append((acc, method, conf, fid))
            methods[method or "unresolved"] = methods.get(method or "unresolved", 0) + 1
        run.db.executemany("UPDATE qualitative_feedback SET account_id=?, match_method=?, match_confidence=? WHERE feedback_id=?", out)
        run.db.commit()
        resolved = sum(v for k, v in methods.items() if k != "unresolved")
        s.detail = {"summary": f"Matched {resolved} of {len(rows)} feedback items to accounts", "methods": methods}
    return r


CAB_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["items"], "properties": {"items": {"type": "array", "items": {
    "type": "object", "additionalProperties": False, "required": ["line_no", "company", "speaker", "kind", "text", "sentiment"],
    "properties": {"line_no": {"type": "integer"}, "company": {"type": "string"}, "speaker": {"type": "string"},
                   "kind": {"type": "string", "enum": ["pain", "ask", "commitment", "praise"]},
                   "text": {"type": "string"}, "sentiment": {"type": "number"}}}}}}
CAB_SYSTEM = """You extract structured customer statements from Customer Advisory Board meeting notes for a B2B identity and device-management vendor.
For every line where a named customer attendee states a problem, makes a request, or praises something, return one item. Also return vendor commitments (action items or decisions) as kind "commitment" with company set to the customer they concern, or "" if none.
Use the exact line number shown. "text" is a faithful one-sentence paraphrase. sentiment is -1 (very negative) to 1 (very positive).
Ignore headers, agenda titles and attendee lists. Do not invent statements."""


def parse_cab(run, resolver):
    with run.step("cab", "CAB Agent · parse advisory-board notes") as s:
        meetings = run.q("SELECT meeting_id, body FROM cab_meetings ORDER BY meeting_id")

        def one(m):
            mid, body = m
            numbered = "\n".join(f"{i + 1:>3}| {l}" for i, l in enumerate(body.splitlines()))
            res = run.llm.structured("cab_parse", model=JUDGE, system=CAB_SYSTEM, user=f"Meeting {mid}:\n\n{numbered}",
                                     schema=CAB_SCHEMA, effort="medium", meter=s.meter)
            return mid, res["items"]

        with ThreadPoolExecutor(4) as ex:
            results = list(ex.map(one, meetings))
        rows, n = [], 0
        for mid, items in results:
            for it in items:
                n += 1
                acc, _, _ = resolver.by_name(it["company"])
                rows.append((run.run_id, f"{mid}-L{it['line_no']:02d}", mid, it["line_no"], acc, it["speaker"], it["kind"], it["text"], it["sentiment"]))
        run.db.executemany("INSERT OR REPLACE INTO cab_items VALUES (?,?,?,?,?,?,?,?,?)", rows)
        run.db.commit()
        kinds = {}
        for r in rows: kinds[r[6]] = kinds.get(r[6], 0) + 1
        s.detail = {"summary": f"Extracted {len(rows)} statements from {len(meetings)} CAB meetings", "kinds": kinds}


ENRICH_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["items"], "properties": {"items": {"type": "array", "items": {
    "type": "object", "additionalProperties": False,
    "required": ["id", "is_product_feedback", "urgency", "sentiment", "mentions_workaround", "persona"],
    "properties": {"id": {"type": "string"}, "is_product_feedback": {"type": "boolean"},
                   "urgency": {"type": "integer"}, "sentiment": {"type": "number"}, "mentions_workaround": {"type": "boolean"},
                   "persona": {"type": "string", "enum": ["economic_buyer", "it_admin", "security_lead", "end_user", "vendor", "unknown"]}}}}}}
ENRICH_SYSTEM = """You label customer feedback for a B2B identity, device and AI-agent access platform.
For each item return:
- is_product_feedback: true if it describes a product problem, gap or feature request; false for billing, how-to questions, admin requests, praise or chit-chat.
- urgency 1-5: 1 nice-to-have, 3 painful, 5 blocking a deal, rollout, audit or renewal.
- sentiment -1..1.
- mentions_workaround: true if the customer describes doing something manual or using another tool to cope.
- persona of the customer speaker.
Sarcasm counts as negative. Return one entry per id, same ids."""


def clean(body):
    body = re.sub(r"\[\d\d:\d\d\]\s*", "", body)
    body = re.sub(r"^(Subject|Summary|Customer|Impact|Notes):\s*", "", body, flags=re.M)
    return re.sub(r"\s+", " ", body).strip()


def enrich(run, batch=40):
    with run.step("enrich", "Enrichment · urgency, sentiment, workarounds (batched)") as s:
        items = [(r[0], clean(r[1])[:900]) for r in run.q("SELECT feedback_id, body FROM qualitative_feedback ORDER BY feedback_id")]
        items += [(r[0], r[1]) for r in run.q("SELECT item_id, text FROM cab_items WHERE run_id=? AND kind IN ('pain','ask') ORDER BY item_id", run.run_id)]
        batches = [items[i:i + batch] for i in range(0, len(items), batch)]

        def one(b):
            user = "\n".join(json.dumps({"id": i, "text": t}, ensure_ascii=False) for i, t in b)
            res = run.llm.structured("enrich", model=LIGHT, system=ENRICH_SYSTEM, user=user, schema=ENRICH_SCHEMA,
                                     effort="low", max_tokens=8000, meter=s.meter)
            return res["items"]

        with ThreadPoolExecutor(6) as ex:
            out = [x for r in ex.map(one, batches) for x in r]
        known = {i for i, _ in items}
        rows = [(run.run_id, o["id"], None, None, int(o["is_product_feedback"]), max(1, min(5, o["urgency"])),
                 max(-1, min(1, o["sentiment"])), int(o["mentions_workaround"]), o["persona"]) for o in out if o["id"] in known]
        run.db.executemany("INSERT OR REPLACE INTO feedback_enrichment VALUES (?,?,?,?,?,?,?,?,?)", rows)
        run.db.commit()
        prod = sum(r[4] for r in rows)
        s.detail = {"summary": f"Labelled {len(rows)} items in {len(batches)} batches; {prod} are product feedback",
                    "items": len(items), "labelled": len(rows), "product_feedback": prod}
