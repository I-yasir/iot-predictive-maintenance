# PdM-Live developer commands. Python env: `make venv` (needs uv), then `source .venv/bin/activate`.
PY ?= python

.PHONY: venv audit train train-quick evaluate test lint typecheck notebook

venv:
	uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e "ml[dev]"

audit:            ## P1.4 regenerate data/reference/data_audit.json + config/profiles/*.yaml
	$(PY) ml/pipelines/audit.py

train:            ## P1.6-P1.9 grouped CV selection, final fit, versioned bundles (never touches test files)
	$(PY) ml/pipelines/train.py

train-quick:      ## smoke test: one config, no ablations
	$(PY) ml/pipelines/train.py --quick --profiles FD001

evaluate:         ## P1.8 one-time official test evaluation of CURRENT bundles
	$(PY) ml/pipelines/evaluate.py

test:
	cd ml && $(PY) -m pytest

lint:
	cd ml && ruff check . && ruff format --check .

typecheck:
	cd ml && mypy

notebook:
	jupyter lab ml/notebooks/01_data_audit_and_baseline.ipynb

# ---- Phase 2: IoT (needs `pip install -e contracts -e "iot[dev]"` and a filled-in .env)
.PHONY: up down passwd test-iot lint-iot harness replay-demo esp32-profile esp32-build

up:               ## broker + TimescaleDB
	docker compose up -d

down:
	docker compose down

passwd:           ## regenerate config/mosquitto/passwd from .env, then restart the broker
	sh config/mosquitto/make_passwd.sh && docker compose restart mosquitto

test-iot:         ## contract + iot tests (broker tests skip unless `make up` is running)
	cd contracts && $(PY) -m pytest && cd ../iot && $(PY) -m pytest

lint-iot:
	cd contracts && ruff check . && mypy && cd ../iot && ruff check . && mypy

harness:          ## Mode 2 harness against a virtual ESP32 with every fault type
	set -a; . ./.env; set +a; pdm-harness --virtual --count 60 --rate 10 \
	  --faults malformed@10,missing@20,range@30,duplicate@40,out_of_order@45,drop@50:3

replay-demo:      ## Mode 1: replay FD001 test unit 34 at 5 cycles/s
	set -a; . ./.env; set +a; pdm-replay --profile FD001 --split test --units 34 --speed 5

esp32-profile:
	pdm-export-esp32-profile --profile FD001

esp32-build:
	cd iot/esp32 && pio run

# ---- Phase 3: backend (needs `pip install -e contracts -e iot -e "backend[dev]"`, `make up` and a filled-in .env)
.PHONY: backend migrate test-backend lint-backend perf

backend:          ## API + MQTT subscriber on :8000 (migrates the DB on startup)
	set -a; . ./.env; set +a; cd backend && uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000

migrate:          ## alembic upgrade head
	set -a; . ./.env; set +a; cd backend && pdm-backend migrate

test-backend:     ## backend tests (each run creates and drops its own test database)
	set -a; . ./.env; set +a; cd backend && $(PY) -m pytest

lint-backend:
	cd backend && ruff check . && mypy app

perf:             ## P3.9 load test: 500 msg/s, 300 assets, 5 min -> reports/perf_p39.md
	set -a; . ./.env; set +a; $(PY) backend/perf/load_test.py --rate 500 --assets 300 --duration 300
