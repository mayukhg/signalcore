PY ?= .venv/bin/python
.PHONY: setup data run record demo test standalone deck clean lf-sync lf-eval lf-eval-live

setup:            ## create venv and install dependencies
	python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt

data:             ## regenerate the synthetic tenant (deterministic)
	$(PY) -m signalcore.data.generate

run:              ## run the pipeline (live if ANTHROPIC_API_KEY or SIGNALCORE_ANTHROPIC_API_KEY is set, else replay, else stub)
	$(PY) -m signalcore.pipeline.graph

record:           ## live run that records every model call to fixtures/llm_cache.jsonl
	SIGNALCORE_MODE=live $(PY) -m signalcore.pipeline.graph

demo: setup       ## one command: data + latest run + web app on http://localhost:8000
	@test -f data/signalcore.db || $(PY) -m signalcore.data.generate
	.venv/bin/uvicorn signalcore.api:app --port 8000

test:
	SIGNALCORE_MODE=stub $(PY) -m pytest -q tests

standalone:       ## single-file HTML with the latest run embedded
	$(PY) -m signalcore.export

deck:            ## single-file HTML pitch deck (slides + screenshots embedded)
	$(PY) deck/build_standalone.py

LF ?= https://us.cloud.langfuse.com
lf-sync:          ## create/refresh Langfuse datasets (planted themes, Ask golden set, judge calibration)
	LANGFUSE_BASE_URL=$(LF) $(PY) -m signalcore.evaluation.experiments sync

lf-eval:          ## no model cost: score the latest pipeline run against planted ground truth in Langfuse
	LANGFUSE_BASE_URL=$(LF) $(PY) -m signalcore.evaluation.experiments run --suite planted

lf-eval-live:     ## live Claude: Ask golden set (code + LLM-judge scores) and Grounding Judge calibration
	LANGFUSE_BASE_URL=$(LF) SIGNALCORE_MODE=live $(PY) -m signalcore.evaluation.experiments run --suite all --mode live

clean:
	rm -f data/signalcore.db
