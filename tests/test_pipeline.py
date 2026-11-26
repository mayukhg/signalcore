"""End-to-end and unit tests. Run in stub mode: no API key or network needed."""
import json

import pytest

from signalcore.data.generate import build
from signalcore.db import readonly, run_readonly_sql
from signalcore.llm import LLM
from signalcore.pipeline.graph import run_pipeline
from signalcore.pipeline.pbr import numbers_ok, nums
from signalcore.state import build_state


@pytest.fixture(scope="session")
def db(tmp_path_factory):
    p = tmp_path_factory.mktemp("d") / "t.db"
    build(p)
    run_pipeline(p, llm=LLM("stub"), run_id="t1")
    return p


def evals(db):
    import sqlite3
    return dict(sqlite3.connect(db).execute("SELECT metric, value FROM evals WHERE run_id='t1'").fetchall())


def test_generator_is_deterministic(tmp_path):
    import sqlite3
    a, b = build(tmp_path / "a.db"), build(tmp_path / "b.db")
    qa = sqlite3.connect(a).execute("SELECT body FROM qualitative_feedback ORDER BY feedback_id LIMIT 50").fetchall()
    qb = sqlite3.connect(b).execute("SELECT body FROM qualitative_feedback ORDER BY feedback_id LIMIT 50").fetchall()
    assert qa == qb


def test_pipeline_recovers_planted_truth(db):
    e = evals(db)
    assert e["cluster_precision"] > .9 and e["cluster_recall"] > .9
    assert e["pattern_recovery"] == 1.0
    assert e["bottleneck_found"] == 1.0
    assert e["identity_precision"] > .97 and e["identity_coverage"] > .85
    assert e["cab_recall"] > .9


def test_cd3_ranking_is_consistent(db):
    s = build_state(db, "t1")
    ts = s["themes"]
    assert [t["rank"] for t in ts] == list(range(1, len(ts) + 1))
    for t in ts:
        assert t["cod_adj"] == pytest.approx(t["cod"] * t["evidence"] / 100, rel=1e-6)
        assert t["cd3"] == pytest.approx(t["cod_adj"] / (t["effort"] + t["blocked_weeks"]), rel=1e-6)
    assert all(a["cd3"] >= b["cd3"] for a, b in zip(ts, ts[1:]))


def test_mirage_is_discounted(db):
    s = build_state(db, "t1")
    mir = [t for t in s["themes"] if t["archetype"] == "commercial_mirage"]
    assert mir and all(t["evidence"] < 40 for t in mir)


def test_readonly_guard(db):
    c = readonly(db, "t1")
    assert "error" in run_readonly_sql(c, "DELETE FROM accounts")
    assert "error" in run_readonly_sql(c, "SELECT gt_theme_id FROM qualitative_feedback")
    assert "error" in run_readonly_sql(c, "SELECT * FROM cab_gt")
    assert "error" in run_readonly_sql(c, "SELECT 1; DROP TABLE accounts")
    assert run_readonly_sql(c, "SELECT COUNT(*) FROM v_feedback")["rows"][0][0] > 1000


def test_number_grounding():
    facts = [{"label": "ARR", "value": "$1.29M"}, {"label": "abandon", "value": "45% vs 12%"}]
    assert numbers_ok("ARR is $1.29M and abandonment 45%", facts) == []
    assert numbers_ok("ARR is $1.3M", facts) == []          # rounding allowed
    assert numbers_ok("ARR is $2M", facts) == [2e6]          # invented number caught
    assert nums("TH-02 and SSO-88 in 2027-Q1") == []         # ids and quarters ignored


def test_override_recomputes(db):
    import sqlite3
    from signalcore.pipeline.rescore import rescore
    s = build_state(db, "t1")
    t = s["themes"][0]
    con = sqlite3.connect(db)
    con.execute("INSERT INTO pm_overrides (run_id, theme_id, field, old_value, new_value, reason, author, created_at) VALUES (?,?,?,?,?,?,?,?)",
                ("t1", t["id"], f"effort:{t['feature']}", str(t["effort"]), str(t["effort"] * 10), "test", "pytest", "now"))
    con.commit()
    rescore(db, "t1")
    t2 = next(x for x in build_state(db, "t1")["themes"] if x["id"] == t["id"])
    assert t2["effort"] == t["effort"] * 10 and t2["cd3"] < t["cd3"]
