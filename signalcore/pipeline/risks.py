"""Portfolio risk detection (deterministic): one ranked feed with Cost of Delay impact and an owner."""
import json


def detect_risks(run):
    with run.step("risks", "Portfolio risk detection") as s:
        sc, rid, rows = run.scores, 0, []
        titles = dict(run.q("SELECT theme_id, title FROM themes WHERE run_id=?", run.run_id))
        module = dict(run.q("SELECT theme_id, module_id FROM themes WHERE run_id=?", run.run_id))
        team = {r[0]: r[1] for r in run.q("SELECT module_id, name FROM modules")}

        def add(kind, sev, title, detail, cod, tid=None, mod=None, owner=None, cites=()):
            nonlocal rid
            rid += 1
            rows.append((run.run_id, f"R{rid:02d}", kind, sev, title, detail, cod, tid, mod or module.get(tid), owner, json.dumps(list(cites))))

        for tid, o in sc.items():
            m = run.metrics[tid]
            if o["archetype"] == "silent_churn":
                add("silent_churn", "high", f"Silent churn: {titles[tid]}",
                    f"Usage fell {m['decline']:.0%} across {m['cohort']} accounts renewing within 150 days while only {m['n_accounts']} accounts complained.",
                    o["cod_adj"], tid, owner="Product + Customer Success", cites=m["declining"][:8])
            if o["top_share"] > .6 and o["cod"]["total"] > 10000:
                add("concentration", "high" if o["cod"]["total"] > 10000 else "medium", f"Single-account dependency: {titles[tid]}",
                    f"{o['top_share']:.0%} of the dollars behind this theme come from {o['top_account']}.", o["cod_adj"], tid, owner="Product leadership")
        gl = {r[0]: r[1] for r in run.q("SELECT item_id, theme_id FROM gpl_links WHERE run_id=?", run.run_id)}
        for item, title, status, cited in run.q("SELECT item_id, title, status, cited_sources FROM roadmap_items"):
            t = gl.get(item)
            if not t or t not in sc: continue
            o = sc[t]
            if status != "proposed" and o["evidence"] < 50:
                add("weak_bet", "high", f"Committed on weak evidence: {item} {title}",
                    f"Status {status}; evidence score {o['evidence']} ({o['archetype'].replace('_', ' ')}). CD3 rank {o['rank']} of {len(sc)}.",
                    o["cod_adj"], t, owner="Product Ops", cites=[item])
            pillars = {"gong": "say", "zendesk": "say", "jira": "say", "idea_portal": "say", "cab": "say", "pendo": "do", "sfdc": "pay"}
            if status == "proposed" and len({pillars.get(c) for c in cited.split(",")}) < 2 and o["evidence"] >= 60:
                add("under_cited", "low", f"Under-cited roadmap item: {item} {title}",
                    f"The PRD cites one pillar, but triangulated evidence scores {o['evidence']}. Attach Do and Pay evidence.", o["cod_adj"], t,
                    owner="Product Ops", cites=[item])
        for k, own, inh, unblocks, cd3 in run.q("SELECT epic_key, own_cod_week, inherited_cod_week, unblocks, cd3 FROM epic_value WHERE run_id=? ORDER BY inherited_cod_week DESC", run.run_id):
            ub = json.loads(unblocks)
            e = run.epics[k]
            if inh > 20000 and e["status"] == "not_started" and len(ub) >= 2:
                add("dependency", "high", f"Dependency bottleneck: {k} {e['title']}",
                    f"Not started; {e['weeks']:.0f} weeks of work in {e['team']} blocks {len(ub)} epics ({', '.join(ub)}). "
                    f"Delay cost flowing through it: ${inh:,.0f}/week.", inh, mod=e["module"], owner=f"{e['team']} lead", cites=[k] + ub)
        fte = {r[0]: r[1] for r in run.q("SELECT module_id, eng_fte FROM capability_investments WHERE quarter='2026-Q4'")}
        dem = {}
        for tid, o in sc.items(): dem[module.get(tid)] = dem.get(module.get(tid), 0) + o["cod_adj"]
        tf, td = sum(fte.values()), sum(dem.values()) or 1
        for mod, f in fte.items():
            share_f, share_d = f / tf, dem.get(mod, 0) / td
            if share_f > .08 and share_d < share_f * .4:
                add("capital", "medium", f"Capacity ahead of evidence: {team[mod]}",
                    f"{share_f:.0%} of engineering FTE against {share_d:.0%} of confidence-adjusted Cost of Delay.", 0, mod=mod, owner="VP Engineering")
        order = {"high": 0, "medium": 1, "low": 2}
        rows.sort(key=lambda r: (order[r[3]], -(r[6] or 0)))
        rows = [(r[0], f"R{i + 1:02d}") + r[2:] for i, r in enumerate(rows)]
        run.db.executemany("INSERT OR REPLACE INTO risks VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        run.db.commit()
        kinds = {}
        for r in rows: kinds[r[2]] = kinds.get(r[2], 0) + 1
        s.detail = {"summary": f"{len(rows)} portfolio risks detected", "kinds": kinds}
