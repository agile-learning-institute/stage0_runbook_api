# stage0_runbook_api

This repository contains the `stage0_runbook_api` component of the [Stage0 Runbook System](https://github.com/agile-learning-institute/stage0_runbooks) - a production-ready REST API server for validating and executing runbooks. There is a WebUI `stage0_runbook_spa` available at [GitHub stage0_runbook_spa](https://github.com/agile-learning-institute/stage0_runbook_spa)

## Quick Start

A Runbook is just a markdown file that describes a task. You can create a runbook for a manual task, or describe manual steps as part of an automated task, but for an automated task to be executed by the runbook automation, it must have the proper [Runbook layout](./RUNBOOK.md). See the [Custom Runbook Template](https://github.com/agile-learning-institute/stage0_runbook_template) for instructions on setting up your own custom runbook system.

### Using Makefile (For Runbook Authors)

The Makefile provides simple curl-based commands for testing runbooks without requiring Python:

```sh
# Start API server with local runbooks mounted 
make dev

# Start API server with packaged runbooks
make deploy

# Tail the API log files (ctrl-c to end)
make tail 

# Validate a runbook (assumes API is running)
make validate RUNBOOK=samples/runbooks/SimpleRunbook.md

# Execute a runbook with environment variables (assumes API is running)
make execute RUNBOOK=samples/runbooks/SimpleRunbook.md DATA='{"env_vars":{"TEST_VAR":"test_value"}}'

# Open web UI in browser (assumes API and SPA are running)
make open

# Stop the API server
make down

# Build the container image
make container
```

The Makefile execute and validate commands use `curl` to interact with the API:
- Automatically gets a dev token from `/dev-login`
- Calls the appropriate API endpoint
- Formats JSON output using `jq`

**Prerequisites**: `make`, `curl`, and `jq` (for JSON formatting)

**Note**: `pipenv run dev` runs the API server locally (not in Docker) and is for API developers, not runbook authors.

### Using the API Directly

All operations require JWT authentication. For development, use the `/dev-login` endpoint to get a token:

```sh
# Get a token
TOKEN=$(curl -s -X POST http://localhost:8083/dev-login \
  -H "Content-Type: application/json" \
  -d '{"subject":"dev-user","roles":["developer","admin"]}' | \
  jq -r '.access_token')

# Validate a runbook
curl -X PATCH "http://localhost:8083/api/runbooks/SimpleRunbook.md" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json"

# Execute a runbook with environment variables
curl -X POST "http://localhost:8083/api/runbooks/SimpleRunbook.md" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"env_vars":{"TEST_VAR":"test_value"}}'

# Execute without environment variables (empty env_vars object)
curl -X POST "http://localhost:8083/api/runbooks/SimpleRunbook.md" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"env_vars":{}}'

# List all runbooks
curl -X GET "http://localhost:8083/api/runbooks" \
  -H "Authorization: Bearer $TOKEN"

# Get runbook content
curl -X GET "http://localhost:8083/api/runbooks/SimpleRunbook.md" \
  -H "Authorization: Bearer $TOKEN"

# Shutdown the API server
curl -X POST "http://localhost:8083/api/shutdown" \
  -H "Authorization: Bearer $TOKEN"
```

## Contributing Prerequisites

- Python 3.12+
- pipenv (install with `pip install pipenv`)
- Docker and Docker Compose (for container-based execution)

## Developer Commands

For API developers working on the API codebase:

```sh
# Install dependencies
pipenv install

# Run unit and integration tests (uses Flask test client, no running API required)
pipenv run test

# Run end-to-end (e2e) tests (comprehensive workflow tests)
pipenv run e2e

# Run the API server locally (not in Docker, for API development)
pipenv run dev

# Build the deployment container
make container
```

For runbook authors testing their runbooks, use `make api` (see [Using Makefile](#using-makefile-for-runbook-authors) above).

## API Server

The API server runs via Gunicorn and provides REST API endpoints for runbook operations with JWT authentication.

### API Explorer

Interactive API documentation is available at **http://localhost:8083/docs/explorer.html** when the API is running. The explorer provides:
- Complete endpoint documentation with descriptions
- Try-it-out functionality for testing endpoints
- Request/response examples
- Authentication testing

The OpenAPI specification is available at **http://localhost:8083/docs/openapi.yaml**.

**Note**: All endpoints except `/dev-login`, `/metrics`, and `/docs` require JWT authentication.

## Configuration

The API server uses a centralized `Config` singleton (see [`src/config/config.py`](./src/config/config.py)) that manages all configuration via environment variables with sensible defaults.

**Key Configuration Variables:**
- `API_PORT` - Port for the API server (default: `8083`)
- `RUNBOOKS_DIR` - Directory containing runbooks (default: `/runbooks`)
- `EXECUTION_DIR` - Container path where per-run directories are created (default: `/execution`). 
- `MOUNT_DIR` - **Required** host path mounted at `EXECUTION_DIR` used for `docker run -v`
- `ENABLE_LOGIN` - Enable `/dev-login` endpoint for development (default: `false`, **NEVER enable in production**)
- `JWT_SECRET` - Secret for JWT signing (**MUST be set in production**)
- `JWT_ISSUER` - Expected JWT issuer claim
- `JWT_AUDIENCE` - Expected JWT audience claim

**For complete configuration reference**, see [`src/config/config.py`](./src/config/config.py) which defines all configuration options, their types, defaults, and how they're loaded from environment variables.

**For production configuration guidance**, including required settings, recommended values, and deployment examples, see the [SRE Documentation](https://github.com/agile-learning-institute/stage0_runbooks/blob/main/SRE.md#production-configuration).

## Authentication and Authorization

### Development Mode

When `ENABLE_LOGIN=true`, use the `/dev-login` endpoint to obtain JWT tokens:

```bash
curl -X POST http://localhost:8083/dev-login \
  -H "Content-Type: application/json" \
  -d '{"subject":"dev-user","roles":["developer","admin"]}'
```

**Never enable this in production!**

### Production Authentication and RBAC

For production authentication setup, JWT configuration, and Role-Based Access Control (RBAC) details, see the [SRE Documentation](https://github.com/agile-learning-institute/stage0_runbooks/blob/main/SRE.md#authentication-and-authorization).

Runbooks can specify required claims in the "Required Claims" section to control access. See [RUNBOOK.md](./RUNBOOK.md#required-claims) for details on how to specify required claims and how RBAC validation works.

## Runbook Format

For complete details on runbook structure, required sections, history format, and execution processing, see [RUNBOOK.md](./RUNBOOK.md).

### Sub-Runbook Execution

Runbooks can call other runbooks (sub-runbooks) via API calls, enabling composition of complex workflows from simpler, reusable runbooks. Scripts automatically receive system environment variables (`RUNBOOK_API_TOKEN`, `RUNBOOK_CORRELATION_ID`, `RUNBOOK_URL`, `RUNBOOK_RECURSION_STACK`) for making API calls. The `RUNBOOK_URL` variable includes the `/api/runbooks` path for convenient use. The system includes automatic recursion detection and depth limiting to prevent infinite loops and circular dependencies. See [RUNBOOK.md](./RUNBOOK.md#sub-runbook-execution) for complete documentation and examples.

## Security

For comprehensive security documentation, including security features, production requirements, known limitations, threat model, and best practices, see [SECURITY.md](./SECURITY.md).


## Production Deployment Guide

For comprehensive production deployment documentation, including deployment options (Docker Compose single/multi-instance, Kubernetes), configuration reference, monitoring setup, load balancing, backup/recovery, and performance tuning, see [SRE.md](https://github.com/agile-learning-institute/stage0_runbooks/blob/main/SRE.md) in the stage0_runbooks repository.

## Project Structure

```
.
├── samples/                       # Sample Dockerfiles and example runbooks
├── docs/                          # API Explorer, OpenAPI, History Schema
├── src/
│   ├── config/                    # Configuration management
│   ├── flask_utils/               # Flask utilities
│   ├── routes/                    # API route blueprints
│   ├── services/                  # Business logic layer
│   └── server.py                  # Flask application factory
└── test/
    ├── e2e/                       # End 2 End testing
    ├── integration/               # Integration testing
    ├── unit/                      # Unit testing
```
Need help - **Join us on Discord**: [Runbooks Support Channel](https://discord.gg/Pcs8yTXPuh)
