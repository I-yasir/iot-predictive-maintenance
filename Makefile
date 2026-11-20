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
