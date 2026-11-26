# Handoff: remaining steps (for the next session)

State: branch `v2-working-app`. Data generator, full LangGraph pipeline, FastAPI app, 10-view UI, tests (7 passing in stub mode) and standalone export are done. Nothing has run against the live Claude API yet.

Needs `ANTHROPIC_API_KEY` set as an environment variable in the cloud environment.

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
