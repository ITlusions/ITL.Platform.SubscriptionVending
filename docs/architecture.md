---
layout: default
title: Architecture Overview
---

# Architecture Overview

## What is Subscription Vending?

ITL Subscription Vending is a **FastAPI microservice** that automatically provisions new Azure subscriptions the moment they are created. Rather than requiring manual post-creation steps, the service hooks into Azure Event Grid and runs a deterministic provisioning workflow for every new subscription.

---

## High-level flow

```
Azure Portal / IaC
     │
     │  creates subscription via
     │  Microsoft.Subscription/aliases/write
     ▼
Azure Event Grid
  (Microsoft.Resources.Subscriptions topic)
     │
     │  HTTP POST  aeg-event-type: Notification
     ▼
ITL Subscription Vending  (POST /webhook/)
     │
     ├─ 0. Read subscription tags
     ├─ 1. Move to management group
     ├─ 2. Attach ITL Foundation Initiative (via Authorization service)
     ├─ 3. Create RBAC role assignments
     ├─ 4. Assign default Azure Policies
     ├─ 5. Create cost-budget alert  (if itl-budget tag present)
     ├─ 6. Publish outbound notification event  (if VENDING_EVENT_GRID_TOPIC_ENDPOINT set)
     ├─ [Custom steps — auto-discovered from extensions/, topologically ordered]
     └─ [Lifecycle events — STARTED / COMPLETED / SUCCEEDED / FAILED]
```

---

## Internal architecture

The service is designed as a **Microkernel / Plugin pipeline engine**. The core framework is fixed; all provisioning logic is pluggable.

```
handlers/                  driving adapters (FastAPI routers)
     │
infrastructure/queue/      retry strategy: none / queue / dead_letter
     │
workflow/engine.py         WorkflowEngine — built-in steps 1–6 + toposort
     │
core/registry.py           step + gate registries
     │
core/base.py               BaseStep ABC — plugin contract
     │
core/context.py            StepContext, ProvisioningResult — pure dataclasses
     │
infrastructure/azure/      Azure SDK adapters
     │
core/events.py             lifecycle bus: STARTED / COMPLETED / SUCCEEDED / FAILED
     │
extensions/                auto-discovered plugins
```

### Layer responsibilities

| Layer / folder | Responsibility |
|---|---|
| `core/` | Pure domain + framework skeleton: `BaseStep` ABC, `StepContext`, `ProvisioningResult`, `Settings`, step registry, lifecycle event bus, port contracts (`protocols.py`), exception hierarchy (`exceptions.py`). No business logic, no I/O. |
| `schemas/` | Pydantic HTTP surface contracts. Only imported by `handlers/`. |
| `infrastructure/azure/` | All Azure SDK calls. No workflow orchestration. |
| `infrastructure/queue/` | Retry strategy dispatcher and Azure Storage Queue client. |
| `extensions/` | Auto-discovered plugins. Each module self-registers at import. Only modules starting with `__` are excluded from discovery. |
| `handlers/` | FastAPI routers, each as a sub-package (`event_grid/`, `worker/`, `preflight/`, `replay/`, `mock/`). |
| `core/config.py` | All settings via `Pydantic BaseSettings`. Use `get_settings()` — never instantiate `Settings()` directly. |
| `workflow/` | Package: `engine.py` hosts `WorkflowEngine` and the backward-compat `run_provisioning_workflow` wrapper; `steps.py` defines built-in steps 1–6. |

---

## Component breakdown

### FastAPI application (`src/subscription_vending/`)

| Module | Responsibility |
|--------|---------------|
| `main.py` | Application factory; mounts routers; exposes `/health`; calls `autodiscover()` inside `lifespan` |
| `core/config.py` | Pydantic-settings `Settings` class; `get_settings()` singleton (`@lru_cache`); loads `VENDING_*` env vars |
| `core/context.py` | `StepContext` and `ProvisioningResult` — pure domain dataclasses with no I/O or framework dependencies |
| `core/job.py` | `ProvisioningJob` dataclass — payload written to / read from the retry queue |
| `core/enums.py` | `RetryStrategy` enum (`none`, `queue`, `dead_letter`) |
| `core/base.py` | `BaseStep` ABC — base class for all custom provisioning steps |
| `core/events.py` | Lifecycle event bus — `LifecycleEvent`, `on()`, `emit()` |
| `core/registry.py` | Step and gate registries (`_EXTRA_STEPS`, `_GATE_STEPS`), `register_step()`, `register_gate()`, `_toposort()` |
| `core/protocols.py` | Port contracts: `ManagementGroupPort`, `RbacPort`, `PolicyPort`, `NotificationPort`, `TagReaderPort` — all `@runtime_checkable Protocol` |
| `core/exceptions.py` | Typed exception hierarchy: `AppError → ProvisioningError` (`GateCheckFailed`, `StepFailed`) `\| AzureIntegrationError` (`ManagementGroupError`, `RbacError`, `PolicyError`, `NotificationError`) `\| ConfigurationError \| AuthorizationError` |
| `schemas/event_grid.py` | HTTP surface contracts: `EventGridEvent`, `EventGridEventData`, `WebhookResponse`, `HealthResponse` |
| `workflow/engine.py` | `WorkflowEngine` class — `run()` method orchestrates gates + built-in steps + custom steps + lifecycle events. Also exports backward-compat `run_provisioning_workflow()` wrapper. |
| `workflow/steps.py` | Built-in provisioning steps 1–6, each decorated with `@register_step` |
| `handlers/event_grid/` | `POST /webhook/` — receives Event Grid deliveries, validates SAS key, dispatches to `WorkflowEngine` |
| `handlers/worker/` | `POST /worker/process-job` — dequeues and processes a `ProvisioningJob` from Azure Storage Queue |
| `handlers/preflight/` | `POST /webhook/preflight` — dry-run plan: runs gates + simulates steps, no Azure mutations |
| `handlers/replay/` | `POST /webhook/replay` — manually re-triggers the workflow for a given subscription ID |
| `handlers/mock/` | `POST /webhook/test` — mock endpoint (enabled when `VENDING_MOCK_MODE=true`) |
| `extensions/` | Auto-discovered extension modules; each self-registers at import time via module-level code |
| `extensions/webhook_notify.py` | Optional step: POST result as JSON to a plain HTTPS webhook (`VENDING_WEBHOOK_URL`) |
| `extensions/api_notify.py` | Optional step: POST result as JSON to a REST API with Bearer token auth (`VENDING_API_NOTIFY_URL`) |
| `extensions/servicenow_check.py` | Optional gate: validate a ServiceNow ticket before provisioning starts (`VENDING_SNOW_INSTANCE`) |
| `extensions/servicenow_feedback.py` | Optional step: PATCH the ServiceNow ticket with the provisioning outcome (`VENDING_SNOW_INSTANCE`) |
| `infrastructure/azure/management_groups.py` | Moves a subscription under a target management group |
| `infrastructure/azure/notifications.py` | Publishes an outbound `ITL.SubscriptionVending.SubscriptionProvisioned` event to an Azure Event Grid Custom Topic (Step 6). Enabled only when `VENDING_EVENT_GRID_TOPIC_ENDPOINT` is set. |
| `infrastructure/azure/rbac.py` | Creates initial RBAC role assignments on the subscription scope |
| `infrastructure/azure/policy.py` | Assigns default Azure Policies; attaches the ITL Foundation Initiative via the Authorization service |
| `infrastructure/azure/tags.py` | Reads subscription tags from Azure and converts them to a `SubscriptionConfig` dataclass |
| `infrastructure/azure/credential.py` | Selects `ClientSecretCredential` or `ManagedIdentityCredential` based on settings |
| `infrastructure/queue/dispatcher.py` | Routes a completed/failed job to the configured retry strategy |
| `infrastructure/queue/azure_queue.py` | Azure Storage Queue client — enqueue and dequeue `ProvisioningJob` messages |

### Azure infrastructure (`infra/`)

The Bicep templates deploy:

- **Azure Function App** (Consumption, Linux, Python 3.12) — hosts the FastAPI application via a custom startup command
- **App Service Plan** (Y1 Consumption)
- **Storage Account** — required by Azure Functions
- **Event Grid System Topic** — scoped to the Azure subscription, filtering `Microsoft.Resources.ResourceActionSuccess` events for `Microsoft.Subscription/aliases/write` operations
- **Event Grid Subscription** — delivers events to the Function App webhook endpoint with the SAS key injected as a delivery header
- **Managed Identity** with Owner role at the subscription scope (so the Function App can move subscriptions and create role assignments)

### Kubernetes (`k8s/`)

An alternative deployment path for teams running the service on AKS or any Kubernetes cluster:

- **Deployment** — single replica of the container image with liveness/readiness probes on `/health`
- **Service** — ClusterIP exposing port 8000
- **ConfigMap** — non-secret environment variables; secrets (tenant ID, client credentials, SAS key) are stored in a Kubernetes Secret

---

## Credential strategy

The service supports two authentication modes, selected automatically at startup:

| Scenario | Credential used |
|----------|----------------|
| `VENDING_AZURE_CLIENT_ID` and `VENDING_AZURE_CLIENT_SECRET` are both set | `ClientSecretCredential` (service principal) |
| Either variable is empty | `ManagedIdentityCredential` |

Managed Identity is the recommended option for Azure-hosted deployments.

---

## External dependencies

| Dependency | Purpose |
|------------|---------|
| **Authorization service** (`VENDING_AUTHORIZATION_SERVICE_URL`) | Attaches the ITL Foundation Policy Initiative to new subscriptions |
| **Azure Management Groups API** | Moves subscriptions between management groups |
| **Azure Authorization Management API** | Creates RBAC role assignments |
| **Azure Resource Management API** | Assigns Azure Policy definitions |
| **Azure Subscription API** | Reads subscription tags |
| **Azure Consumption API** | Creates Cost Management budgets |

---

## Error handling

Every step in the provisioning workflow is wrapped in an independent `try/except` block. Failures in individual steps are logged and appended to `ProvisioningResult.errors`, but they **do not abort** the workflow — subsequent steps still execute. This ensures that a transient failure in one step (e.g. the Authorization service being temporarily unavailable) does not prevent management group placement or RBAC assignments.

Event Grid retries are also suppressed: the webhook always returns `200 OK` so that Event Grid does not resend the event. Errors are surfaced exclusively through structured logs.
