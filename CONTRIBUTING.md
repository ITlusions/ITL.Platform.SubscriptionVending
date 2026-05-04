# Contributing to ITL.Platform.SubscriptionVending

Thank you for your interest in contributing! This guide covers everything you need to get started.

---

## Development setup

### Prerequisites

- Python 3.12+
- [Hatch](https://hatch.pypa.io/) (`pip install hatch`)
- Docker (optional, for container testing)

### Install

```bash
git clone https://github.com/ITlusions/ITL.Platform.SubscriptionVending.git
cd ITL.Platform.SubscriptionVending
pip install -e ".[dev]"
```

### Run tests

```bash
pytest
```

### Run locally

```bash
cp .env.example .env
# Edit .env — set at minimum VENDING_AZURE_TENANT_ID
uvicorn subscription_vending.main:app --reload --port 8000
```

### Run with Docker Compose

```bash
docker-compose up --build
```

---

## Branching strategy

| Branch | Purpose |
|---|---|
| `main` | Production-ready code. Every merge triggers a patch version bump and container push. |
| `develop` | Integration branch for ongoing work. |
| `feature/<short-desc>` | New features or improvements. Branch from `develop`. |
| `fix/<short-desc>` | Bug fixes. Branch from `main` for hotfixes, `develop` otherwise. |

---

## Commit conventions

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short description>

[optional body]

[optional footer]
```

**Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `ci`, `chore`  
**Scope:** `workflow`, `handlers`, `azure`, `config`, `ci`, `docs`, `k8s`, `infra`

Examples:

```
feat(workflow): add step 7 for tagging completion
fix(handlers): return 400 on missing subscription_id
docs(readme): update quickstart section
ci: pin actions to latest Node.js 24 compatible versions
```

---

## Pull requests

1. Fork the repo and create a branch from `develop` (or `main` for hotfixes)
2. Make your changes — keep each PR focused on a single concern
3. Run `pytest` and ensure all tests pass
4. Update relevant docs in `/docs` if behaviour changes
5. Update `CHANGELOG.md` under `[Unreleased]`
6. Open a PR against `develop` with a clear description

---

## Coding standards

- **Python 3.12+** with type hints on all public functions
- **async/await** for all route handlers and Azure SDK calls
- Pydantic v2 models for HTTP schemas — keep them in `schemas/`, never in domain code
- No secrets in environment variables — use `DefaultAzureCredential`
- Each provisioning step must be independent — record failures in `ctx.result.errors`, do not raise
- Use `get_settings()` (from `config.py`) instead of instantiating `Settings()` directly — the singleton is cached via `@lru_cache`
- Raise typed exceptions from `core/exceptions.py`, not bare `Exception` or plain strings

---

---

## Architecture overview

This service is a **Microkernel / Plugin pipeline engine** — not a CRUD API.
It receives an Azure Event Grid event when a new subscription is created and
runs a configurable provisioning workflow.

### Data flow

```
Event Grid  /  Queue Worker  /  Preflight  /  Replay
       ↓
handlers/          (FastAPI routers — driving adapters)
       ↓
retry/dispatcher   (strategy: none / queue / dead_letter)
       ↓
WorkflowEngine(settings).run()
  ├── Gate steps   (pre-flight checks, executed first, abort on failure)
  └── Workflow steps (provisioning, topologically ordered by depends_on)
            ↓
core/base.py::BaseStep  (ABC — plugin contract)
            ↓
azure/              (Azure SDK calls: MG placement, RBAC, policy, tags)
            ↓
core/events.py      (lifecycle bus: STARTED / SUCCEEDED / FAILED / COMPLETED)
            ↓
extensions/         (auto-discovered plugins: webhook, API notify, ServiceNow)
```

### Folder responsibilities

| Folder / file | Responsibility |
|---|---|
| `domain/` | Pure domain objects: `StepContext`, `ProvisioningResult`. No I/O, no framework deps. |
| `core/` | Framework skeleton: `BaseStep` ABC, step registry, lifecycle event bus, port contracts, exception hierarchy. No business logic. |
| `schemas/` | Pydantic HTTP schemas (request / response). Import only in `handlers/`. |
| `azure/` | All Azure SDK calls. No workflow orchestration. |
| `extensions/` | Auto-discovered plugins. Each module self-registers at import. |
| `handlers/` | FastAPI routers (webhook, worker, preflight, replay, mock). |
| `retry/` | Retry strategy: inline, Azure Storage Queue, or dead-letter. |
| `config.py` | All settings via `Pydantic BaseSettings` + `get_settings()` singleton. |
| `workflow/engine.py` | Orchestrator: `WorkflowEngine` class — `run()` executes built-in steps 1–6. Re-exports domain / registry symbols for backward compatibility. |

---

## How to add a provisioning step

A provisioning step runs **after** all gate checks pass, as part of the main
workflow. Use `BaseStep` for class-based steps, or `@register_step` for
function-based steps.

### Class-based step (recommended for reusable steps)

Create a new file in `extensions/` (or a separate package if external):

```python
# extensions/_my_step.py
from __future__ import annotations
from ..domain.context import StepContext
from ..core.base import BaseStep

class MyStep(BaseStep):
    """Short description of what this step does."""

    async def execute(self, ctx: StepContext) -> None:
        if ctx.dry_run:
            self.logger.info("DryRun: would do X for %s", ctx.subscription_id)
            return

        # Do work here.
        # Record failures by appending to ctx.result.errors — do NOT raise.
        try:
            ...
        except Exception as exc:
            ctx.result.errors.append(f"MyStep failed: {exc}")

# Auto-register when this module is imported.
MyStep().register()
```

Because the file name starts with `_`, it is **not** auto-discovered.
Import it explicitly in `main.py`:

```python
import subscription_vending.extensions._my_step  # noqa: F401
```

Files **without** a leading `_` are auto-discovered and imported at startup —
use that for generic, always-on extensions.

### Function-based step

```python
from subscription_vending.core.registry import register_step
from subscription_vending.domain.context import StepContext

@register_step
async def my_step(ctx: StepContext) -> None:
    ...

# With dependency ordering:
@register_step(depends_on=[my_step], stop_on_error=True)
async def critical_follow_up(ctx: StepContext) -> None:
    ...
```

> `workflow.py` still re-exports `register_step`, `register_gate`, and `StepContext` for
> backward compatibility, so existing imports continue to work.

### `StepContext` — available fields

Canonical import: `from subscription_vending.domain.context import StepContext`

| Field | Type | Description |
|---|---|---|
| `subscription_id` | `str` | Azure subscription ID |
| `subscription_name` | `str` | Display name |
| `config` | `SubscriptionConfig` | Tag-derived config (environment, budget, owner, etc.) |
| `settings` | `Settings` | All env-var settings |
| `result` | `ProvisioningResult` | Mutable result — append errors here |
| `dry_run` | `bool` | When `True`, skip all mutations and log intent instead |
| `credential` | `Azure credential` | `None` in dry-run mode |

### `BaseStep` — built-in helpers

| Helper | Description |
|---|---|
| `self.logger` | Structured logger named after the subclass |
| `self._build_payload(ctx)` | Standard provisioning result dict |
| `self._http_post(ctx, url, headers, timeout)` | POST payload as JSON; errors go to `ctx.result.errors` |
| `BaseStep.on(event)` | Decorator to subscribe to a lifecycle event |

---

## How to add a gate check

A gate check runs **before** all provisioning steps. If a gate with
`stop_on_error=True` records an error, the entire workflow is aborted.

```python
from subscription_vending.core.registry import register_gate
from subscription_vending.domain.context import StepContext

@register_gate
async def require_owner_tag(ctx: StepContext) -> None:
    if not ctx.config.owner_email:
        ctx.result.errors.append(
            f"Gate failed: no 'itl-owner' tag on {ctx.subscription_name}"
        )
```

Class-based gate using `BaseStep`:

```python
class MyGate(BaseStep):
    async def execute(self, ctx: StepContext) -> None:
        ...

MyGate().register_gate(stop_on_error=True)
```

---

## How to react to lifecycle events

Subscribe to `PROVISIONING_SUCCEEDED`, `PROVISIONING_FAILED`, or
`PROVISIONING_COMPLETED` without modifying the core workflow:

```python
from subscription_vending.core.base import BaseStep

class MyStep(BaseStep):
    ...

@MyStep.on(BaseStep.Event.PROVISIONING_SUCCEEDED)
async def _on_success(ctx) -> None:
    # Runs after all steps complete without errors.
    ...

@MyStep.on(BaseStep.Event.PROVISIONING_FAILED)
async def _on_failure(ctx) -> None:
    # Runs after all steps complete with at least one error.
    ...
```

---

## Where to put new code

| What you are adding | Where it goes |
|---|---|
| New pure domain object | `domain/<name>.py` — no I/O, no framework imports |
| New Azure SDK call | `azure/<concern>.py` |
| New provisioning step (generic, always-on) | `extensions/<name>.py` (no `_` prefix — auto-discovered) |
| New provisioning step (opt-in, configurable) | `extensions/_<name>.py` + explicit import in `main.py` |
| New pre-flight gate check | Same as a step, but register with `.register_gate()` |
| New HTTP request / response schema | `schemas/<concern>.py` — Pydantic `BaseModel` only, import in `handlers/` |
| New HTTP endpoint | `handlers/<name>.py` + `app.include_router(...)` in `main.py` |
| New env-var setting | Field on `Settings` in `config.py` with `VENDING_` prefix |
| New retry strategy | `retry/dispatcher.py` — add a branch in `dispatch()` |
| New port contract (Azure adapter interface) | `core/protocols.py` — `typing.Protocol`, `@runtime_checkable` |
| New exception type | `core/exceptions.py` — inherit from the appropriate base class |
| New ABC or core framework class | `core/base.py` (do not add to `azure/` or `extensions/`) |

---

## Reporting bugs

Use the [Bug Report](.github/ISSUE_TEMPLATE/bug_report.md) issue template.

## Requesting features

Use the [Feature Request](.github/ISSUE_TEMPLATE/feature_request.md) issue template.
