"""Run context: database, LLM, step logging and progress events."""
import contextlib
import datetime as dt
import json
import threading
import time

from ..db import connect, DEFAULT_DB
from ..llm import LLM, Meter


class Step:
    def __init__(self, node, label):
        self.node, self.label = node, label
        self.detail = {}
        self.meter = Meter()


class Run:
    def __init__(self, db_path=DEFAULT_DB, llm=None, run_id=None, on_event=None):
        self.db_path = str(db_path)
        self.db = connect(db_path)
        self.llm = llm or LLM()
        self.run_id = run_id or "run-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.on_event = on_event or (lambda e: None)
        self._step_no = 0
        self._lock = threading.Lock()
        self.db.execute("INSERT OR REPLACE INTO agent_runs (run_id, started_at, mode, status) VALUES (?,?,?,?)",
                        (self.run_id, dt.datetime.now().isoformat(timespec="seconds"), self.llm.mode, "running"))
        self.db.commit()

    def q(self, sql, *args):
        return self.db.execute(sql, args).fetchall()

    @contextlib.contextmanager
    def step(self, node, label):
        with self._lock:
            self._step_no += 1
            no = self._step_no
        s = Step(node, label)
        t0 = time.time()
        started = dt.datetime.now().isoformat(timespec="seconds")
        self.on_event({"type": "step_started", "step_no": no, "node": node, "label": label})
        try:
            yield s
        finally:
            ms = int((time.time() - t0) * 1000)
            with self._lock:
                self.db.execute("INSERT OR REPLACE INTO agent_steps VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                (self.run_id, no, node, label, started, ms, ",".join(sorted(s.meter.models)) or None,
                                 s.meter.tokens_in, s.meter.tokens_out, round(s.meter.cost, 5), json.dumps(s.detail, default=str)))
                self.db.execute("UPDATE agent_runs SET tokens_in = tokens_in + ?, tokens_out = tokens_out + ?, cost_usd = cost_usd + ? WHERE run_id = ?",
                                (s.meter.tokens_in, s.meter.tokens_out, s.meter.cost, self.run_id))
                self.db.commit()
            self.on_event({"type": "step_finished", "step_no": no, "node": node, "label": label, "ms": ms,
                           "cost": round(s.meter.cost, 4), "summary": s.detail.get("summary")})

    def finish(self, status="done"):
        self.db.execute("UPDATE agent_runs SET status = ?, finished_at = ? WHERE run_id = ?",
                        (status, dt.datetime.now().isoformat(timespec="seconds"), self.run_id))
        self.db.commit()
        self.on_event({"type": "run_finished", "status": status, "run_id": self.run_id})
