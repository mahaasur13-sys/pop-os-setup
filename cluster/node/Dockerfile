FROM python:3.11-slim

WORKDIR /app

COPY cluster/shared /app/shared
COPY atomos /app/atomos

RUN pip install --no-cache-dir asyncio grpcio grpcio-tools pyyaml

CMD ["python", "/app/node/entrypoint.py"]
