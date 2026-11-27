"""Langfuse tracing and scoring for SignalCore (off unless configured).

Enable with LANGFUSE_BASE_URL (e.g. https://us.cloud.langfuse.com) plus LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY.
In this repo's cloud environment the keys are injected by the network proxy, so placeholders are used when the
variables are absent and only LANGFUSE_BASE_URL is needed.

Trace shape for a pipeline run:
    signalcore.pipeline (root span, one per run)
      └ <node> span per LangGraph step          (resolve, cab, enrich, cluster, ..., judge, evals)
          └ <purpose> generation per Claude call (model, input, output, tokens, cost)
    + scores: every eval metric, per-theme Skeptic penalties, PBR grounding rates
Agent threads don't inherit OpenTelemetry context, so children attach with an explicit trace_context.
"""
import contextlib
import json
import os
import threading

_client = None
_lock = threading.Lock()


def enabled():
    return bool(os.environ.get("LANGFUSE_BASE_URL") or os.environ.get("LANGFUSE_HOST"))


def client():
    global _client
    if not enabled():
        return None
    with _lock:
        if _client is None:
            from langfuse import Langfuse
            _client = Langfuse(base_url=os.environ.get("LANGFUSE_BASE_URL") or os.environ.get("LANGFUSE_HOST"),
                               public_key=os.environ.get("LANGFUSE_PUBLIC_KEY", "pk-lf-proxy-injected"),
                               secret_key=os.environ.get("LANGFUSE_SECRET_KEY", "sk-lf-proxy-injected"),
                               environment=os.environ.get("SIGNALCORE_ENV", "demo"), release="signalcore-2.0")
    return _client


def _clip(x, n=6000):
    s = x if isinstance(x, str) else json.dumps(x, default=str, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + f"… [{len(s) - n} chars truncated]"


class Ctx:
    """Where a child observation should attach: trace id + parent span id."""

    def __init__(self, trace_id=None, span_id=None):
        self.trace_id, self.span_id = trace_id, span_id

    def as_trace_context(self):
        if not self.trace_id:
            return None
        return {"trace_id": self.trace_id, **({"parent_span_id": self.span_id} if self.span_id else {})}


@contextlib.contextmanager
def root(name, *, input=None, metadata=None, tags=None, session_id=None):
    """Root span for a pipeline run, an Ask, or an experiment item. Yields a Ctx (empty when disabled)."""
    lf = client()
    if lf is None:
        yield Ctx()
        return
    from langfuse import propagate_attributes
    with propagate_attributes(trace_name=name, tags=tags or [], session_id=session_id, metadata={k: str(v) for k, v in (metadata or {}).items()}):
        with lf.start_as_current_observation(name=name, as_type="chain", input=input, metadata=metadata) as span:
            ctx = Ctx(span.trace_id, span.id)
            ctx.span = span
            try:
                yield ctx
            finally:
                pass


@contextlib.contextmanager
def child(ctx, name, *, as_type="span", input=None, metadata=None):
    """A child span under ctx, usable from any thread. Yields a Ctx for its own children."""
    lf = client()
    if lf is None or ctx is None or not ctx.trace_id:
        yield Ctx()
        return
    obs = lf.start_observation(trace_context=ctx.as_trace_context(), name=name, as_type=as_type, input=input, metadata=metadata)
    out = Ctx(ctx.trace_id, obs.id)
    out.span = obs
    try:
        yield out
    except Exception as e:
        obs.update(level="ERROR", status_message=f"{type(e).__name__}: {e}"[:500])
        raise
    finally:
        obs.end()


def generation(ctx, *, name, model, params, response, cost_usd, mode):
    """Record one Claude call as a generation. Called after the call returns (replayed calls included)."""
    lf = client()
    if lf is None or ctx is None or not ctx.trace_id:
        return
    u = response.get("usage", {}) or {}
    usage = {"input": int(u.get("input_tokens", 0) or 0), "output": int(u.get("output_tokens", 0) or 0)}
    if u.get("cache_read_input_tokens"):
        usage["cache_read_input_tokens"] = int(u["cache_read_input_tokens"])
    out = []
    for b in response.get("content", []):
        t = b.get("type")
        if t == "text":
            out.append(b.get("text", ""))
        elif t == "tool_use":
            out.append({"tool_use": b.get("name"), "input": b.get("input")})
    g = lf.start_observation(trace_context=ctx.as_trace_context(), name=name, as_type="generation", model=model,
                             input=_clip({"system": params.get("system"), "messages": params.get("messages")}),
                             output=_clip(out), usage_details=usage, cost_details={"total": round(cost_usd, 6)},
                             model_parameters={k: v for k, v in (params.get("output_config") or {}).items() if k == "effort"},
                             metadata={"mode": mode, "stop_reason": response.get("stop_reason"),
                                       "tools": [t.get("name") for t in params.get("tools", [])] or None})
    g.end()


def score(ctx_or_trace, name, value, *, comment=None, data_type=None, metadata=None, observation_id=None):
    lf = client()
    if lf is None:
        return
    trace_id = ctx_or_trace.trace_id if isinstance(ctx_or_trace, Ctx) else ctx_or_trace
    if not trace_id:
        return
    if data_type is None:
        data_type = "BOOLEAN" if isinstance(value, bool) else "CATEGORICAL" if isinstance(value, str) else "NUMERIC"
    if isinstance(value, bool):
        value = 1.0 if value else 0.0
    lf.create_score(name=name, value=value, trace_id=trace_id, observation_id=observation_id, comment=comment,
                    data_type=data_type, metadata=metadata)


def trace_url(ctx):
    lf = client()
    return lf.get_trace_url(trace_id=ctx.trace_id) if lf and ctx and ctx.trace_id else None


def flush():
    if _client is not None:
        _client.flush()
