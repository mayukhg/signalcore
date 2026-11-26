"""Evals against the ground truth planted by the generator (gt_* columns, cab_gt). Agents never read these."""
import json
from collections import Counter, defaultdict

EXPECT = {"T01": "high_signal", "T02": "high_signal", "T03": "commercial_mirage", "T04": "silent_churn", "T06": "vocal_minority"}


def run_evals(run):
    with run.step("evals", "Evals · score the pipeline against planted ground truth") as s:
        q, rid, out = run.q, run.run_id, {}
        r = q("SELECT AVG(CASE WHEN account_id = gt_account_id THEN 1.0 ELSE 0 END), AVG(account_id IS NOT NULL) FROM qualitative_feedback WHERE account_id IS NOT NULL OR 1")[0]
        prec = q("SELECT AVG(CASE WHEN account_id = gt_account_id THEN 1.0 ELSE 0 END) FROM qualitative_feedback WHERE account_id IS NOT NULL")[0][0]
        out["identity_precision"] = (prec, "Resolved feedback mapped to the right account")
        out["identity_coverage"] = (r[1], "Feedback items resolved to any account")
        # CAB extraction: customer statement lines found
        gt = {(m, l) for m, l in q("SELECT meeting_id, line_no FROM cab_gt")}
        got = {(m, l) for m, l in q("SELECT meeting_id, line_no FROM cab_items WHERE run_id=? AND kind != 'commitment'", rid)}
        out["cab_recall"] = (len(gt & got) / len(gt) if gt else 0, "Customer statements in CAB notes that were extracted")
        out["cab_precision"] = (len(gt & got) / len(got) if got else 0, "Extracted CAB statements that are real customer statements")
        # clustering
        rows = q("""SELECT e.theme_id, f.gt_theme_id FROM feedback_enrichment e JOIN qualitative_feedback f USING(feedback_id)
                    WHERE e.run_id=?""", rid)
        m = defaultdict(Counter)
        for th, g in rows:
            if th: m[th][g] += 1
        maj = {th: c.most_common(1)[0][0] for th, c in m.items()}
        clustered = sum(sum(c.values()) for c in m.values())
        out["cluster_precision"] = (sum(m[t][maj[t]] for t in m) / clustered if clustered else 0, "Clustered items whose planted theme matches their cluster's majority")
        planted = [(th, g) for th, g in rows if g]
        out["cluster_recall"] = (sum(1 for th, g in planted if th and maj.get(th) == g) / len(planted) if planted else 0,
                                 "Planted-theme items that landed in a matching cluster")
        noise = [(th, g) for th, g in rows if not g]
        out["noise_leak"] = (sum(1 for th, g in noise if th) / len(noise) if noise else 0, "Non-product items that leaked into a theme (lower is better)")
        uniq = Counter(v for v in maj.values() if v)
        out["themes_found"] = (len([t for t in uniq]), f"Planted themes recovered (of 12); {sum(1 for v in uniq.values() if v > 1)} split across clusters")
        # deal linking
        lk = q("SELECT l.theme_id, o.gt_theme_id FROM opp_links l JOIN crm_opportunities o USING(opp_id) WHERE l.run_id=?", rid)
        out["deal_link_accuracy"] = (sum(1 for th, g in lk if maj.get(th) == g) / len(lk) if lk else 0, "Gap-tagged deals linked to the right theme")
        # patterns
        arch = {t: a for t, a in q("SELECT theme_id, archetype FROM theme_scores WHERE run_id=?", rid)}
        hits, detail = 0, {}
        for g, want in EXPECT.items():
            ths = [t for t, v in maj.items() if v == g]
            got_a = [arch.get(t) for t in ths]
            ok = want in got_a
            hits += ok
            detail[g] = {"want": want, "got": got_a}
        out["pattern_recovery"] = (hits / len(EXPECT), json.dumps(detail))
        # grounding
        c = dict(q("SELECT status, COUNT(*) FROM brief_claims WHERE run_id=? GROUP BY status", rid))
        # retries overwrite claim rows, so the judge stashes the first-pass rate on the run
        first = getattr(run, "first_pass", None)
        if first is None:
            first = q("SELECT AVG(status='grounded') FROM brief_claims WHERE run_id=? AND attempt=1", rid)[0][0]
        tot = sum(c.values())
        out["grounded_final"] = (c.get("grounded", 0) / tot if tot else 0, f"Claims kept after judging ({c.get('dropped', 0)} dropped)")
        out["grounded_first_pass"] = (first or 0, "Claims grounded on the first draft")
        # dependency: planted bottleneck should carry the most inherited CoD
        top = q("SELECT epic_key FROM epic_value WHERE run_id=? ORDER BY inherited_cod_week DESC LIMIT 1", rid)
        out["bottleneck_found"] = (1.0 if top and top[0][0] == "SSO-88" else 0.0, "Planted bottleneck epic SSO-88 ranked first by inherited Cost of Delay")
        cost = q("SELECT cost_usd, tokens_in, tokens_out FROM agent_runs WHERE run_id=?", rid)[0]
        out["run_cost_usd"] = (cost[0], f"{cost[1]:,} input / {cost[2]:,} output tokens")
        run.db.executemany("INSERT OR REPLACE INTO evals VALUES (?,?,?,?)", [(rid, k, float(v or 0), d) for k, (v, d) in out.items()])
        run.db.commit()
        s.detail = {"summary": f"Clusters {out['cluster_precision'][0]:.0%} precise / {out['cluster_recall'][0]:.0%} recall; "
                               f"patterns {hits}/{len(EXPECT)}; grounded {out['grounded_final'][0]:.0%}"}
