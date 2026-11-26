# Handoff: remaining steps (for the next session)

State: branch `v2-working-app`. Data generator, full LangGraph pipeline, FastAPI app, 10-view UI, tests (7 passing in stub mode) and standalone export are done. Nothing has run against the live Claude API yet.

Needs a Claude API key: `ANTHROPIC_API_KEY`, or `SIGNALCORE_ANTHROPIC_API_KEY` if that is unset. The cloud environment withholds `ANTHROPIC_API_KEY` from sessions, so the key is provided as `SIGNALCORE_ANTHROPIC_API_KEY`; `signalcore/llm.py` (`api_key()`) reads either and passes it explicitly to the Anthropic client.

## Status (2026-11-26, second session): steps 1-6 done

- **Live run** `run-20261126-154725`: $2.90, 473K input / 220K output tokens, under 4 minutes. Evals: cluster precision 99% / recall 98%, 12/12 planted themes found, patterns 5/5, CAB recall and precision 100%, deal linking 100%, SSO-88 bottleneck found, PBR claims grounded 81% first pass / 91% kept.
- **Fixes made after the first live run** (which scored patterns 3/5):
  - Cluster prompt now asks for the most specific feature, or `none`, instead of forcing `user_lifecycle`.
  - Silent churn also fires when usage falls across at least twice as many accounts as complain.
  - The first-pass grounding eval was always 0, because retries overwrote claim rows.
  - Ask: documented the roadmap, Jira and dependency columns; quotes are captured before trace truncation (this fixed a JSONDecodeError); 12 turns; `gpl_links` is readable through `v_gpl_links`.
  - `Run.q` is serialized. Agent threads shared one sqlite connection and sometimes got empty results on bootstrap.
  - Ask answers render markdown (tables, bold, lists).
- **Replay cache** `fixtures/llm_cache.jsonl`: 167 entries (pipeline plus the 4 suggested Ask questions). It was pruned to the calls replay actually uses. A fresh clone with no key bootstraps in replay mode and answers all 4 questions offline (verified twice).
- **Screenshots** are in `deck/screenshots/` (2880x1800). The deck artifact https://claude.ai/artifact/3cEoEoz9KqGbN8Pt5anvB5 was revised to 21 slides: it leads with the skeptic, uses the "your org" framing, adds Cost of Delay / CD3, the matrix, Grind → engine → Outputs and "real vs simulated", and uses live numbers. Its source is mirrored in `deck/project/`.
- **Prototype artifact** https://claude.ai/artifact/HviD4VrrJqn67kjbMPWmDs now serves `signalcore-standalone.html` from the live run.

Open items: the deck still has placeholders `[Your name]`, `[repo link]`, `[your email]` and the pilot success metric `[__]%`. Both artifacts are private until shared from the Share menu.

## Original steps

Status (2026-11-26): the Default environment has an `ANTHROPIC_API_KEY` variable, but the container this session ran in started before it was added, so the key was not visible. Start a **new session** so the variable loads. Network secrets cannot be used for api.anthropic.com. On a fresh clone, `make setup`, `make data` (fixed: the generator now creates `data/`) and `make test` (7 passed) all work.

1. `make setup && make data && make record`. This is the first live run.
   - Watch for API errors in the live path of `signalcore/llm.py`: beta `fallbacks="default"` with server-side-fallback-2026-07-01 on Opus/Sonnet, `output_config.format` JSON schemas, strict tools in `skeptic.py` and `ask.py`, and echoing assistant content (including thinking blocks) back in `LLM.tool_loop`.
   - Check evals in the app (Run & evals tab) and fix prompts if themes or patterns regress.
2. Record 4 Ask answers through the API (`POST /api/ask`) using the suggested questions in `web/app.js` (`DEFAULT_Q`), so replay mode and the standalone file can show them.
3. Commit `fixtures/llm_cache.jsonl` (the replay cache) so `make demo` works without a key.
4. Screenshots at deviceScaleFactor 2 of: prioritize (matrix + detail), dependencies, cab, pbr, run (trace + evals), ask (with an answer). Upload them as assets to the deck artifact https://claude.ai/artifact/3cEoEoz9KqGbN8Pt5anvB5 and revise the deck:
   - Lead with the skeptic.
   - Frame it as "how I'd run prioritisation in your org".
   - Add Cost of Delay / CD3 and the Evidence × CoD matrix.
   - Use the "The Grind → engine → Outputs" framing.
   - Add an honest "what's real vs simulated" slide.
   - Use real numbers from the live run.
5. `make standalone`, then publish `signalcore-standalone.html` to the prototype artifact https://claude.ai/artifact/HviD4VrrJqn67kjbMPWmDs.
6. Push the branch, and give the user the artifact link plus `make demo` instructions.
