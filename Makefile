# Makefile for Stage0 Runbook API
# Simple curl-based commands for testing runbooks

.PHONY: help dev deploy down open validate execute get-token container tail

# Configuration
API_URL ?= http://localhost:8083
RUNBOOK ?= 
DATA ?= {"env_vars":{}} 

help:
	@echo "Available commands:"
	@echo "  make dev              - Start API server with local runbooks mounted (for testing runbooks)"
	@echo "  make deploy           - Start API server with packaged runbooks (for deployment)"
	@echo "  make down             - Stop all services"
	@echo "  make open             - Open web UI in browser"
	@echo "  make tail             - Tail API logs (captures terminal, Ctrl+C to exit)"
	@echo "  make validate         - Validate a runbook (requires RUNBOOK=path/to/runbook.md)"
	@echo "  make execute          - Execute a runbook (requires RUNBOOK=path/to/runbook.md)"
	@echo "  make container        - Build the container image"
	@echo ""
	@echo "Examples:"
	@echo "  make dev              # Start API in dev mode (local runbooks mounted)"
	@echo "  make deploy           # Start API in deploy mode (packaged runbooks)"
	@echo "  make validate RUNBOOK=samples/runbooks/SimpleRunbook.md"
	@echo "  make execute RUNBOOK=samples/runbooks/SimpleRunbook.md DATA='{\"env_vars\":{\"TEST_VAR\":\"test_value\"}}'"

down:
	@MOUNT_DIR=$$(pwd)/execution docker compose --profile runbook-dev --profile runbook-deploy down

open:
	@echo "Opening web UI..."
	@open http://localhost:8084 2>/dev/null || xdg-open http://localhost:8084 2>/dev/null || echo "Please open http://localhost:8084 in your browser"

tail:
	docker logs -f stage0_runbook_api

get-token:
	@curl -s -X POST $(API_URL)/dev-login \
		-H "Content-Type: application/json" \
		-d '{"subject": "dev-user", "roles": ["sre", "api", "data", "ux"]}' \
		| jq -r '.access_token // .token // empty'

validate:
	@FILENAME=$$(basename $(RUNBOOK)); \
	TOKEN=$$(make -s get-token); \
	curl -s -X PATCH "$(API_URL)/api/runbooks/$$FILENAME" \
		-H "Authorization: Bearer $$TOKEN" \
		-H "Content-Type: application/json" \
		-d '$(DATA)' \
		| jq '.' || cat

execute:
	@FILENAME=$$(basename $(RUNBOOK)); \
	TOKEN=$$(make -s get-token); \
	curl -s -X POST "$(API_URL)/api/runbooks/$$FILENAME" \
		-H "Authorization: Bearer $$TOKEN" \
		-H "Content-Type: application/json" \
		-d '$(DATA)' \
		| jq '.' || cat

# Start API server with local runbooks mounted (for runbook authors)
dev:
	@$(MAKE) down || true
	@mkdir -p execution
	@echo "Starting API server in dev mode with local runbooks mounted..."
	@bash -c 'export JWT_SECRET=$$(date +%s) && export MOUNT_DIR=$$(pwd)/execution && docker compose --profile runbook-dev up -d'
	@echo "Waiting for API to be ready..."
	@timeout 30 bash -c 'until curl -sf http://localhost:8083/metrics > /dev/null; do sleep 1; done' || true
	@echo "API is ready at http://localhost:8083"
	@echo "Runbooks are mounted from ./samples/runbooks"
	@echo "Use 'make down' to stop the API"

# Start API server with packaged runbooks (for deployment)
deploy:
	@$(MAKE) down || true
	@mkdir -p execution
	@echo "Starting API server in deploy mode with packaged runbooks..."
	@bash -c 'export JWT_SECRET=$$(date +%s) && export MOUNT_DIR=$$(pwd)/execution && docker compose --profile runbook-deploy up -d'
	@echo "Waiting for API to be ready..."
	@timeout 30 bash -c 'until curl -sf http://localhost:8083/metrics > /dev/null; do sleep 1; done' || true
	@echo "API is ready at http://localhost:8083"
	@echo "Runbooks are packaged in the container at ./runbooks"
	@echo "Use 'make down' to stop the API"

# Build the deployment container
container:
	@docker build -t ghcr.io/agile-learning-institute/stage0_runbook_api:latest .
