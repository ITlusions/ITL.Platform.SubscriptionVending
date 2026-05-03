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
     └─ 6. Publish outbound notification event  (if VENDING_EVENT_GRID_TOPIC_ENDPOINT set)
```

---

## Component breakdown

### FastAPI application (`src/subscription_vending/`)

| Module | Responsibility |
|--------|---------------|
| `main.py` | Application factory; mounts routers; exposes `/health` |
| `config.py` | Pydantic-settings `Settings` class; loads `VENDING_*` env vars |
| `models.py` | Pydantic request/response models for Event Grid and webhooks |
| `workflow.py` | Orchestrates the six-step provisioning workflow |
| `handlers/event_grid.py` | `POST /webhook/` — receives Event Grid deliveries, validates SAS key, dispatches to workflow |
| `handlers/mock.py` | `POST /webhook/test` — mock endpoint (enabled when `VENDING_MOCK_MODE=true`) |
| `azure/management_groups.py` | Moves a subscription under a target management group |
| `azure/notifications.py` | Publishes an outbound `ITL.SubscriptionVending.SubscriptionProvisioned` event to an Azure Event Grid Custom Topic after each provisioning workflow run (Step 6). Enabled only when `VENDING_EVENT_GRID_TOPIC_ENDPOINT` is set. |
| `azure/rbac.py` | Creates initial RBAC role assignments on the subscription scope |
| `azure/policy.py` | Assigns default Azure Policies; attaches the ITL Foundation Initiative via the Authorization service |
| `azure/tags.py` | Reads subscription tags from Azure and converts them to a `SubscriptionConfig` dataclass |

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
