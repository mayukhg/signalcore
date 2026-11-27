# SignalCore product metrics

SignalCore earns its keep if product teams **make roadmap decisions on triangulated evidence**, and **trust the agents enough to act on them**. The metrics below follow that chain, from usage to decisions to trust to cost. Every metric maps to an event the app sends to Mixpanel (see the event schema at the end).

Users: **PM** (works themes and estimates), **Product Ops** (runs the pipeline, audits the roadmap, produces PBRs), **Executive** (reads the portfolio view and PBRs), **Engineering lead** (dependencies, estimates).

## North star

| Metric | Definition | Why it matters | Target (pilot) |
|---|---|---|---|
| **Evidence-backed decisions per week** | Count of `Decision Recorded`: an estimate override, a PBR export or a board memo copy, each tied to a scored theme | The product exists to change roadmap decisions, not to be looked at | 15+/week across the pilot team |
| **Share of committed roadmap with strong evidence** | `strong_evidence_items ÷ committed_items` on `Roadmap Audited` (evidence ≥ 70) | The outcome leadership cares about: fewer loudest-voice bets | Up 20 points in 90 days |

## 1 · Adoption and engagement

| Metric | Definition | Event |
|---|---|---|
| Weekly active users (WAU), by role | Unique users with `App Opened` per week, broken down by `role` | `App Opened` |
| Stickiness | DAU ÷ WAU | `App Opened` |
| Views per session and view mix | `View Viewed` per user per day, broken down by `view` | `View Viewed` |
| Themes investigated per active user | `Theme Opened` ÷ WAU | `Theme Opened` |
| Week-4 retention | Users who opened the app in their first week and again in week 4 | `App Opened` → `App Opened` |

## 2 · Activation (the "aha" funnel)

`App Opened` → `Theme Opened` → `Evidence Inspected` (opened the Skeptic's checks, cited facts or SQL) → `Decision Recorded` within 7 days.

Watch for drop-off between viewing a theme and inspecting the evidence. That gap means people look at scores without trusting them.

## 3 · Decision quality and outcomes

| Metric | Definition | Event |
|---|---|---|
| Overrides per week, and rank shift | `Estimate Overridden` count; average of `rank_before − rank_after` | `Estimate Overridden` |
| PBRs exported | `PBR Exported` by `doc` | `PBR Exported` |
| Weak bets flagged | Average `weak_bets` per audit | `Roadmap Audited` |
| Cost of Delay surfaced | Average `cod_adj_week_usd` per run (confidence-adjusted CoD the backlog represents) | `Pipeline Run Completed` |
| Silent-churn risks detected | Sum of `silent_churn_risks` per run | `Pipeline Run Completed` |

## 4 · Trust and AI quality

| Metric | Definition | Event | Alert if |
|---|---|---|---|
| Grounding first-pass rate | Average `grounded_first_pass` (claims passing the Grounding Judge on the first draft) | `Pipeline Run Completed` | < 70% |
| Claims dropped per run | Average `claims_dropped` | `Pipeline Run Completed` | rising |
| Skeptic intervention rate | Average `skeptic_weakened ÷ themes` | `Pipeline Run Completed` | > 85% (too harsh) or < 20% (rubber stamp) |
| Cluster precision vs ground truth | Average `cluster_precision` (synthetic tenant only; real tenants use PM relabel rate) | `Pipeline Run Completed` | < 90% |
| Ask answer success rate | `Question Answered` with `success = true` ÷ all | `Question Answered` | < 90% |
| Citations per answer | Average `cited_count` | `Question Answered` | < 2 |

## 5 · Reliability, latency and cost

| Metric | Definition | Event | Alert if |
|---|---|---|---|
| Pipeline success rate | `Pipeline Run Completed` with `status = done` ÷ all | `Pipeline Run Completed` | < 95% |
| Pipeline duration (p50 / p90) | `duration_s` | `Pipeline Run Completed` | p90 > 15 min |
| Cost per run | Average `cost_usd`, live runs only | `Pipeline Run Completed` | > $6 |
| Ask latency (p50 / p90) | `latency_s` | `Question Answered` | p90 > 60 s |
| Cost per question | Average `cost_usd` | `Question Answered` | > $0.40 |

## Event schema

Every event carries `role`, `app_version`, `mode` (live | replay | stub) and, for seeded data, `demo = true`.

| Event | Sent from | Properties |
|---|---|---|
| `App Opened` | web | `view` |
| `View Viewed` | web | `view` |
| `Theme Opened` | web | `theme_id`, `archetype`, `quadrant`, `rank`, `evidence_score`, `cod_week_usd` |
| `Evidence Inspected` | web | `kind` (skeptic_checks, cited_facts, linked_deals, sql), `theme_id` |
| `Estimate Overridden` | server | `theme_id`, `feature_key`, `old_weeks`, `new_weeks`, `rank_before`, `rank_after` |
| `Decision Recorded` | server/web | `kind` (override, pbr_export, memo_copy), `theme_id` |
| `PBR Exported` | web | `doc`, `format` |
| `Question Asked` / `Question Answered` | server | `tool_calls`, `latency_s`, `cost_usd`, `cited_count`, `success` |
| `Pipeline Run Started` / `Pipeline Run Completed` | server | `run_id`, `status`, `duration_s`, `cost_usd`, `themes`, `risks`, `silent_churn_risks`, `skeptic_weakened`, `grounded_first_pass`, `claims_dropped`, `cluster_precision`, `cod_adj_week_usd` |
| `Roadmap Audited` | server | `committed_items`, `strong_evidence_items`, `weak_bets` |
