---
layout: default
title: Local Development Guide
---

# Local Development Guide

This guide walks through setting up the service for local development, running it, and executing the test suite.

---

## Prerequisites

| Tool | Minimum version | Notes |
|------|----------------|-------|
| Python | 3.12 | Use [pyenv](https://github.com/pyenv/pyenv) or your OS package manager |
| pip | latest | Bundled with Python |
| Docker + Docker Compose | any recent | Optional; needed for the containerised dev workflow |
| Azure CLI | latest | Optional; needed only for infrastructure deployment |

---

## 1. Clone the repository

```bash
git clone https://github.com/ITlusions/ITL.Platform.SubscriptionVending.git
cd ITL.Platform.SubscriptionVending
```

---

## 2. Install dependencies

The project uses [Hatchling](https://hatch.pypa.io/) as its build backend. Install the package together with the development extras:

```bash
pip install -e ".[dev]"
```

This installs:
- All runtime dependencies (`fastapi`, `uvicorn`, `pydantic`, Azure SDK packages, etc.)
- Development tools: `pytest`, `pytest-asyncio`, `httpx`

---

## 3. Configure the environment

Copy the example configuration and fill in the required values:

```bash
cp .env.example .env
```

At minimum you must set `VENDING_AZURE_TENANT_ID`. For a pure local/mock run you can set it to any non-empty string.

To enable the mock webhook endpoint (useful for testing without a real Azure subscription):

```env
VENDING_MOCK_MODE=true
```

See [configuration.md](./configuration.md) for a full description of all variables, and [secrets.md](./secrets.md) for guidance on which variables are secrets and how to handle them securely.

---

## 4. Run the service

```bash
uvicorn subscription_vending.main:app --reload --host 0.0.0.0 --port 8000
```

The service is available at <http://localhost:8000>.

| URL | Description |
|-----|-------------|
| `http://localhost:8000/health` | Liveness check |
| `http://localhost:8000/docs` | Swagger UI |
| `http://localhost:8000/webhook/` | Event Grid webhook |
| `http://localhost:8000/webhook/test` | Mock webhook (mock mode only) |

---

## 5. Project layout

```
src/subscription_vending/
├── main.py                  application factory, router registration
├── config.py                Settings (Pydantic) + get_settings() @lru_cache singleton
├── models.py                backward-compat re-export — use schemas/ for new code
├── workflow.py              orchestrator: built-in steps 1–6, re-exports domain/core symbols
│
├── domain/
│   └── context.py           StepContext, ProvisioningResult — pure dataclasses, no I/O
│
├── core/
│   ├── base.py              BaseStep ABC — plugin contract
│   ├── events.py            lifecycle event bus (STARTED / SUCCEEDED / FAILED / COMPLETED)
│   ├── registry.py          step + gate registries, register_step(), register_gate(), toposort()
│   ├── protocols.py         Azure port contracts (typing.Protocol, @runtime_checkable)
│   └── exceptions.py        typed exception hierarchy (AppError → ProvisioningError, etc.)
│
├── schemas/
│   └── event_grid.py        HTTP schemas: EventGridEvent, WebhookResponse, HealthResponse
│
├── handlers/                FastAPI routers (driving adapters)
├── retry/                   retry strategies: none / queue / dead_letter
├── extensions/              auto-discovered plugins (self-register at import time)
└── azure/                   Azure SDK calls (management groups, RBAC, policy, tags, notifications)
```

### Key conventions

- Import `StepContext` / `ProvisioningResult` from `domain.context`; import `register_step` / `register_gate` from `core.registry`. The old `workflow` import paths still work (re-exported) but should not be used in new code.
- Use `get_settings()` everywhere instead of `Settings()`. The singleton is cached after the first call.
- New HTTP schemas go in `schemas/` — never in `domain/` or `core/`.
- New Azure SDK calls go in `azure/` — never in `workflow.py` or `handlers/`.
- Raise typed exceptions from `core/exceptions.py` rather than appending plain strings to `ctx.result.errors` (the plain-string pattern is still supported for backward compatibility).

---

## 6. Running with Docker Compose

```bash
docker-compose up --build
```

Docker Compose starts the service with `VENDING_MOCK_MODE=true`. The service is available at <http://localhost:8000>.

To rebuild the image after code changes:

```bash
docker-compose up --build --force-recreate
```

---

## 7. Triggering the mock workflow

With mock mode enabled, you can trigger a full provisioning run without connecting to Azure:

```bash
curl -X POST http://localhost:8000/webhook/test \
  -H "Content-Type: application/json" \
  -d '{
    "subscription_id": "00000000-0000-0000-0000-000000000001",
    "subscription_name": "local-test-sub",
    "management_group_id": "ITL-Development"
  }'
```

Add `"dry_run": true` to skip all Azure mutations and outbound HTTP calls — only log output is produced:

```bash
curl -X POST http://localhost:8000/webhook/test \
  -H "Content-Type: application/json" \
  -d '{
    "subscription_id": "00000000-0000-0000-0000-000000000001",
    "subscription_name": "local-test-sub",
    "management_group_id": "ITL-Development",
    "dry_run": true
  }'
```

> **Note:** "Mock mode" only enables the `/webhook/test` endpoint — it does not stub out Azure SDK calls. The full provisioning workflow is executed, including calls to the Azure Management Groups, RBAC, and Policy APIs. These calls will fail in a local environment without valid Azure credentials, but each step's error is caught, logged, and appended to the result without crashing the service. This makes the endpoint useful for verifying request routing and partial workflow logic.

---

## 8. Running tests

```bash
pytest
```

Or with verbose output:

```bash
pytest -v
```

To run a specific test file:

```bash
pytest tests/test_workflow.py -v
```

The test suite uses `pytest-asyncio` in `auto` mode, so all `async` test functions are automatically treated as async tests.

When patching settings in tests, call `get_settings.cache_clear()` before applying `monkeypatch` env vars:

```python
from subscription_vending.config import get_settings

def test_something(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("VENDING_AZURE_TENANT_ID", "test-tenant")
    settings = get_settings()
    ...
```

### Test structure

| File | What it tests |
|------|--------------|
| `tests/test_app.py` | FastAPI application setup; `/health` endpoint |
| `tests/test_event_grid.py` | Event Grid webhook handler (validation handshake, event parsing, SAS key enforcement) |
| `tests/test_rbac.py` | RBAC role-assignment helpers |
| `tests/test_retry.py` | Retry strategy dispatcher and queue client |
| `tests/test_snow_gate.py` | ServiceNow gate check extension |
| `tests/test_tags.py` | Subscription tag parsing and `SubscriptionConfig` derivation |
| `tests/test_notifications.py` | Outbound notification step |
| `tests/test_workflow.py` | End-to-end provisioning workflow with mocked Azure calls |

---

## 8. Project structure recap

```
src/subscription_vending/   # Application source
  azure/                    # Azure SDK wrappers (management groups, RBAC, policy, etc.)
  core/                     # Shared internals (BaseStep ABC, lifecycle event bus)
  extensions/               # Auto-discovered extension modules
  handlers/                 # FastAPI route handlers
tests/                      # Pytest test suite
infra/                      # Bicep IaC templates
k8s/                        # Kubernetes manifests
docs/                       # Documentation
.env.example                # Annotated environment-variable template
pyproject.toml              # Build metadata and dependencies
Dockerfile                  # Container image definition
docker-compose.yml          # Local development compose file
```

---

## Tips

- **Hot reload:** `--reload` in the `uvicorn` command restarts the server on every file change.
- **Log level:** Set the `LOG_LEVEL` environment variable (or pass `--log-level debug` to `uvicorn`) for more verbose output.
- **Interactive API docs:** The Swagger UI at `/docs` lets you call all endpoints directly from the browser without `curl`.
