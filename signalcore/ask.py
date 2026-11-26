"""Ask the evidence: an agent with two tools, SQL over the pillars and retrieval over verbatims (RAG)."""
import datetime as dt
import json
import time

import numpy as np
from scipy.sparse import hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from .db import connect, readonly, run_readonly_sql
from .llm import HEAVY, LLM, Meter
from .pipeline.intake import clean
from .pipeline.skeptic import SCHEMA_DOC


class Retriever:
    """Hybrid word + character TF-IDF index over feedback text and CAB statements."""

    def __init__(self, db_path, run_id):
        db = connect(db_path)
        rows = db.execute("""SELECT f.feedback_id, f.source, f.source_ref, a.name, a.segment, f.created_at, f.body, e.theme_id
                             FROM qualitative_feedback f LEFT JOIN accounts a ON a.account_id = f.account_id
                             LEFT JOIN feedback_enrichment e ON e.feedback_id = f.feedback_id AND e.run_id = ?""", (run_id,)).fetchall()
        rows += db.execute("""SELECT c.item_id, 'cab_note', c.meeting_id || ' line ' || c.line_no, a.name, a.segment, m.held_on, c.text, e.theme_id
                              FROM cab_items c JOIN cab_meetings m USING(meeting_id) LEFT JOIN accounts a ON a.account_id = c.account_id
                              LEFT JOIN feedback_enrichment e ON e.feedback_id = c.item_id AND e.run_id = c.run_id
                              WHERE c.run_id = ? AND c.kind != 'commitment'""", (run_id,)).fetchall()
        db.close()
        self.rows = [dict(id=r[0], source=r[1], ref=r[2], account=r[3], segment=r[4], date=(r[5] or "")[:10], text=clean(r[6]), theme_id=r[7]) for r in rows]
        texts = [r["text"] for r in self.rows]
        self.w = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english", min_df=1)
        self.c = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=2, max_features=40000)
        self.X = normalize(hstack([self.w.fit_transform(texts), self.c.fit_transform(texts) * .5]).tocsr())

    def search(self, query, k=8, source=None, segment=None):
        v = normalize(hstack([self.w.transform([query]), self.c.transform([query]) * .5]).tocsr())
        sims = (self.X @ v.T).toarray().ravel()
        out = []
        for i in np.argsort(-sims):
            r = self.rows[i]
            if source and r["source"] != source: continue
            if segment and r["segment"] != segment: continue
            out.append({**r, "text": r["text"][:400], "score": round(float(sims[i]), 3)})
            if len(out) >= k: break
        return out


SYSTEM = f"""You answer product leaders' questions about customer evidence for Keystone Directory, a B2B identity, device and AI-agent access platform.
You have two tools: run_sql (numbers from CRM, telemetry, themes, scores) and search_evidence (verbatim customer quotes from calls, tickets, ideas and CAB notes).
Use SQL for anything countable and search_evidence for what customers actually said; most good answers use both.
Then call final_answer with a short answer (3-6 sentences or a compact list). Every number must come from a query you ran.
Cite verbatims inline by id like [FB-00123] or [CAB-M02-L14] and list every cited id in cited_ids. If the data can't answer the question, say so.

{SCHEMA_DOC}"""

TOOLS = [
    {"name": "run_sql", "description": "Run one read-only SELECT (max 200 rows).",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["sql"], "properties": {"sql": {"type": "string"}}}, "strict": True},
    {"name": "search_evidence", "description": "Semantic search over customer verbatims. Optional filters: source (gong, zendesk, jira, idea_portal, cab, cab_note) and segment (SMB, Mid-Market, Enterprise); use empty strings for no filter.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["query", "k", "source", "segment"],
                      "properties": {"query": {"type": "string"}, "k": {"type": "integer"}, "source": {"type": "string"}, "segment": {"type": "string"}}}, "strict": True},
    {"name": "final_answer", "description": "Return the final answer. Call exactly once.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["answer", "cited_ids"],
                      "properties": {"answer": {"type": "string"}, "cited_ids": {"type": "array", "items": {"type": "string"}}}}, "strict": True},
]


def ask(question, db_path, run_id, llm: LLM, retriever: Retriever):
    conn = readonly(db_path, run_id)
    trace, meter, t0 = [], Meter(), time.time()

    def execute(name, inp):
        if name == "run_sql":
            return json.dumps(run_readonly_sql(conn, inp["sql"]), default=str)[:12000]
        if name == "search_evidence":
            res = retriever.search(inp["query"], k=max(1, min(15, inp.get("k") or 8)), source=inp.get("source") or None, segment=inp.get("segment") or None)
            return json.dumps(res, ensure_ascii=False)
        return "Unknown tool"

    final = llm.tool_loop("ask", model=HEAVY, system=SYSTEM, user=question, tools=TOOLS, execute=execute,
                          finish_tool="final_answer", effort="medium", max_turns=8, meter=meter, trace=trace)
    conn.close()
    final = final or {"answer": "I couldn't finish this one within the step limit. Try a narrower question.", "cited_ids": []}
    quotes = {}
    for t in trace:
        if t["tool"] == "search_evidence":
            try:
                for r in json.loads(t["output"]): quotes[r["id"]] = r
            except json.JSONDecodeError:
                pass
    cited = [quotes[i] for i in final["cited_ids"] if i in quotes] or list(quotes.values())[:5]
    steps = []
    for t in trace:
        if t["tool"] == "run_sql":
            try: res = json.loads(t["output"])
            except json.JSONDecodeError: res = {"error": "truncated output"}
            steps.append({"tool": "run_sql", "sql": t["input"]["sql"], "result": res})
        else:
            steps.append({"tool": "search_evidence", "query": t["input"]["query"], "hits": len(json.loads(t["output"])) if t["output"].startswith("[") else 0})
    out = {"question": question, "answer": final["answer"], "cited": cited, "steps": steps, "mode": llm.mode,
           "cost_usd": round(meter.cost, 4), "seconds": round(time.time() - t0, 1)}
    db = connect(db_path)
    db.execute("INSERT INTO ask_log (asked_at, question, answer, sql, rows, cost_usd) VALUES (?,?,?,?,?,?)",
               (dt.datetime.now().isoformat(timespec="seconds"), question, json.dumps(out, default=str), None, None, out["cost_usd"]))
    db.commit(); db.close()
    return out
