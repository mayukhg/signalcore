"""Product analytics: sends SignalCore usage events to Mixpanel (https://api.mixpanel.com/track).

Off unless MIXPANEL_TOKEN is set. Events are queued and sent from a background thread, so tracking
never slows a request or a pipeline run, and a Mixpanel outage never breaks the app.
Event names and properties are documented in docs/METRICS.md.
"""
import atexit
import json
import os
import queue
import threading
import time
import uuid

APP_VERSION = "2.0"
_q: "queue.Queue[dict]" = queue.Queue(maxsize=10000)
_started = False
_lock = threading.Lock()


def enabled():
    return bool(os.environ.get("MIXPANEL_TOKEN"))


def track(event, distinct_id="signalcore-server", **props):
    if not enabled():
        return
    p = {"token": os.environ["MIXPANEL_TOKEN"], "distinct_id": distinct_id, "time": int(time.time() * 1000),
         "$insert_id": uuid.uuid4().hex, "app_version": APP_VERSION, **{k: v for k, v in props.items() if v is not None}}
    try:
        _q.put_nowait({"event": event, "properties": p})
    except queue.Full:
        return
    _ensure_worker()


def _ensure_worker():
    global _started
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_worker, daemon=True).start()


def _send(batch):
    import httpx
    url = os.environ.get("MIXPANEL_API", "https://api.mixpanel.com") + "/track?ip=0"
    for attempt in range(3):
        try:
            r = httpx.post(url, data={"data": json.dumps(batch)}, timeout=10)
            if r.status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2 ** attempt)


def _worker():
    while True:
        batch = [_q.get()]
        while len(batch) < 50:
            try:
                batch.append(_q.get(timeout=1))
            except queue.Empty:
                break
        _send(batch)


@atexit.register
def _flush():
    batch = []
    while not _q.empty() and len(batch) < 50:
        batch.append(_q.get_nowait())
    if batch:
        _send(batch)


def run_summary(db, run_id):
    """Properties for `Pipeline Run Completed` and `Roadmap Audited`, read from what the run wrote."""
    q = lambda sql, *a: db.execute(sql, a).fetchall()
    run = q("SELECT status, started_at, finished_at, cost_usd, mode FROM agent_runs WHERE run_id=?", run_id)[0]
    ev = dict(q("SELECT metric, value FROM evals WHERE run_id=?", run_id))
    themes = q("SELECT COUNT(*), COALESCE(SUM(cod_adj_week_usd),0), SUM(skeptic_penalty < 1) FROM theme_scores WHERE run_id=?", run_id)[0]
    risks = dict(q("SELECT kind, COUNT(*) FROM risks WHERE run_id=? GROUP BY kind", run_id))
    dropped = q("SELECT COUNT(*) FROM brief_claims WHERE run_id=? AND status='dropped'", run_id)[0][0]
    import datetime as dt
    dur = None
    if run[1] and run[2]:
        dur = (dt.datetime.fromisoformat(run[2]) - dt.datetime.fromisoformat(run[1])).total_seconds()
    committed = q("""SELECT COUNT(*), SUM(s.evidence_score >= 70), SUM(s.evidence_score < 50) FROM roadmap_items r
                     JOIN gpl_links l ON l.item_id = r.item_id AND l.run_id = ?
                     JOIN theme_scores s ON s.theme_id = l.theme_id AND s.run_id = l.run_id
                     WHERE r.status != 'proposed'""", run_id)[0]
    completed = dict(run_id=run_id, status="done" if run[0] == "done" else "failed", mode=run[4], duration_s=dur,
                     cost_usd=round(run[3] or 0, 4), themes=themes[0], skeptic_weakened=themes[2] or 0,
                     cod_adj_week_usd=round(themes[1]), risks=sum(risks.values()), silent_churn_risks=risks.get("silent_churn", 0),
                     grounded_first_pass=ev.get("grounded_first_pass"), claims_dropped=dropped,
                     cluster_precision=ev.get("cluster_precision"), pattern_recovery=ev.get("pattern_recovery"))
    audited = dict(run_id=run_id, committed_items=committed[0] or 0, strong_evidence_items=committed[1] or 0, weak_bets=committed[2] or 0,
                   strong_share=round((committed[1] or 0) / committed[0], 3) if committed[0] else None)
    return completed, audited
