"""Cluster Agent: local TF-IDF embeddings + clustering, then Claude names, merges and maps themes.
Also links CRM deal notes and roadmap items to the discovered themes by text similarity."""
import json

import numpy as np
from scipy.sparse import hstack
from sklearn.cluster import AgglomerativeClustering
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from ..llm import HEAVY
from .intake import clean

MIN_SIZE = 5


class TextSpace:
    """Word + character n-gram TF-IDF reduced with SVD; robust to typos."""

    def __init__(self, texts, dims=96, seed=0):
        self.w = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True, stop_words="english")
        self.c = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=3, sublinear_tf=True, max_features=30000)
        X = hstack([self.w.fit_transform(texts), self.c.fit_transform(texts) * .6]).tocsr()
        self.svd = TruncatedSVD(n_components=min(dims, X.shape[1] - 1), random_state=seed)
        self.X = normalize(self.svd.fit_transform(X))

    def embed(self, texts):
        X = hstack([self.w.transform(texts), self.c.transform(texts) * .6]).tocsr()
        return normalize(self.svd.transform(X))


NAME_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["clusters"], "properties": {"clusters": {"type": "array", "items": {
    "type": "object", "additionalProperties": False,
    "required": ["cluster_id", "coherent", "merge_into", "title", "problem_statement", "feature_key"],
    "properties": {"cluster_id": {"type": "integer"}, "coherent": {"type": "boolean"}, "merge_into": {"type": "integer"},
                   "title": {"type": "string"}, "problem_statement": {"type": "string"}, "feature_key": {"type": "string"}}}}}}
NAME_SYSTEM = """You are the Cluster Agent in a product-evidence pipeline for a B2B identity, device and AI-agent access platform.
You receive machine-made clusters of customer feedback (sample texts and keywords). For each cluster:
- coherent: false if the samples describe unrelated problems or are not product feedback.
- merge_into: the cluster_id of another cluster describing the SAME underlying problem, or -1. Only merge true duplicates.
- title: 3-6 words naming the problem from the customer's point of view.
- problem_statement: one sentence: who is blocked, what fails, and the consequence.
- feature_key: the single best-matching feature key from the list provided.
Be literal: name what customers describe, not solutions."""


def cluster_themes(run):
    with run.step("cluster", "Cluster Agent · embed, cluster, name themes") as s:
        rows = run.q("""SELECT e.feedback_id, COALESCE(f.body, c.text) FROM feedback_enrichment e
                        LEFT JOIN qualitative_feedback f ON f.feedback_id = e.feedback_id
                        LEFT JOIN cab_items c ON c.item_id = e.feedback_id AND c.run_id = e.run_id
                        WHERE e.run_id = ? AND e.is_product_feedback = 1 ORDER BY e.feedback_id""", run.run_id)
        ids = [r[0] for r in rows]
        texts = [clean(r[1]) for r in rows]
        space = TextSpace(texts)
        labels = AgglomerativeClustering(n_clusters=None, distance_threshold=.88, metric="cosine", linkage="average").fit_predict(space.X)
        clusters = {}
        for i, l in enumerate(labels):
            clusters.setdefault(int(l), []).append(i)
        big = {k: v for k, v in clusters.items() if len(v) >= MIN_SIZE}
        # keywords per cluster
        vocab = np.array(space.w.get_feature_names_out())
        W = space.w.transform(texts)
        feats = run.q("SELECT feature_key, name FROM features")
        payload = []
        for k, idx in sorted(big.items(), key=lambda kv: -len(kv[1])):
            cent = np.asarray(W[idx].mean(axis=0)).ravel()
            kw = list(vocab[cent.argsort()[::-1][:10]])
            sims = space.X[idx] @ normalize(space.X[idx].mean(axis=0, keepdims=True)).T
            order = [idx[j] for j in np.argsort(-sims.ravel())]
            payload.append({"cluster_id": k, "size": len(idx), "keywords": kw, "samples": [texts[j][:260] for j in order[:12]]})
        user = ("Features:\n" + "\n".join(f"- {f}: {n}" for f, n in feats) + "\n\nClusters:\n" +
                "\n".join(json.dumps(p, ensure_ascii=False) for p in payload))
        named = run.llm.structured("name_themes", model=HEAVY, system=NAME_SYSTEM, user=user, schema=NAME_SCHEMA,
                                   effort="medium", meter=s.meter)["clusters"]
        info = {c["cluster_id"]: c for c in named}
        fkeys = {f for f, _ in feats}
        # apply merges, drop incoherent
        root = {}
        for k in big:
            c = info.get(k, {})
            m = c.get("merge_into", -1)
            root[k] = m if (m in big and m != k and info.get(m, {}).get("coherent", True)) else k
        groups = {}
        for k in big:
            if not info.get(k, {}).get("coherent", True):
                continue
            r = root[k]
            while root.get(r, r) != r: r = root[r]
            groups.setdefault(r, []).extend(big[k])
        ordered = sorted(groups.items(), key=lambda kv: -len(kv[1]))
        theme_of, centroids, theme_rows = {}, {}, []
        mod = dict(run.q("SELECT feature_key, module_id FROM features"))
        for n, (k, idx) in enumerate(ordered, 1):
            tid = f"TH-{n:02d}"
            c = info[k]
            fk = c["feature_key"] if c["feature_key"] in fkeys else None
            centroids[tid] = normalize(space.X[idx].mean(axis=0, keepdims=True))
            kw = next(p["keywords"] for p in payload if p["cluster_id"] == k)
            theme_rows.append((run.run_id, tid, c["title"], c["problem_statement"], mod.get(fk), fk, ", ".join(kw[:8]), len(idx)))
            for j in idx: theme_of[ids[j]] = tid
        # items outside big clusters: attach if close to a theme centroid
        T = list(centroids)
        C = np.vstack([centroids[t] for t in T]) if T else np.zeros((0, space.X.shape[1]))
        attached = 0
        for j, fid in enumerate(ids):
            if fid in theme_of or not T: continue
            sims = C @ space.X[j]
            b = int(sims.argmax())
            if sims[b] > .62:
                theme_of[fid] = T[b]; attached += 1
        run.db.executemany("INSERT OR REPLACE INTO themes VALUES (?,?,?,?,?,?,?,?)", theme_rows)
        run.db.executemany("UPDATE feedback_enrichment SET cluster_id=?, theme_id=? WHERE run_id=? AND feedback_id=?",
                           [(int(labels[j]), theme_of.get(fid), run.run_id, fid) for j, fid in enumerate(ids)])
        run.db.commit()
        run.space, run.centroids = space, centroids
        s.detail = {"summary": f"{len(texts)} product items → {len(clusters)} raw clusters → {len(theme_rows)} themes "
                               f"({len(big)} kept, {sum(1 for c in named if c['merge_into'] >= 0)} merged, "
                               f"{sum(1 for c in named if not c['coherent'])} incoherent)",
                    "themes": [{"id": r[1], "title": r[2], "size": r[7], "feature": r[5]} for r in theme_rows],
                    "unclustered": len(ids) - len(theme_of), "attached_late": attached}


def link_records(run):
    """Link deal notes and roadmap items to themes (text similarity + feature match)."""
    with run.step("link", "Triangulation · link deals and roadmap items to themes") as s:
        themes = run.q("SELECT theme_id, title, problem_statement, keywords, feature_key FROM themes WHERE run_id=?", run.run_id)
        T = [t[0] for t in themes]
        C = np.vstack([run.centroids[t] for t in T])
        opps = run.q("SELECT opp_id, COALESCE(notes,'') || ' ' || COALESCE(loss_reason,'') FROM crm_opportunities WHERE notes LIKE 'Gap:%' OR notes LIKE 'AE:%'")
        rows = []
        if opps:
            E = run.space.embed([clean(o[1]) for o in opps])
            S = E @ C.T
            for (oid, _), sims in zip(opps, S):
                b = int(sims.argmax())
                if sims[b] > .25:
                    rows.append((run.run_id, oid, T[b], float(sims[b])))
        run.db.executemany("INSERT OR REPLACE INTO opp_links VALUES (?,?,?,?)", rows)
        feat_theme = {}
        for t in themes:
            if t[4]: feat_theme.setdefault(t[4], t[0])
        epic_feat = dict(run.q("SELECT roadmap_item_id, feature_key FROM jira_epics WHERE roadmap_item_id IS NOT NULL"))
        gpl = run.q("SELECT item_id, title || '. ' || description FROM roadmap_items")
        E = run.space.embed([g[1] for g in gpl])
        S = E @ C.T
        grow = []
        for (gid, _), sims in zip(gpl, S):
            f = epic_feat.get(gid)
            if f in feat_theme:
                grow.append((run.run_id, gid, feat_theme[f], 1.0))
            else:
                b = int(sims.argmax())
                grow.append((run.run_id, gid, T[b] if sims[b] > .2 else None, float(sims[b])))
        run.db.executemany("INSERT OR REPLACE INTO gpl_links VALUES (?,?,?,?)", grow)
        run.db.commit()
        s.detail = {"summary": f"Linked {len(rows)} of {len(opps)} gap-tagged deals and {sum(1 for g in grow if g[2])} of {len(gpl)} roadmap items to themes"}
