"""LangGraph wiring for the nightly run.

resolve → cab → enrich → cluster → link → triangulate → deps → score → skeptic → rescore → risks → pbr → judge
   judge --(failed claims, < 2 retries)--> pbr_retry → judge
   judge --(ok or out of retries)--> finalize → evals
"""
from typing import TypedDict

from langgraph.graph import END, StateGraph

from . import cluster, evals, intake, pbr, risks, score, skeptic
from .run import Run

MAX_RETRIES = 2


class S(TypedDict, total=False):
    attempt: int
    failed: dict


def build(run: Run):
    ctx = {}

    def n(fn):
        def wrapped(state):
            fn(state)
            return {}
        return wrapped

    g = StateGraph(S)
    g.add_node("resolve", n(lambda s: ctx.__setitem__("resolver", intake.resolve_identities(run))))
    g.add_node("cab", n(lambda s: intake.parse_cab(run, ctx["resolver"])))
    g.add_node("enrich", n(lambda s: intake.enrich(run)))
    g.add_node("cluster", n(lambda s: cluster.cluster_themes(run)))
    g.add_node("link", n(lambda s: cluster.link_records(run)))
    g.add_node("triangulate", n(lambda s: score.triangulate(run)))
    g.add_node("deps", n(lambda s: score.trace_dependencies(run)))
    g.add_node("score", n(lambda s: score.score(run)))
    g.add_node("skeptic", n(lambda s: skeptic.skeptic(run)))
    g.add_node("rescore", n(lambda s: score.score(run, skeptic=run.skeptic)))
    g.add_node("risks", n(lambda s: risks.detect_risks(run)))
    g.add_node("pbr", n(lambda s: pbr.write_pbrs(run)))

    def judge_node(state):
        attempt = state.get("attempt", 1)
        failed = pbr.judge(run, attempt)
        return {"failed": failed, "attempt": attempt}

    def retry_node(state):
        attempt = state["attempt"] + 1
        run.to_judge = set(state["failed"])
        pbr.write_pbrs(run, only=set(state["failed"]), feedback=state["failed"], attempt=attempt)
        return {"attempt": attempt}

    g.add_node("judge", judge_node)
    g.add_node("pbr_retry", retry_node)
    g.add_node("finalize", n(lambda s: pbr.drop_failed(run)))
    g.add_node("evals", n(lambda s: evals.run_evals(run)))

    order = ["resolve", "cab", "enrich", "cluster", "link", "triangulate", "deps", "score", "skeptic", "rescore", "risks", "pbr", "judge"]
    g.set_entry_point(order[0])
    for a, b in zip(order, order[1:]):
        g.add_edge(a, b)
    g.add_conditional_edges("judge", lambda s: "pbr_retry" if s.get("failed") and s.get("attempt", 1) <= MAX_RETRIES else "finalize",
                            {"pbr_retry": "pbr_retry", "finalize": "finalize"})
    g.add_edge("pbr_retry", "judge")
    g.add_edge("finalize", "evals")
    g.add_edge("evals", END)
    return g.compile()


def run_pipeline(db_path=None, llm=None, run_id=None, on_event=None):
    kw = {k: v for k, v in dict(db_path=db_path, llm=llm, run_id=run_id, on_event=on_event).items() if v is not None}
    run = Run(**kw)
    try:
        build(run).invoke({"attempt": 1}, {"recursion_limit": 60})
        run.finish("done")
    except Exception as e:
        run.finish(f"failed: {type(e).__name__}: {e}"[:300])
        raise
    return run.run_id


if __name__ == "__main__":
    import argparse, sys
    from ..llm import LLM
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default=None)
    ap.add_argument("--run-id", default=None)
    a = ap.parse_args()
    rid = run_pipeline(llm=LLM(a.mode), run_id=a.run_id,
                       on_event=lambda e: print(f"  {e['label']} · {e.get('summary') or ''}", file=sys.stderr) if e["type"] == "step_finished" else None)
    print(rid)
