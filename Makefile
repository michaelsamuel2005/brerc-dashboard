# BRERC Public Dashboard — developer convenience targets.
# Run `make` or `make help` to list targets. Docker Compose v2 is assumed
# (`docker compose`). Nothing here needs anything beyond Docker + a POSIX shell.

# Load .env if present so targets can see POSTGRES_* etc.
ifneq (,$(wildcard ./.env))
include .env
export
endif

COMPOSE ?= docker compose
# Run one-off DB commands through the running db service as the superuser.
PSQL = $(COMPOSE) exec -T db psql -v ON_ERROR_STOP=1 -U $(POSTGRES_USER) -d $(POSTGRES_DB)

.DEFAULT_GOAL := help
.PHONY: help up down restart logs ps build db-migrate db-seed db-reset gate-test \
        db-internal dq-test internal-up internal-down \
        lint typecheck test test-api test-web api-dev web-dev fmt clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	 | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[1m%-14s\033[0m %s\n", $$1, $$2}'

## ---- Stack lifecycle -------------------------------------------------------
up: ## Build (if needed) and start the whole stack in the background
	$(COMPOSE) up -d --build

down: ## Stop the stack and remove containers (keeps the data volume)
	$(COMPOSE) down

restart: down up ## Restart the stack

logs: ## Follow logs for all services
	$(COMPOSE) logs -f

ps: ## Show service status
	$(COMPOSE) ps

build: ## Build all images without starting
	$(COMPOSE) build

## ---- Database --------------------------------------------------------------
db-migrate: ## Apply all SQL migrations in order (idempotent)
	@for f in db/migrations/*.sql; do \
		echo "-- applying $$f"; \
		$(PSQL) -v readonly_password="$(BRERC_READONLY_PASSWORD)" -f "/repo/$$f"; \
	done

db-seed: ## Load the SYNTHETIC demo dataset (safe; never client data)
	$(PSQL) -f /repo/db/seed/sensitive_species_demo.sql
	$(PSQL) -f /repo/db/seed/seed_synthetic.sql
	@echo "Seeded synthetic demo data."
	@echo "Refreshing Martin so it discovers the tile function + new data…"
	-$(COMPOSE) restart martin api

db-reset: ## Drop + recreate the schema, then migrate + seed (DESTRUCTIVE, dev only)
	$(PSQL) -c "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;"
	$(MAKE) db-migrate db-seed

gate-test: ## Assert the fail-closed sensitive-species gate holds (needs DB up)
	$(PSQL) -f /repo/db/tests/test_generalisation_gate.sql
	@echo "Gate test passed: no finer-than-allowed geometry is exposed."

## ---- Internal data-quality dashboard (SECONDARY, opt-in) -------------------
db-internal: ## Create the internal role + data-quality views (+ demo anomalies)
	@for f in db/internal/*.sql; do \
		echo "-- applying $$f"; \
		$(PSQL) -v internal_password="$(BRERC_INTERNAL_PASSWORD)" -f "/repo/$$f"; \
	done
	$(PSQL) -f /repo/db/seed/internal_dq_demo.sql
	@echo "Internal DQ views ready (and demo anomalies loaded)."

dq-test: ## Assert the internal data-quality views catch the seeded anomalies
	$(PSQL) -f /repo/db/tests/test_data_quality.sql

internal-up: ## Start the internal data-quality API (localhost only, NOT proxied)
	$(COMPOSE) --profile internal up -d --build api-internal
	@echo "Internal API on http://localhost:$${INTERNAL_API_PORT:-8001}/  (open internal-web/index.html)"

internal-down: ## Stop the internal API service
	$(COMPOSE) --profile internal stop api-internal

## ---- Quality gates ---------------------------------------------------------
lint: ## Lint everything (ruff, sqlfluff, eslint)
	cd api && ruff check .
	sqlfluff lint db --dialect postgres || true
	cd web && npm run lint

typecheck: ## Static type checks (mypy, tsc)
	cd api && mypy app
	cd web && npm run typecheck

test: test-api test-web ## Run all unit/component tests

test-api: ## Run API unit tests (DB-backed tests skip if no DATABASE_URL)
	cd api && pytest -q

test-web: ## Run web unit + accessibility (axe) tests
	cd web && npm run test

fmt: ## Auto-format (ruff format, prettier)
	cd api && ruff format .
	cd web && npm run format

## ---- Local dev servers (without full compose) ------------------------------
api-dev: ## Run the FastAPI dev server with autoreload
	cd api && uvicorn app.main:app --reload --host $(API_HOST) --port $(API_PORT)

web-dev: ## Run the Vite dev server
	cd web && npm run dev

clean: ## Remove build artefacts and caches (keeps node_modules and DB volume)
	rm -rf web/dist web/coverage api/.pytest_cache api/.mypy_cache api/.ruff_cache
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
