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
    from .. import observability as obs
    from ..evaluation.run_scores import push_run_scores
    with obs.root("signalcore.pipeline", input={"run_id": run.run_id, "mode": run.llm.mode},
                  metadata={"run_id": run.run_id, "mode": run.llm.mode}, tags=["pipeline", run.llm.mode], session_id=run.run_id) as ctx:
        run.trace = ctx
        try:
            build(run).invoke({"attempt": 1}, {"recursion_limit": 60})
            run.finish("done")
        except Exception as e:
            run.finish(f"failed: {type(e).__name__}: {e}"[:300])
            if getattr(ctx, "span", None):
                ctx.span.update(level="ERROR", status_message=str(e)[:500])
            raise
        finally:
            if getattr(ctx, "span", None):
                r = run.db.execute("SELECT status, cost_usd, tokens_in, tokens_out FROM agent_runs WHERE run_id=?", (run.run_id,)).fetchone()
                top = run.db.execute("SELECT theme_id, evidence_score, archetype, ROUND(cd3) FROM theme_scores WHERE run_id=? ORDER BY priority_rank LIMIT 5",
                                     (run.run_id,)).fetchall()
                ctx.span.update(output={"status": r[0], "top_by_cd3": [list(t) for t in top]},
                                metadata={"cost_usd": round(r[1] or 0, 4), "tokens_in": r[2], "tokens_out": r[3]})
                try:
                    push_run_scores(run.db, run.run_id, ctx)
                finally:
                    obs.flush()
    run.trace_url = obs.trace_url(ctx)
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
