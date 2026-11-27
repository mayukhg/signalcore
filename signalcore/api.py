"""FastAPI app: serves the UI and the JSON API.

    uvicorn signalcore.api:app --port 8000
"""
import datetime as dt
import json
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import analytics
from .ask import Retriever, ask as run_ask
from .db import DEFAULT_DB, connect
from .llm import LLM, default_mode
from .state import build_state, latest_run

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
DB = DEFAULT_DB

app = FastAPI(title="SignalCore")
app.mount("/static", StaticFiles(directory=WEB), name="static")
_events, _lock = {}, threading.Lock()
_cache = {"state": {}, "retriever": {}}


def ensure_data():
    if not Path(DB).exists():
        from .data.generate import build
        build(DB)
    db = connect(DB)
    has = latest_run(db)
    db.close()
    if not has:
        from .pipeline.graph import run_pipeline
        mode = "replay" if default_mode() in ("replay", "live") and (ROOT / "fixtures" / "llm_cache.jsonl").exists() else "stub"
        run_pipeline(DB, llm=LLM(mode), run_id="run-bootstrap")


@app.on_event("startup")
def startup():
    ensure_data()


def state(run_id=None):
    db = connect(DB)
    rid = run_id or latest_run(db)
    db.close()
    if rid not in _cache["state"]:
        _cache["state"][rid] = build_state(DB, rid)
    return _cache["state"][rid]


def retriever(run_id):
    if run_id not in _cache["retriever"]:
        _cache["retriever"][run_id] = Retriever(DB, run_id)
    return _cache["retriever"][run_id]


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/api/state")
def get_state(run: str | None = None):
    s = state(run)
    return JSONResponse(s | {"llm_mode": default_mode()})


class RunReq(BaseModel):
    mode: str | None = Field(None, description="live | replay | stub")
    user: str | None = None
    role: str | None = None


@app.post("/api/runs")
def start_run(req: RunReq):
    mode = req.mode or default_mode()
    if mode == "live" and default_mode() != "live":
        raise HTTPException(400, "Live runs need ANTHROPIC_API_KEY (or SIGNALCORE_ANTHROPIC_API_KEY) on the server.")
    rid = "run-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    with _lock:
        _events[rid] = []

    def on_event(e):
        with _lock:
            _events[rid].append(e | {"t": dt.datetime.now().isoformat(timespec="seconds")})

    def work():
        from .pipeline.graph import run_pipeline
        try:
            run_pipeline(DB, llm=LLM(mode), run_id=rid, on_event=on_event)
        except Exception as e:  # recorded on the run row and in events
            on_event({"type": "error", "message": f"{type(e).__name__}: {e}"})
        _cache["state"].clear()
        if analytics.enabled():
            db = connect(DB)
            try:
                completed, audited = analytics.run_summary(db, rid)
                analytics.track("Pipeline Run Completed", req.user or "signalcore-server", role=req.role, **completed)
                analytics.track("Roadmap Audited", req.user or "signalcore-server", role=req.role, **audited)
            finally:
                db.close()

    analytics.track("Pipeline Run Started", req.user or "signalcore-server", role=req.role, run_id=rid, mode=mode)
    threading.Thread(target=work, daemon=True).start()
    return {"run_id": rid, "mode": mode}


@app.get("/api/runs/{rid}/events")
def run_events(rid: str, after: int = 0):
    with _lock:
        ev = list(_events.get(rid, []))
    return {"events": ev[after:], "next": len(ev)}


class AskReq(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)
    user: str | None = None
    role: str | None = None


@app.post("/api/ask")
def post_ask(req: AskReq):
    s = state()
    rid = s["run"]["run_id"]
    mode = default_mode()
    llm = LLM(mode)
    who = dict(distinct_id=req.user or "anonymous", role=req.role, mode=mode)
    analytics.track("Question Asked", **who, question_length=len(req.question))
    t0 = dt.datetime.now()
    try:
        out = run_ask(req.question, DB, rid, llm, retriever(rid))
    except Exception as e:
        prev = next((a for a in s.get("asks", []) if a["question"].strip().lower() == req.question.strip().lower()), None) if mode == "replay" else None
        if not prev:
            analytics.track("Question Answered", **who, success=False, error=type(e).__name__,
                            latency_s=round((dt.datetime.now() - t0).total_seconds(), 2))
            if mode != "replay":
                raise HTTPException(500, f"{type(e).__name__}: {e}")
            raise HTTPException(409, "Replay mode can only answer recorded questions. Pick a suggested question or add an API key.")
        out = prev
    analytics.track("Question Answered", **who, success=True, tool_calls=len(out.get("steps", [])), cited_count=len(out.get("cited", [])),
                    cost_usd=out.get("cost_usd"), latency_s=round((dt.datetime.now() - t0).total_seconds(), 2))
    _cache["state"].clear()
    return out


class OverrideReq(BaseModel):
    theme_id: str
    feature_key: str
    effort_weeks: float = Field(..., gt=0, le=104)
    reason: str = Field(..., min_length=5, max_length=500)
    author: str = "PM"
    user: str | None = None
    role: str | None = None


@app.post("/api/overrides")
def post_override(req: OverrideReq):
    """PM override of the build estimate: logged with a reason, then CoD/CD3 are recomputed for the current run."""
    s = state()
    rid = s["run"]["run_id"]
    old = next((e["effort_weeks"] for e in s["estimates"] if e["feature_key"] == req.feature_key), None)
    db = connect(DB)
    db.execute("INSERT INTO pm_overrides (run_id, theme_id, field, old_value, new_value, reason, author, created_at) VALUES (?,?,?,?,?,?,?,?)",
               (rid, req.theme_id, f"effort:{req.feature_key}", str(old), str(req.effort_weeks), req.reason, req.author,
                dt.datetime.now().isoformat(timespec="seconds")))
    db.commit(); db.close()
    from .pipeline.rescore import rescore
    before = next((t["rank"] for t in s["themes"] if t["id"] == req.theme_id), None)
    rescore(DB, rid)
    _cache["state"].clear()
    new = state(rid)
    after = next((t["rank"] for t in new["themes"] if t["id"] == req.theme_id), None)
    who = dict(distinct_id=req.user or "anonymous", role=req.role or req.author)
    analytics.track("Estimate Overridden", **who, theme_id=req.theme_id, feature_key=req.feature_key, old_weeks=old,
                    new_weeks=req.effort_weeks, rank_before=before, rank_after=after)
    analytics.track("Decision Recorded", **who, kind="override", theme_id=req.theme_id)
    return {"ok": True, "state": new}


class TrackReq(BaseModel):
    event: str = Field(..., pattern=r"^(App Opened|View Viewed|Theme Opened|Evidence Inspected|PBR Exported|Decision Recorded)$")
    user: str = Field(..., min_length=4, max_length=64)
    role: str | None = Field(None, max_length=32)
    props: dict = Field(default_factory=dict)


@app.post("/api/track")
def post_track(req: TrackReq):
    """Relay for browser events (allow-listed names, scalar properties only), so the page never needs the token."""
    props = {k[:40]: v for k, v in list(req.props.items())[:20] if isinstance(v, (str, int, float, bool)) and k not in ("token", "distinct_id", "time")}
    analytics.track(req.event, req.user, role=req.role, mode=default_mode(), **props)
    return {"ok": True, "tracking": analytics.enabled()}
