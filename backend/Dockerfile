# PdM-Live backend image (docs/04 §1, §4). Build context = repository root:
#   docker compose build backend
# The models need torch for the FD002/FD004 sequence model; the CPU wheel keeps the image ~1.5 GB smaller.
# If download.pytorch.org is blocked, build with --build-arg TORCH_INDEX_URL=https://pypi.org/simple
FROM python:3.12.16-slim

ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PDM_ROOT=/app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 pdm
WORKDIR /app

RUN pip install torch==2.7.1 --index-url "${TORCH_INDEX_URL}"
# dependencies first (cached layer), then the code
COPY contracts/pyproject.toml contracts/
COPY ml/pyproject.toml ml/
COPY iot/pyproject.toml iot/
COPY backend/pyproject.toml backend/
COPY contracts/pdm_contracts contracts/pdm_contracts
COPY ml/pdm_ml ml/pdm_ml
COPY iot/pdm_iot iot/pdm_iot
COPY backend/app backend/app
RUN pip install -e contracts -e ml -e iot -e backend

# runtime data: model bundles, evaluation reports, profiles/alert config, C-MAPSS (for replay), contracts
COPY ml/artifacts ml/artifacts
COPY ml/reports ml/reports
COPY config config
COPY data/raw/cmapss data/raw/cmapss
COPY data/reference data/reference
COPY iot/contracts iot/contracts

USER pdm
WORKDIR /app/backend
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=120s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz').status == 200 else 1)"
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
