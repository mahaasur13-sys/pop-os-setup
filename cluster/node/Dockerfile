FROM python:3.11-slim

WORKDIR /app

# ── Runtime deps ─────────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    netcat \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

# ── Python deps ──────────────────────────────────────────────────────────────
RUN pip install --no-cache-dir \
    grpcio==1.60.0 \
    grpcio-tools==1.60.0 \
    protobuf==4.25.2

# ── Copy project sources ─────────────────────────────────────────────────────
COPY cluster/    ./cluster/
COPY proto/      ./proto/
COPY sbs/       ./sbs/
COPY drl/       ./drl/
COPY rpc/       ./rpc/

# ── Build protobufs ───────────────────────────────────────────────────────────
RUN python -m grpc_tools.protoc \
    -I/app \
    --python_out=/app \
    --grpc_python_out=/app \
    /app/proto/atom_os.proto

# ── SBS import path fix: 'from atomos.sbs import ...' → ./sbs/ ──────────────
# SBS source files use 'from atomos.sbs import ...' (as in global_invariant_engine.py)
# We create /app/atomos/sbs as a symlink to /app/sbs so both import styles work.
RUN mkdir -p /app/atomos && \
    ln -sfn /app/sbs /app/atomos/sbs

ENV PYTHONPATH=/app

WORKDIR /app

COPY cluster/node/entrypoint.py /entrypoint.py
ENTRYPOINT ["python", "/entrypoint.py"]
