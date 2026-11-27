"""Scorers and tracing hooks, offline (stub mode, Langfuse disabled)."""
import os

from signalcore import observability as obs
from signalcore.evaluation import scorers
from signalcore.evaluation.experiments import _expected_numbers


OUT = {"answer": "GPL-102 depends on Globex Holdings, an open $1.24M deal [FB-00138]. 400 customers hold $46.88M ARR.",
       "steps": [{"tool": "run_sql", "result": {"columns": ["n", "arr", "amt"], "rows": [[400, 46884700, 1240000]]}}],
       "cited": [{"id": "FB-00138", "text": "Globex won't sign without it"}]}


def test_expected_entities_any_of():
    r = scorers.expected_entities(OUT, {"must_mention": ["Globex", ["GPL-102", "Globex SAML engine"], "SSO-88"]})
    assert r["value"] == round(2 / 3, 3) and "SSO-88" in r["comment"]


def test_numbers_grounded_and_untraced():
    assert scorers.numbers_grounded(OUT)["value"] == 1.0
    bad = dict(OUT, answer=OUT["answer"] + " Churn risk is $9.9M.")
    r = scorers.numbers_grounded(bad)
    assert r["value"] < 1.0 and "untraced" in r["comment"]


def test_citation_validity():
    assert scorers.citation_validity(OUT, {"FB-00138"})["value"] == 1.0
    assert scorers.citation_validity(dict(OUT, answer="see [FB-99999]"), {"FB-00138"})["value"] == 0.0


def test_expected_numbers_tolerance():
    assert _expected_numbers(OUT, {"numbers": [400, 46884700]})["value"] == 1.0
    assert _expected_numbers(OUT, {"numbers": [1300000], "tolerance": .1})["value"] == 1.0
    assert _expected_numbers(OUT, {"numbers": [2000000]})["value"] == 0.0


def test_tracing_is_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    assert not obs.enabled() and obs.client() is None
    with obs.root("x") as ctx:
        assert ctx.trace_id is None
        with obs.child(ctx, "y") as c:
            obs.generation(c, name="g", model="m", params={}, response={}, cost_usd=0, mode="stub")
            obs.score(c, "s", 1.0)
