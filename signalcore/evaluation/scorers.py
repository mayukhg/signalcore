"""Scorers shared by live tracing and offline experiments.

Code scorers are deterministic and free; the LLM judge (Claude Sonnet) runs only where a model is available.
Every scorer returns {"name", "value", "comment"} so it can feed Langfuse scores or experiment evaluations.
"""
import json
import re

from ..llm import JUDGE
from ..pipeline.pbr import JUDGE_SCHEMA, JUDGE_SYSTEM, nums

CITE = re.compile(r"\b(FB-\d{5}|CAB-M\d\d-L\d\d)\b")


def _evidence_text(out):
    """Everything the agent saw: SQL result rows and the verbatims it retrieved or cited."""
    parts = []
    for s in out.get("steps", []):
        if s.get("tool") == "run_sql":
            parts.append(json.dumps(s.get("result", {}), default=str))
    for c in out.get("cited", []):
        parts.append(f"{c.get('id')} {c.get('text', '')}")
    return "\n".join(parts)


def citation_validity(out, known_ids):
    """Share of cited ids that exist in the data. 1.0 when nothing is cited (scored separately by citation_count)."""
    ids = set(CITE.findall(out.get("answer", "")))
    if not ids:
        return {"name": "citation_validity", "value": 1.0, "comment": "No inline citations."}
    bad = sorted(i for i in ids if i not in known_ids)
    return {"name": "citation_validity", "value": round(1 - len(bad) / len(ids), 3),
            "comment": f"{len(ids) - len(bad)} of {len(ids)} cited ids exist" + (f"; unknown: {', '.join(bad[:5])}" if bad else "")}


def numbers_grounded(out):
    """Share of numbers in the answer that appear in (or round from) the tool outputs the agent actually saw."""
    have = nums(_evidence_text(out))
    found = nums(re.sub(r"\b\d{4}-\d\d-\d\d\b", " ", out.get("answer", "")))
    found = [n for n in found if n not in range(0, 13) or n in have]   # small counts like "2 of 4" are hard to trace; keep if present
    if not found:
        return {"name": "numbers_grounded", "value": 1.0, "comment": "No numeric claims."}
    ok = [n for n in found if any(abs(n - h) <= max(.5, .02 * abs(h)) for h in have)]
    miss = [n for n in found if n not in ok]
    return {"name": "numbers_grounded", "value": round(len(ok) / len(found), 3),
            "comment": f"{len(ok)} of {len(found)} numbers traced to tool output" + (f"; untraced: {', '.join(f'{m:g}' for m in miss[:6])}" if miss else "")}


def expected_entities(out, expected):
    """Share of required entities (names, ids, values) present in the answer. Case-insensitive."""
    req = expected.get("must_mention", []) if isinstance(expected, dict) else []
    if not req:
        return {"name": "expected_entities", "value": 1.0, "comment": "No required entities."}
    text = out.get("answer", "").lower().replace(",", "")
    forms = lambda e: e if isinstance(e, list) else [e]          # an entry may list acceptable alternatives
    hit = [e for e in req if any(f.lower().replace(",", "") in text for f in forms(e))]
    missing = [forms(e)[0] for e in req if e not in hit]
    return {"name": "expected_entities", "value": round(len(hit) / len(req), 3),
            "comment": f"Mentions {len(hit)}/{len(req)}; missing: {', '.join(missing) or 'none'}"}


ASK_JUDGE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["correctness", "groundedness", "reasoning"],
                    "properties": {"correctness": {"type": "number"}, "groundedness": {"type": "number"}, "reasoning": {"type": "string"}}}
ASK_JUDGE_SYSTEM = """You grade answers from a product-evidence assistant.
correctness (0-1): does the answer address the question and agree with the reference notes? Partial credit for partly right.
groundedness (0-1): is every factual statement supported by the tool evidence shown? Penalise invented numbers, names or causal claims.
Be strict and brief. Reasoning: two sentences at most."""


def llm_judge_ask(llm, question, out, expected, meter=None):
    """LLM-as-judge (Claude Sonnet) for Ask answers. Returns two scores."""
    user = json.dumps({"question": question, "reference": expected, "answer": out.get("answer"),
                       "evidence": _evidence_text(out)[:20000]}, ensure_ascii=False)
    r = llm.structured("lf_judge_ask", model=JUDGE, system=ASK_JUDGE_SYSTEM, user=user, schema=ASK_JUDGE_SCHEMA,
                       effort="medium", max_tokens=4000, meter=meter)
    clamp = lambda v: max(0.0, min(1.0, float(v)))
    return [{"name": "judge_correctness", "value": clamp(r["correctness"]), "comment": r["reasoning"]},
            {"name": "judge_groundedness", "value": clamp(r["groundedness"]), "comment": r["reasoning"]}]


def grounding_judge_single(llm, claim_text, facts, meter=None):
    """Run the production Grounding Judge prompt on one claim (used to calibrate the judge itself)."""
    payload = [{"claim_id": "c1", "text": claim_text, "facts": facts}]
    v = llm.structured("judge", model=JUDGE, system=JUDGE_SYSTEM, user="CLAIMS:\n" + json.dumps(payload, ensure_ascii=False),
                       schema=JUDGE_SCHEMA, effort="medium", meter=meter)["verdicts"]
    return v[0] if v else {"grounded": False, "reason": "no verdict"}
