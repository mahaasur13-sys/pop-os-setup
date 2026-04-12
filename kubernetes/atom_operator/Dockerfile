FROM python:3.11-slim

WORKDIR /app

# OS-level deps for kubectl / kubernetes client
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install kubectl
RUN curl -fsSL -o /usr/local/bin/kubectl \
    https://dl.k8s.io/release/v1.29.0/bin/linux/amd64/kubectl \
    && chmod +x /usr/local/bin/kubectl

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy operator source (after package install to cache layers)
COPY . .

# Entrypoint — operator binary
ENTRYPOINT ["python", "-m", "operator.main"]
