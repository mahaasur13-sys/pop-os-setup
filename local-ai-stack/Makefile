# Makefile — local-ai-stack deployment commands

.PHONY: help build up down logs restart ps shell clean \
        health ready metrics \
        build-no-cache start-from-scratch

NAME := agent-runtime
COMPOSE := docker compose
ENV_FILE := ./agent-runtime/.env

help:
	@echo "local-ai-stack — deployment commands"
	@echo "====================================="
	@echo "  make build          — build agent-runtime image"
	@echo "  make up             — start full stack"
	@echo "  make down           — stop stack"
	@echo "  make logs           — tail logs (all containers)"
	@echo "  make ps             — show container status"
	@echo "  make health         — liveness check"
	@echo "  make ready          — readiness check (deps)"
	@echo "  make metrics        — scrape metrics endpoint"
	@echo "  make restart        — restart agent-runtime"
	@echo "  make shell          — open shell in container"
	@echo "  make clean          — remove containers + volumes"
	@echo "  make build-no-cache — rebuild without cache"
	@echo "  make start-from-scratch — clean + build + up"

# === Core operations ===

up:
	@echo "Starting local-ai-stack..."
	$(COMPOSE) up -d
	@echo "Waiting for services..."
	@sleep 15 && $(COMPOSE) exec -T redis redis-cli ping
	@echo "Run 'make ps' to see status"

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100

ps:
	$(COMPOSE) ps

restart:
	$(COMPOSE) restart $(NAME)

shell:
	$(COMPOSE) exec $(NAME) /bin/sh

# === Build ===

build:
	$(COMPOSE) build $(NAME)

build-no-cache:
	$(COMPOSE) build --no-cache $(NAME)

start-from-scratch: down clean build up

# === Health & Observability ===

health:
	@curl -sf http://localhost:8050/health && echo "LIVENESS OK" || echo "LIVENESS FAIL"

ready:
	@curl -sf http://localhost:8050/health/ready \
	  && echo "READINESS OK" || echo "READINESS FAIL"

metrics:
	@curl -sf http://localhost:8050/metrics

# === Maintenance ===

clean:
	$(COMPOSE) down -v --remove-orphans
	@echo "Containers + volumes removed"

rebuild: down build up
