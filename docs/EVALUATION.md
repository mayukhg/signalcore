# Evaluation framework (Langfuse)

SignalCore is evaluated at three levels, and everything lands in Langfuse so runs can be compared over time.

| Level | What | Where it runs | Model cost |
|---|---|---|---|
| **Tracing** | Every pipeline run and every Ask is a trace: one span per LangGraph step, one generation per Claude call (model, input, output, tokens, cost) | automatically, when `LANGFUSE_BASE_URL` is set | none extra |
| **Online scores** | Pipeline runs: every ground-truth eval (`eval.*`), a Skeptic penalty per theme (`skeptic.penalty`), Skeptic intervention rate, PBR claim outcomes (`pbr.claims_*`). Each Ask: `ask.citation_validity`, `ask.numbers_grounded`, cost, latency | attached to the trace as it finishes | none (code scorers) |
| **Offline experiments** | Three Langfuse datasets run as experiments, so each change gets a comparable run | `make lf-eval` / `make lf-eval-live` | planted: none · ask and judge: a few dollars |

## Datasets

| Dataset | Items | Expected output | Evaluators |
|---|---|---|---|
| `signalcore-planted-themes` | 12 problems planted in the synthetic tenant | feature key, and pattern for the 5 keyed themes | `theme_found`, `feature_match`, `pattern_match` (code) |
| `signalcore-ask-golden` | 10 questions | required entities and numbers computed from ground truth, plus reference notes | `expected_entities`, `expected_numbers`, `numbers_grounded`, `citation_validity` (code) · `judge_correctness`, `judge_groundedness` (Claude Sonnet as judge) · cost, latency |
| `signalcore-judge-calibration` | 24: real grounded PBR claims plus two perturbed copies each (number changed, causal overclaim) | `grounded: true/false` | `label_correct`, `false_pass` (the dangerous error: the judge approves an unsupported claim) |

Expected outputs come from ground-truth columns the agents never see. Dataset items have stable ids, so `make lf-sync` is idempotent.

## Run it

```bash
make lf-sync        # create/refresh datasets
make lf-eval        # score the latest pipeline run against planted ground truth (no model calls)
make lf-eval-live   # needs SIGNALCORE_ANTHROPIC_API_KEY: golden Ask set + Grounding Judge calibration
```

Set `LF=https://cloud.langfuse.com` for the EU region. Keys come from `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`; in this repo's cloud environment the network proxy injects them, so only the base URL is needed.

## Reading results

- **Regression gate:** compare a new pipeline run's planted-themes experiment against the baseline. Any drop in `avg_pattern_match` or `avg_feature_match` blocks the change.
- **Ask quality:** `avg_expected_entities` and `avg_judge_correctness` track answer quality; `avg_numbers_grounded` under 0.95 means the agent is stating numbers it didn't query.
- **Judge trust:** `avg_false_pass` is the headline. Above 10%, unsupported claims can reach a PBR; tighten the judge prompt or rely more on the code checks.

Baseline (recorded live run `run-20261126-154725`): planted themes found 12/12, feature match 12/12, pattern match 5/5.
