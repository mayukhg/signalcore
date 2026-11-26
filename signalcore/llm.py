"""Claude client with three modes.

live   - calls the Anthropic API and records every request/response to the replay cache
replay - answers from the cache only (offline demos; deterministic)
stub   - deterministic local stand-ins (tests and keyless development)

Requests and responses are plain dicts so they can be cached and replayed byte-for-byte.
"""
import hashlib
import json
import os
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "fixtures" / "llm_cache.jsonl"

HEAVY = "claude-opus-5-5"     # reasoning: theme naming, skeptic, PBR, ask
JUDGE = "claude-sonnet-5-5"   # grounding judge, CAB parsing
LIGHT = "claude-haiku-5-5"    # per-item enrichment
PRICE = {HEAVY: (4.0, 20.0), JUDGE: (2.0, 10.0), LIGHT: (0.10, 0.50)}  # $ per 1M tokens (in, out)
FALLBACK_OK = {HEAVY, JUDGE}  # server-side refusal fallbacks (not available for Haiku)


class ReplayMiss(RuntimeError):
    pass


def cost(model, usage):
    pi, po = PRICE.get(model, (4.0, 20.0))
    tin = usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0) * 1.25 + usage.get("cache_read_input_tokens", 0) * 0.1
    return (tin * pi + usage.get("output_tokens", 0) * po) / 1e6


def default_mode():
    m = os.environ.get("SIGNALCORE_MODE")
    if m:
        return m
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "live"
    return "replay" if CACHE.exists() and CACHE.stat().st_size else "stub"


class Meter:
    def __init__(self):
        self.tokens_in = self.tokens_out = self.calls = 0
        self.cost = 0.0
        self.models = set()
        self._lock = threading.Lock()

    def add(self, model, usage):
        with self._lock:
            self.calls += 1
            self.models.add(model)
            self.tokens_in += usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0) + usage.get("cache_creation_input_tokens", 0)
            self.tokens_out += usage.get("output_tokens", 0)
            self.cost += cost(model, usage)


class LLM:
    def __init__(self, mode=None, cache_path=CACHE):
        self.mode = mode or default_mode()
        self.cache_path = Path(cache_path)
        self._lock = threading.Lock()
        self._cache = {}
        if self.cache_path.exists():
            for line in self.cache_path.read_text().splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self._cache[rec["key"]] = rec["response"]
        self._client = None
        if self.mode == "live":
            import anthropic
            self._client = anthropic.Anthropic(max_retries=4, timeout=600)

    @staticmethod
    def key(purpose, params):
        blob = json.dumps({"purpose": purpose, **params}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()[:32]

    def create(self, purpose, meter=None, **params):
        k = self.key(purpose, params)
        if self.mode == "stub":
            from .stubs import respond
            resp = respond(purpose, params)
        elif self.mode == "replay" or (self.mode == "live" and k in self._cache and os.environ.get("SIGNALCORE_REUSE_CACHE", "1") == "1"):
            if k not in self._cache:
                raise ReplayMiss(f"No recorded response for {purpose} ({k}). Run once in live mode to record it.")
            resp = self._cache[k]
        else:
            model = params["model"]
            if model in FALLBACK_OK:
                r = self._client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params)
            else:
                r = self._client.messages.create(**params)
            resp = r.model_dump(mode="json", exclude_none=True)
            with self._lock:
                self._cache[k] = resp
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                with self.cache_path.open("a") as f:
                    f.write(json.dumps({"key": k, "purpose": purpose, "response": resp}, ensure_ascii=False) + "\n")
        if resp.get("stop_reason") == "refusal":
            raise RuntimeError(f"{purpose}: model declined ({resp.get('stop_details')})")
        if meter is not None:
            meter.add(resp.get("model", params["model"]), resp.get("usage", {}))
        return resp

    # ------------------------------------------------------------------ helpers
    def structured(self, purpose, *, model, system, user, schema, effort="medium", max_tokens=16000, meter=None):
        """One call with a JSON-schema output. Returns the parsed object."""
        resp = self.create(purpose, meter=meter, model=model, max_tokens=max_tokens, system=system,
                           messages=[{"role": "user", "content": user}],
                           output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}})
        if resp.get("stop_reason") == "max_tokens":
            raise RuntimeError(f"{purpose}: output hit max_tokens")
        text = next(b["text"] for b in resp["content"] if b.get("type") == "text")
        return json.loads(text)

    def tool_loop(self, purpose, *, model, system, user, tools, execute, finish_tool, effort="high", max_turns=8,
                  max_tokens=16000, meter=None, trace=None):
        """Manual agentic loop. `execute(name, input) -> str`. Ends when the model calls `finish_tool`.
        Returns the finish tool's input dict (or None) and appends tool calls to `trace`."""
        messages = [{"role": "user", "content": user}]
        for turn in range(max_turns):
            resp = self.create(purpose, meter=meter, model=model, max_tokens=max_tokens, system=system, messages=messages,
                               tools=tools, output_config={"effort": effort})
            if resp.get("stop_reason") == "pause_turn":
                messages.append({"role": "assistant", "content": resp["content"]})
                continue
            uses = [b for b in resp["content"] if b.get("type") == "tool_use"]
            messages.append({"role": "assistant", "content": resp["content"]})
            if not uses:
                messages.append({"role": "user", "content": f"Call the {finish_tool} tool now with your result."})
                continue
            results, final = [], None
            for u in uses:
                if u["name"] == finish_tool:
                    final = u["input"]
                    results.append({"type": "tool_result", "tool_use_id": u["id"], "content": "Recorded."})
                    continue
                out = execute(u["name"], u["input"])
                if trace is not None:
                    trace.append({"tool": u["name"], "input": u["input"], "output": out[:4000]})
                results.append({"type": "tool_result", "tool_use_id": u["id"], "content": out})
            if final is not None:
                return final
            messages.append({"role": "user", "content": results})
        return None
