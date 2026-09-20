# netzanalyst — one entry point for the common tasks.
#
# Homebrew Postgres is not on PATH by default; add it for the db targets.
export PATH := /opt/homebrew/opt/postgresql@16/bin:$(PATH)

MCP := services/mcp-server
TODAY := $(shell date +%F)

.DEFAULT_GOAL := help
.PHONY: help setup hooks db-up db-reset ingest ingest-dry mcp-build mcp-run mcp-stdio \
        test test-py test-mcp lint fmt tf-validate check clean

help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup:  ## Install Python and Node dependencies
	python3 -m pip install -e ".[dev]"
	cd $(MCP) && npm install

hooks:  ## Install the pre-commit hooks
	pre-commit install

db-up:  ## Create the local database, schema and read-only role
	./scripts/setup-local-db.sh

db-reset:  ## Drop and recreate the local database from scratch
	./scripts/setup-local-db.sh --reset

ingest:  ## Load SMARD data from 2024-01-01 to today
	set -a; . ./.env; set +a; python3 -m netzanalyst.ingest --from 2024-01-01 --to $(TODAY)

ingest-dry:  ## Fetch and validate one week without writing
	python3 -m netzanalyst.ingest --from 2026-08-01 --to 2026-08-07 --dry-run

mcp-build:  ## Compile the MCP server
	cd $(MCP) && npm run build

mcp-run: mcp-build  ## Run the MCP server over HTTP on :3000
	set -a; . ./.env; set +a; cd $(MCP) && node dist/index.js

mcp-stdio: mcp-build  ## Run the MCP server over stdio
	set -a; . ./.env; set +a; cd $(MCP) && node dist/index.js --stdio

test: test-py test-mcp  ## Run all tests

test-py:  ## Run the Python tests
	python3 -m pytest

test-mcp: mcp-build  ## Run the MCP server tests
	cd $(MCP) && npm test

lint:  ## Lint and typecheck Python and TypeScript
	python3 -m ruff check src tests
	python3 -m ruff format --check src tests
	python3 -m mypy
	cd $(MCP) && npm run typecheck

fmt:  ## Autoformat Python and Terraform
	python3 -m ruff check --fix src tests
	python3 -m ruff format src tests
	terraform -chdir=infra/terraform fmt -recursive

tf-validate:  ## Validate the Terraform without credentials
	terraform -chdir=infra/terraform init -backend=false -input=false
	terraform -chdir=infra/terraform validate

check: lint test tf-validate  ## Everything CI runs

clean:  ## Remove build artefacts and macOS AppleDouble files
	rm -rf $(MCP)/dist .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov
	find . -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
	# dot_clean strips attributes from extracted Terraform provider binaries,
	# which breaks the checksums in .terraform.lock.hcl and makes `validate`
	# fail with "missing or corrupted provider plugins". Remove the provider
	# cache first; `make tf-validate` re-downloads it.
	rm -rf infra/terraform/.terraform
	dot_clean -m . 2>/dev/null || true
	@echo "Note: run 'make tf-validate' to restore the Terraform provider cache."
