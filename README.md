# SignalCore

**Feedback tools tell you what customers said. SignalCore tells you whether to believe it, and what waiting costs.**

SignalCore is an AI workflow engine for Product Ops. It replaces three grinds that waste senior PM time:

| The grind | Engine (LangGraph + Claude) | Output |
|---|---|---|
| Manual Pendo data collation | Triangulation: SQL joins of telemetry and revenue onto each theme | Evidence synthesis: themes, Evidence Score, cited quotes |
| Tracing cross-portfolio Jira dependencies | Dependency Tracer: follows "blocks" links, critical-path weeks, inherited Cost of Delay | Portfolio risk detection |
| Parsing CAB notes and crafting PBRs | CAB Agent, PBR Agent, Grounding Judge | Grounded Product Business Reviews |

Prioritisation uses **Cost of Delay**. Each theme's CoD per week is discounted by its **Evidence Score** (confidence from Say, Do and Pay triangulation plus a Skeptic Agent), then divided by the weeks to deliver, including weeks blocked by other teams. That gives **CD3**, and the backlog is ranked by it.

Everything runs on a deterministic synthetic tenant ("Keystone Directory", a fictional identity, device and AI-agent access platform) with ground truth planted for evals.

## Quick start

```bash
make demo            # venv + deps + data + latest run + app on http://localhost:8000
```

| Command | What it does |
|---|---|
| `make data` | Regenerate the synthetic tenant (seed 42) |
| `make record` | Live pipeline run with Claude; records every call to `fixtures/llm_cache.jsonl` (needs `ANTHROPIC_API_KEY`, or `SIGNALCORE_ANTHROPIC_API_KEY` as a fallback) |
| `make run` | Run the pipeline: live if a key is set, else replay the recorded calls, else stub |
| `make test` | Tests in stub mode (no key, no network) |
| `make standalone` | `signalcore-standalone.html`: the whole app in one file with the latest run embedded |

### Modes
- **live**: calls the Anthropic API with `ANTHROPIC_API_KEY`, or `SIGNALCORE_ANTHROPIC_API_KEY` if that is unset (some cloud environments withhold `ANTHROPIC_API_KEY` from sessions) (Opus 5.5 for reasoning, Sonnet 5.5 for judging and CAB parsing, Haiku 5.5 for per-item enrichment).
- **replay**: answers from the recorded cache, offline and deterministic. Good for demos without wifi.
- **stub**: local stand-ins for tests; numbers are real, wording is placeholder.

## Pipeline

```
resolve → cab → enrich → cluster → link → triangulate → deps → score → skeptic → rescore → risks → pbr → judge ⟲ (≤2 retries) → evals
```

| Node | Kind | What it does |
|---|---|---|
| Identity resolver | code | Messy reporter emails and company names → accounts (contact email, domain, alias domain, fuzzy name) |
| CAB Agent | Claude Sonnet | Extracts pains, asks, praise and commitments from CAB meeting notes, with line numbers |
| Enrichment | Claude Haiku, batched | Product feedback?, urgency, sentiment, workaround, persona |
| Cluster Agent | TF-IDF + clustering, Claude Opus | Clusters, then names, merges and maps themes to features |
| Triangulation | code (SQL) | Abandonment vs non-complainers, renewal-cohort usage decline, linked deals and ARR |
| Dependency Tracer | code | Theme → Jira epic → unfinished blockers, critical-path weeks; blockers inherit downstream CoD |
| Scoring | code | Evidence Score, pattern, Cost of Delay, CD3, urgency profile |
| Skeptic Agent | Claude Opus + read-only SQL | Tries to refute each theme; may only lower confidence, with cited rows |
| Risk detection | code | Silent churn, concentration, weak bets, under-cited PRDs, dependency bottlenecks, capital misallocation |
| PBR Agent | Claude Opus | Product Business Reviews from a fixed fact table; every claim cites facts |
| Grounding Judge | code + Claude Sonnet | Numbers checked in code, meaning checked by a model; failures rewritten or dropped |
| Ask | Claude Opus + SQL + retrieval | RAG over verbatims and CAB statements, with SQL for numbers |

Agents query through a read-only, allow-listed SQLite connection: writes, multiple statements and ground-truth (`gt_*`) columns are refused.

## Layout

```
schema.sql                  31 tables: pillars, Jira, CAB, and everything the agents write
signalcore/data/            deterministic generator (text.py builds messy feedback; delivery.py builds Jira + CAB notes)
signalcore/pipeline/        LangGraph nodes (intake, cluster, score, skeptic, risks, pbr, evals, graph)
signalcore/llm.py           Claude client with live / replay / stub modes and cost metering
signalcore/ask.py           RAG agent
signalcore/api.py           FastAPI app
web/                        single-page UI (no build step)
tests/                      end-to-end and unit tests
deck/project/               pitch deck source
```
