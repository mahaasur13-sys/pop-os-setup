FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY agent-runtime/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install pydantic-settings (already in requirements.txt, kept for clarity)
# COPY ensures it's installed via requirements.txt above

# Copy app
COPY agent-runtime/ .

# Non-root user for security
RUN useradd -m -u 1000 agent && chown -R agent:agent /app
USER agent

EXPOSE 8050

# Health check
HEALTHCHECK --interval=20s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8050/health || exit 1

CMD ["uvicorn", "agent_runtime.app:app", "--host", "0.0.0.0", "--port", "8050"]
