# Wind Forecast Decision Portal - developer shortcuts.
#
# Every target is a thin wrapper around a command you can also run by hand.
# The interpreter is the repo venv when one exists, otherwise `python`.
# Override it explicitly with:  make test PY=python3.12

VENV    := $(firstword $(wildcard $(CURDIR)/.venv/Scripts/python.exe $(CURDIR)/.venv/bin/python))
PY      ?= $(if $(VENV),$(VENV),python)
COMPOSE ?= docker compose
ARGS    ?=

.DEFAULT_GOAL := help
.PHONY: help up down dev test lint fetch-data

help: ## Show the available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up: ## Build and start the whole stack (API :8000, UI :8080)
	$(COMPOSE) up --build

down: ## Stop the stack and remove its containers and network
	$(COMPOSE) down

dev: ## Run the API with reload and the Vite dev server side by side
	@echo "API -> http://localhost:8000/api/docs"
	@echo "UI  -> http://localhost:5173"
	@trap 'kill 0' EXIT INT TERM; \
	( cd backend && "$(PY)" -m uvicorn app.main:app --reload --port 8000 ) & \
	( cd frontend && npm run dev ) & \
	wait

test: ## Run the backend pytest suite and the frontend unit tests
	cd backend && "$(PY)" -m pytest
	cd frontend && npm test

lint: ## Lint the frontend sources with ESLint
	cd frontend && npm run lint

fetch-data: ## Rebuild the offline Elexon snapshot (reuses data/raw; ARGS=--refresh)
	cd backend && "$(PY)" scripts/fetch_data.py $(ARGS)
