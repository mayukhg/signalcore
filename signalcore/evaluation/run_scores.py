"""Push a finished pipeline run's quality signals to its Langfuse trace as scores."""
import json

from .. import observability as obs

EVAL_NAMES = {"cluster_precision", "cluster_recall", "noise_leak", "themes_found", "pattern_recovery", "identity_precision",
              "identity_coverage", "cab_recall", "cab_precision", "deal_link_accuracy", "grounded_first_pass", "grounded_final",
              "bottleneck_found", "run_cost_usd"}


def push_run_scores(db, run_id, ctx):
    if not obs.enabled() or not ctx or not ctx.trace_id:
        return 0
    q = lambda sql, *a: db.execute(sql, a).fetchall()
    n = 0
    for metric, value, detail in q("SELECT metric, value, detail FROM evals WHERE run_id=?", run_id):
        if metric in EVAL_NAMES:
            obs.score(ctx, f"eval.{metric}", float(value), comment=(detail or "")[:500]); n += 1
    for tid, title, pen, arch, ev, notes in q("""SELECT s.theme_id, t.title, s.skeptic_penalty, s.archetype, s.evidence_score, s.skeptic_notes
                                              FROM theme_scores s JOIN themes t USING(run_id, theme_id) WHERE s.run_id=?""", run_id):
        verdict = (json.loads(notes) or {}).get("verdict") if notes else None
        obs.score(ctx, "skeptic.penalty", float(pen), comment=f"{tid} {title}: {verdict or 'n/a'}",
                  metadata={"theme_id": tid, "archetype": arch, "evidence": ev}); n += 1
    weakened = q("SELECT AVG(skeptic_penalty < 1) FROM theme_scores WHERE run_id=?", run_id)[0][0]
    if weakened is not None:
        obs.score(ctx, "skeptic.intervention_rate", float(weakened), comment="Share of themes the Skeptic weakened or refuted"); n += 1
    for status, c in q("SELECT status, COUNT(*) FROM brief_claims WHERE run_id=? GROUP BY status", run_id):
        obs.score(ctx, f"pbr.claims_{status}", float(c)); n += 1
    return n
