"""Deterministic stand-ins for Claude, used in stub mode (tests, keyless development).
They read only what the real model would see (the request), never ground-truth columns."""
import json
import re

NOISE_HINTS = ["invoice", "mfa", "w-9", "soc 2", "billing", "holiday", "rate limit", "training session", "verified domain",
               "status page", "read-only admin", "terraform", "eu region", "difference between", "remove ", "thanks for the quick",
               "ip ranges", "quarterly business review", "duplicate emails", "spam", "arm laptops", "export the audit log",
               "bulk-assign", "integrate with", "looked weird", "emoji"]
URGENT = ["won't sign", "blocker", "blocks", "renewal", "ciso", "audit", "paused", "sev-2", "other vendors", "lost a bake-off",
          "legal said", "won't approve", "locked out", "firefighting", "no laptop", "rfp", "hard requirement"]
MILD = ["nice to have", "+1", "would love", "would be great", "any plans", "nicer", "easier on the eyes"]
WORKAROUND = ["we export", "by hand", "manually", "script", "spreadsheet", "workaround", "proxy", "split our", "split the",
              "copy-paste", "zapier", "vdi", "chrome for now", "another tool", "throwaway", "separate tenant", "invert colors",
              "zoom screen", "rotate the token", "ansible", "strip all accents", "re-run the sync", "pilot group", "break-glass", "fall back"]
FEATURE_WORDS = {
    "agent_policy_editor": ["agent", "copilot", "llm", "gpt", "bot", "scope", "least-privilege", "token"],
    "scim_sync": ["scim", "workday", "provision", "sync", "new hires", "joiners", "starters"],
    "saml_config": ["saml", "assertion", "globex", "mainframe", "transform"],
    "patch_policies": ["patch", "os upgrade", "macos", "windows 11", "sequoia", "deferral"],
    "linux_enroll": ["linux", "ubuntu", "rhel", "debian", "fedora", "kernel", "enroll"],
    "console_theme": ["dark", "theme", "night", "bright"],
    "approval_flow": ["approv", "slack", "teams", "manager"],
    "browser_ext": ["safari", "extension", "autofill", "keychain"],
    "remote_session": ["remote", "lag", "apac", "sydney", "singapore", "tokyo", "manila"],
    "device_trust": ["byod", "posture", "personal devices", "unmanaged", "contractor laptops", "device trust"],
    "bulk_import": ["csv", "import", "row", "upload"],
    "conditional_access": ["conditional", "policy", "what-if", "simulator", "dry-run", "lock out", "locked out", "sign-in"],
}


def _text(params):
    m = params["messages"][-1]["content"]
    return m if isinstance(m, str) else json.dumps(m)


def _msg(obj, model, tokens=(1000, 300)):
    return {"model": model, "stop_reason": "end_turn", "usage": {"input_tokens": tokens[0], "output_tokens": tokens[1]},
            "content": [{"type": "text", "text": json.dumps(obj)}]}


def _tool(name, inp, model):
    return {"model": model, "stop_reason": "tool_use", "usage": {"input_tokens": 1500, "output_tokens": 200},
            "content": [{"type": "tool_use", "id": f"toolu_stub_{abs(hash(json.dumps(inp, sort_keys=True))) % 10**8}", "name": name, "input": inp}]}


def feature_for(text):
    t = text.lower()
    best, score = None, 0
    for f, words in FEATURE_WORDS.items():
        sc = sum(t.count(w) for w in words)
        if sc > score: best, score = f, sc
    return best


def respond(purpose, params):
    model = params["model"]
    if purpose == "enrich":
        out = []
        for line in _text(params).splitlines():
            it = json.loads(line)
            t = it["text"].lower()
            prod = not any(h in t for h in NOISE_HINTS)
            urg = 5 if sum(w in t for w in URGENT) >= 2 else 4 if any(w in t for w in URGENT) else 1 if any(w in t for w in MILD) else 3
            sent = -0.2 * urg + (0.3 if "thanks" in t or "great" in t and "/s" not in t else 0)
            out.append({"id": it["id"], "is_product_feedback": prod, "urgency": urg, "sentiment": round(max(-1, min(1, sent)), 2),
                        "mentions_workaround": any(w in t for w in WORKAROUND), "persona": "unknown"})
        return _msg({"items": out}, model)
    if purpose == "cab_parse":
        items = []
        for line in _text(params).splitlines():
            m = re.match(r"\s*(\d+)\|\s*- (\w+) \(([^)]+)\): (.*)", line)
            if m and "," not in m.group(3):
                txt = m.group(4)
                kind = "praise" if any(w in txt.lower() for w in ["great", "saved us", "painless", "exactly what"]) else "pain"
                items.append({"line_no": int(m.group(1)), "company": m.group(3), "speaker": m.group(2), "kind": kind, "text": txt,
                              "sentiment": .6 if kind == "praise" else -.5})
            m = re.match(r"\s*(\d+)\|\s+(\w+) added: (.*)", line)
            if m and items:
                items.append({"line_no": int(m.group(1)), "company": items[-1]["company"], "speaker": m.group(2), "kind": "ask",
                              "text": m.group(3), "sentiment": -.2})
            m = re.match(r"\s*(\d+)\|\s*- AI: Keystone to follow up with (.+?) on", line)
            if m:
                items.append({"line_no": int(m.group(1)), "company": m.group(2), "speaker": "Keystone", "kind": "commitment",
                              "text": line.split("|", 1)[1].strip(), "sentiment": 0})
        return _msg({"items": items}, model)
    if purpose == "name_themes":
        txt = _text(params)
        out = []
        for line in txt.split("Clusters:\n", 1)[1].splitlines():
            c = json.loads(line)
            f = feature_for(" ".join(c["samples"]) + " " + " ".join(c["keywords"]))
            out.append({"cluster_id": c["cluster_id"], "coherent": True, "merge_into": -1,
                        "title": " ".join(w.capitalize() for w in c["keywords"][:3]),
                        "problem_statement": "Customers report: " + c["samples"][0][:140], "feature_key": f or "user_lifecycle"})
        return _msg({"clusters": out}, model, (6000, 1500))
    if purpose == "skeptic":
        return _tool("submit_verdict", {"verdict": "stands", "extra_penalty": 1.0,
                                        "reason": "Stub mode: no independent audit was run.", "checks": [], "cited_ids": []}, model)
    if purpose == "pbr":
        facts = json.loads(_text(params).split("FACTS:\n", 1)[1].split("\n\nINSTRUCTIONS", 1)[0])
        claims = [{"claim_id": f"c{i + 1}", "section": f.get("section_hint", "health"), "text": f"{f['label']}: {f['value']}.",
                   "fact_ids": [f["fact_id"]]} for i, f in enumerate(facts[:8])]
        return _msg({"headline": "Stub-mode review generated from facts.", "claims": claims, "asks": []}, model, (4000, 900))
    if purpose == "judge":
        claims = json.loads(_text(params).split("CLAIMS:\n", 1)[1])
        return _msg({"verdicts": [{"claim_id": c["claim_id"], "grounded": True, "reason": "Stub mode: numbers checked by code only."} for c in claims]}, model)
    if purpose == "ask":
        if len(params["messages"]) == 1:
            return _tool("search_evidence", {"query": _text(params)[:200], "k": 5, "source": "", "segment": ""}, model)
        return _tool("final_answer", {"answer": "Stub mode: here are the most relevant verbatims. Connect an API key for a written answer.",
                                      "cited_ids": []}, model)
    raise KeyError(purpose)
