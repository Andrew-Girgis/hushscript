FROM ghcr.io/astral-sh/uv:0.11.7 AS uv
FROM python:3.12-slim-trixie AS runtime
COPY --from=uv /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libseccomp2 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy
COPY --chown=10001:10001 pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY scripts/bootstrap.py scripts/bootstrap.py
ARG BACKEND=cpu
ARG TARGETARCH
RUN uv run --no-sync scripts/bootstrap.py --runtime-only --backend "$BACKEND" \
    --arch "$(case "$TARGETARCH" in arm64) echo aarch64;; *) echo x86_64;; esac)" \
    --runtime-dir /opt/nemo \
    && ln -s /opt/nemo/nemo-speech-* /opt/nemo/current
COPY --chown=10001:10001 hushscript hushscript
ENV PATH="/app/.venv/bin:$PATH" HUSHSCRIPT_RUNTIME=/opt/nemo/current \
    HUSHSCRIPT_MODELS=/models HUSHSCRIPT_DEVICE=cpu HF_HUB_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 DO_NOT_TRACK=1 OTEL_SDK_DISABLED=true \
    CUDA_CACHE_DISABLE=1 OMP_NUM_THREADS=6 HOME=/tmp
USER 10001:10001
EXPOSE 8787
CMD ["python", "-m", "hushscript.server"]

FROM runtime AS test
USER root
RUN uv sync --frozen --group dev
COPY --chown=10001:10001 tests tests
USER 10001:10001
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]

FROM runtime AS benchmark
USER root
RUN uv sync --frozen --extra benchmark --no-dev
COPY --chown=10001:10001 scripts/benchmark.py scripts/benchmark.py
ENV PYTHONPATH=/app \
    LD_LIBRARY_PATH=/app/.venv/lib/python3.12/site-packages/nvidia/cublas/lib:/app/.venv/lib/python3.12/site-packages/nvidia/cudnn/lib:/app/.venv/lib/python3.12/site-packages/nvidia/cuda_nvrtc/lib
USER 10001:10001
CMD ["python", "scripts/benchmark.py", "--engine", "parakeet", "--device", "cpu"]

FROM runtime AS production
