# SignalCore

An AI-powered product evidence layer that triangulates what customers **say** (calls, tickets, ideas),
what they **do** (product telemetry) and what they **pay** (CRM) into an Evidence Score per product theme.

This repo is an interview demo built on fully synthetic data for a fictional identity, device and
AI-agent access platform ("Keystone Directory").

## Contents

| File | What it is |
|---|---|
| `schema.sql` | 13-table schema: three pillars, reference data, agent-written outputs |
| `generate.py` | Deterministic data generator (seed 42) + reference scorer. Writes `signalcore.db` and `app_data.json` |
| `app_data.json` | Scored output consumed by the prototype |
| `prototype.template.html` | UX prototype source (PM Workbench, Executive View, evaluation, schema, pipeline) |
| `build_prototype.py` | Injects `app_data.json` and `schema.sql` into the template |
| `signalcore-prototype.html` | Built, self-contained prototype; open in a browser |
| `deck/project/` | Pitch deck source (slide HTML + CSS) |

## Run

```bash
python3 generate.py          # stdlib only, ~5 s; builds signalcore.db (~40 MB, git-ignored)
python3 build_prototype.py   # rebuilds signalcore-prototype.html
```

Use DuckDB instead of SQLite with `ATTACH 'signalcore.db' (TYPE sqlite);`.

## Scoring

```
evidence = 100 × (0.30·Say + 0.35·Do + 0.35·Pay) × skeptic_penalty
```

Confidence (the score) and pattern (high signal, silent churn, commercial mirage, vocal minority,
emerging) are separate outputs. Twelve themes with known ground truth are planted in the data so
clustering and scoring can be evaluated. The clustering step is simulated with a fixed error rate;
the agent pipeline on the prototype's Agent Pipeline tab is a sketch, not an implementation.
