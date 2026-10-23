SHELL := /bin/bash
.DEFAULT_GOAL := help
SUPABASE := npx -y supabase@2.121.0
PY := uv run python
# 8000/5173 are taken by the AuDHS Tutor on this machine; the vite proxy reads TUTOR_API_PORT.
API_PORT ?= 8020
WEB_PORT ?= 5180
# Load local stack URLs/keys (written by `make env`) for every recipe that needs them.
WITH_ENV := set -a && . ./.env.local && set +a && export SUPABASE_DB_URL="$$DB_URL" &&

help: ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-12s %s\n",$$1,$$2}'

env: ## export local Supabase URLs/keys into .env.local + public frontend settings (never commit)
	@$(SUPABASE) status -o env > .env.local 2>/dev/null || { echo "stack not running: make up"; exit 1; }
	@set -a && . ./.env.local && set +a && printf 'VITE_SUPABASE_URL=%s\nVITE_SUPABASE_PUBLISHABLE_KEY=%s\n' \
	  "$$API_URL" "$${PUBLISHABLE_KEY:-$$ANON_KEY}" > frontend/.env.local

seed: ## regenerate supabase/seed.sql from curriculum + labs
	$(PY) scripts/seed.py

up: ## start local stack, apply migrations (RESET=1 for db reset), create lab DB, install default labs
	uv sync -q
	$(SUPABASE) start
	@if [ "$(RESET)" = "1" ]; then $(PY) scripts/seed.py && $(SUPABASE) db reset; fi
	$(MAKE) env
	$(WITH_ENV) $(PY) scripts/lab_db.py
	$(WITH_ENV) $(PY) scripts/lab.py install 01-rls-vs-grant

down: ## stop the stack (PURGE=1 to drop volumes)
	$(SUPABASE) stop $(if $(PURGE),--no-backup,)

reset: ## db reset + lab DB recreate
	$(MAKE) up RESET=1

ingest: env ## fill the corpus from llms.txt (ARGS="--dry-run" etc.)
	$(WITH_ENV) $(PY) scripts/ingest_llms.py $(ARGS)

olist: env ## import the Olist e-commerce dataset into the lab DB (CSV files in data/olist/)
	$(WITH_ENV) $(PY) scripts/import_olist.py
	@$(WITH_ENV) for s in $$(grep -l 'requires:.*olist' labs/*/lab.yaml | xargs -n1 dirname | xargs -n1 basename); do \
	  $(PY) scripts/lab.py install $$s; done

search: env ## query the corpus: make search Q="permission denied 42501"
	$(WITH_ENV) $(PY) scripts/search.py "$(Q)"

turn: env ## one real tutor turn (uses API tokens): make turn Q="Hallo" [ARGS="--mode incident"]
	@test -f .env || { echo "create .env with ANTHROPIC_API_KEY (cp .env.example .env)"; exit 1; }
	$(WITH_ENV) set -a && . ./.env && set +a && $(PY) scripts/tutor_turn.py $(ARGS) "$(Q)"

refresh: ## re-fetch changed docs only (directly, without the backend)
	$(MAKE) ingest

refresh-schedule: env ## weekly docs refresh: Vault URL+token from .env, pg_cron job (CRON="0 3 * * 1" to change)
	$(WITH_ENV) set -a && . ./.env && set +a && $(PY) scripts/refresh_schedule.py install $(if $(CRON),--cron "$(CRON)",)

refresh-now: env ## trigger the refresh through pg_cron's path (pg_net -> backend); backend must be running
	$(WITH_ENV) $(PY) scripts/refresh_schedule.py run-now

refresh-status: env ## scheduled job, last cron runs and refresh runs
	$(WITH_ENV) $(PY) scripts/refresh_schedule.py status

dev: env ## backend :$(API_PORT) + frontend :$(WEB_PORT) (loads .env.local and .env)
	($(WITH_ENV) { [ -f .env ] && set -a && . ./.env && set +a; true; } && \
	  uv run uvicorn backend.main:app --reload --port $(API_PORT) &) && cd frontend && \
	  TUTOR_API_PORT=$(API_PORT) npm run dev -- --port $(WEB_PORT) --strictPort

tts-voices: ## download the Piper voices for server TTS into data/piper (Thorsten high + Ryan high, ~235 MB)
	@{ [ -f .env ] && set -a && . ./.env && set +a; true; } && $(PY) scripts/tts.py download

tts: tts-voices ## run the local Piper TTS server (127.0.0.1:5002); enable with TUTOR_TTS=server in .env
	@{ [ -f .env ] && set -a && . ./.env && set +a; true; } && $(PY) scripts/tts.py serve

tts-demo: ## synthesise three sample lines into data/voice/ (Piper must be running)
	@{ [ -f .env ] && set -a && . ./.env && set +a; true; } && $(PY) scripts/tts.py demo

dev-user: env ## create/sign in the local dev learner (credentials kept in .env); ARGS=--print-token
	@$(WITH_ENV) { [ -f .env ] && set -a && . ./.env && set +a; true; } && $(PY) scripts/dev_user.py $(ARGS)

smoke: env ## stack reachable, schema + seed present, search callable, lab roles + lab 01 ok
	$(WITH_ENV) $(PY) scripts/smoke.py

test-db: ## pgTAP (schema) + lab checks in both directions
	$(SUPABASE) test db
	$(MAKE) test-labs

test-labs: env ## every lab's checks.sql must FAIL on fresh setup and PASS after solution.sql
	@$(WITH_ENV) for d in labs/*/; do s=$$(basename $$d); \
	  $(PY) scripts/lab.py install $$s >/dev/null; rc=$$?; \
	  if [ $$rc -eq 3 ]; then echo "skip $$s (dataset missing: make olist)"; continue; fi; \
	  [ $$rc -eq 0 ] || { echo "FAIL $$s: install failed"; exit 1; }; \
	  if $(PY) scripts/lab.py check $$s >/dev/null; then echo "FAIL $$s: checks pass while broken"; exit 1; fi; \
	  $(PY) scripts/lab.py solve $$s >/dev/null; \
	  $(PY) scripts/lab.py check $$s >/dev/null || { echo "FAIL $$s: checks fail after solution"; exit 1; }; \
	  $(PY) scripts/lab.py install $$s >/dev/null; echo "ok   $$s"; done

lint: ## ruff + mypy
	uv run ruff check . && uv run mypy backend scripts

check: ## lint + all tests (needs the stack running for pgTAP); evals: free retrieval + replayed recordings
	$(MAKE) lint && uv run pytest -q && $(MAKE) test-db && $(MAKE) evals-offline && \
	  cd frontend && npm run -s typecheck && npm run -s test -- --run

evals-offline: env ## retrieval eval (local, enforced) + re-score recorded turns (report only); no API tokens
	@$(WITH_ENV) $(PY) scripts/eval.py --sets retrieval --strict --if-ready | grep -E '^## |Thresholds'
	@$(WITH_ENV) $(PY) scripts/eval.py --sets grounding socratic safety persona incident web session explicit --replay --if-ready \
	  | grep -E '^## '

eval-calibrate: env ## judge agreement with labelled turns (reference path = pass); a few judge calls
	$(WITH_ENV) { [ -f .env ] && set -a && . ./.env && set +a; true; } && $(PY) scripts/eval.py --calibrate

evals: env ## full eval suite: 78 live tutor turns + judge, records them (uses API tokens, ~$2-5)
	$(WITH_ENV) { [ -f .env ] && set -a && . ./.env && set +a; true; } && \
	  $(PY) scripts/eval.py --all --record --judge --strict

.PHONY: help env seed up down reset olist dev-user ingest search turn refresh refresh-schedule refresh-now refresh-status dev smoke test-db test-labs lint check evals evals-offline eval-calibrate
