"""Recompute Cost of Delay, CD3 and risks for an existing run (e.g. after a PM changes an estimate). No model calls."""
import json

from ..llm import LLM
from . import risks, score
from .run import Run


class ExistingRun(Run):
    def __init__(self, db_path, run_id):
        from ..db import connect
        self.db_path, self.db, self.run_id = str(db_path), connect(db_path), run_id
        self.llm = LLM("stub")
        self.on_event = lambda e: None
        self._step_no = self.db.execute("SELECT COALESCE(MAX(step_no),0) FROM agent_steps WHERE run_id=?", (run_id,)).fetchone()[0]
        import threading
        self._lock = threading.Lock()
        self._qlock = threading.RLock()

    def step(self, node, label):
        return super().step(node, "Recalculation after PM override · " + label)


def rescore(db_path, run_id):
    run = ExistingRun(db_path, run_id)
    sk = {}
    for tid, pen, notes, cited in run.q("SELECT theme_id, skeptic_penalty, skeptic_notes, skeptic_citations FROM theme_scores WHERE run_id=?", run_id):
        if notes:
            sk[tid] = json.loads(notes) | {"extra_penalty": pen, "cited_ids": json.loads(cited or "[]")}
    score.triangulate(run)
    score.trace_dependencies(run)
    score.score(run, skeptic=sk or None)
    run.db.execute("DELETE FROM risks WHERE run_id=?", (run_id,))
    risks.detect_risks(run)
    return run_id
