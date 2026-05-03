[![Pipeline](https://github.com/ITlusions/ITL.Platform.SubscriptionVending/actions/workflows/pipeline.yml/badge.svg?branch=main)](https://github.com/ITlusions/ITL.Platform.SubscriptionVending/actions/workflows/pipeline.yml)
[![Publish Docs](https://github.com/ITlusions/ITL.Platform.SubscriptionVending/actions/workflows/docs.yml/badge.svg?branch=main)](https://github.com/ITlusions/ITL.Platform.SubscriptionVending/actions/workflows/docs.yml)
[![GitHub Pages](https://img.shields.io/badge/docs-GitHub%20Pages-0969da?logo=github)](https://itlusions.github.io/ITL.Platform.SubscriptionVending/)

# ITL.Platform.SubscriptionVending

Subscription Vending is a FastAPI microservice that automatically provisions new Azure subscriptions after creation.  
The service listens to Azure Event Grid events and executes a fixed provisioning workflow: management group placement, RBAC role assignments, policy assignments, and optional cost budget alerts.

---

## How it works

1. Azure creates a subscription (`Microsoft.Subscription/aliases/write`).
2. An Azure Event Grid system topic fires a `Microsoft.Resources.ResourceActionSuccess` event and delivers it via HTTP POST to `POST /webhook/` on this service.
3. The service runs the provisioning workflow for the new subscription:

   | Phase | Action |
   |-------|--------|
   | **Gates** | Pre-flight checks (e.g. ServiceNow ticket validation). A failing gate with `stop_on_error=True` aborts all provisioning. |
   | Step 0 | Read subscription tags — drives the remaining steps |
   | Step 1 | Move the subscription to the correct management group |
   | Step 2 | Attach the ITL Foundation Policy Initiative (via the Authorization service) |
   | Step 3 | Create default RBAC role assignments |
   | Step 4 | Assign default Azure Policy definitions |
   | Step 5 | Create a Cost Management budget alert *(only when `itl-budget` tag is set)* |
   | Step 6 | Publish an outbound `SubscriptionProvisioned` event *(only when `VENDING_EVENT_GRID_TOPIC_ENDPOINT` is set)* |

4. A `ProvisioningResult` is logged. Each provisioning step is **independent** by default — a failure is recorded but does not stop subsequent steps.
5. A `ProvisioningResult` is logged. Each step is **independent** — a failure is recorded but does not stop subsequent steps.
6. The retry strategy (`VENDING_RETRY_STRATEGY`) controls how failures are handled:

   | Strategy | Behaviour |
   |----------|-----------|
   | `none` *(default)* | Runs inline, always returns `200`. Failures are logged only. |
   | `dead_letter` | Runs inline, returns `500` on failure — Event Grid retries up to its configured limit. |
   | `queue` | Enqueues a `ProvisioningJob` to Azure Storage Queue and returns `200`. A separate `POST /worker/process-job` consumer processes jobs asynchronously. |

7. Use `POST /webhook/replay` to manually re-trigger provisioning for any subscription without a real Event Grid event.

See [docs/provisioning-workflow.md](./docs/provisioning-workflow.md) for full details on each step, and [docs/configuration.md](./docs/configuration.md) for all retry strategy settings.

---

> **Documentation site:** [itlusions.github.io/ITL.Platform.SubscriptionVending](https://itlusions.github.io/ITL.Platform.SubscriptionVending/)
>
> - [Live Demo — automated walkthrough](https://itlusions.github.io/ITL.Platform.SubscriptionVending/demo)
> - [Architecture overview](https://itlusions.github.io/ITL.Platform.SubscriptionVending/architecture)
> - [Configuration reference](https://itlusions.github.io/ITL.Platform.SubscriptionVending/configuration)
> - [Secrets handling](https://itlusions.github.io/ITL.Platform.SubscriptionVending/secrets)
> - [Provisioning workflow](https://itlusions.github.io/ITL.Platform.SubscriptionVending/provisioning-workflow)
> - [API reference](https://itlusions.github.io/ITL.Platform.SubscriptionVending/api)
> - [Local development guide](https://itlusions.github.io/ITL.Platform.SubscriptionVending/development)
> - [Infrastructure deployment (Bicep)](https://itlusions.github.io/ITL.Platform.SubscriptionVending/infrastructure)
> - [Kubernetes deployment](https://itlusions.github.io/ITL.Platform.SubscriptionVending/kubernetes)

---

## Directory structure

```
ITL.Platform.SubscriptionVending/
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── docs/
│   ├── architecture.md
│   ├── api.md
│   ├── configuration.md
│   ├── development.md
│   ├── infrastructure.md
│   ├── kubernetes.md
│   └── provisioning-workflow.md
├── infra/
│   ├── main.bicep
│   ├── params.bicepparam
│   └── modules/
│       ├── subscriptionOwnerRoleAssignment.bicep
│       └── mgVendingRoleAssignment.bicep
├── k8s/
│   ├── deployment.yaml
│   ├── service.yaml
│   └── configmap.yaml
└── src/
    └── subscription_vending/
        ├── main.py
        ├── config.py          # Settings + get_settings() singleton
        ├── models.py          # backward-compat re-export (use schemas/ for new code)
        ├── workflow.py        # orchestrator — built-in steps 1–6
        ├── domain/
        │   └── context.py     # StepContext, ProvisioningResult (pure domain)
        ├── core/
        │   ├── base.py        # BaseStep ABC
        │   ├── events.py      # lifecycle event bus
        │   ├── registry.py    # step + gate registry, toposort
        │   ├── protocols.py   # Azure port contracts (typing.Protocol)
        │   └── exceptions.py  # typed exception hierarchy
        ├── schemas/
        │   └── event_grid.py  # HTTP request/response schemas (Pydantic)
        ├── handlers/
        │   ├── event_grid.py
        │   ├── mock.py
        │   ├── preflight.py
        │   ├── replay.py
        │   └── worker.py
        ├── retry/
        │   ├── dispatcher.py
        │   ├── models.py
        │   └── queue_client.py
        ├── extensions/
        │   ├── _webhook_notify.py
        │   ├── _api_notify.py
        │   ├── _servicenow_check.py
        │   └── _servicenow_feedback.py
        └── azure/
            ├── management_groups.py
            ├── notifications.py
            ├── policy.py
            ├── rbac.py
            └── tags.py
```

---

## Quickstart

### Prerequisites

- Python 3.12+
- Docker (optional, for container-based development)
- Azure CLI (for infrastructure deployment)

### Local development

1. **Clone and install dependencies**

   ```bash
   git clone https://github.com/ITlusions/ITL.Platform.SubscriptionVending.git
   cd ITL.Platform.SubscriptionVending
   pip install -e ".[dev]"
   ```

2. **Configure environment**

   ```bash
   cp .env.example .env
   # Edit .env and set at minimum VENDING_AZURE_TENANT_ID
   ```

3. **Run the service**

   ```bash
   uvicorn subscription_vending.main:app --reload --host 0.0.0.0 --port 8000
   ```

4. **Check health**

   ```bash
   curl http://localhost:8000/health
   # {"status": "ok"}
   ```

### Running with Docker Compose

```bash
docker-compose up --build
```

The service starts on <http://localhost:8000> with `VENDING_MOCK_MODE=true` (mock endpoint enabled).

### Mock mode

Set `VENDING_MOCK_MODE=true` to enable the `POST /webhook/test` endpoint, which lets you trigger the provisioning workflow without a real Event Grid delivery:

```bash
curl -X POST http://localhost:8000/webhook/test \
  -H "Content-Type: application/json" \
  -d '{"subscription_id": "00000000-0000-0000-0000-000000000001", "subscription_name": "test-sub"}'
```

---

## API endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Liveness check — returns `{"status": "ok"}`. Used by Kubernetes probes. |
| `POST /webhook/` | **Event Grid target URL.** Receives subscription-created events and triggers the provisioning dispatcher. Handles the Event Grid validation handshake. Configure `VENDING_EVENT_GRID_SAS_KEY` to restrict access. |
| `POST /webhook/preflight` | **Dry-run validation.** Validates the ServiceNow ticket (read-only) and returns a structured plan of what provisioning would do — without making any Azure changes. |
| `POST /webhook/replay` | **Manual re-trigger.** Idempotent replay of the provisioning workflow for any subscription. Supports `dry_run`. Optionally secured via `VENDING_WORKER_SECRET`. |
| `POST /worker/process-job` | **Queue worker.** Processes a single base64-encoded `ProvisioningJob` message from an Azure Storage Queue. Only active when `VENDING_RETRY_STRATEGY=queue`. |
| `POST /webhook/test` | Mock trigger for the provisioning workflow. Only available when `VENDING_MOCK_MODE=true`. |
| `GET /docs` | Interactive Swagger UI (available when the service is running). |
| `GET /redoc` | ReDoc API reference. |

Point your Azure Event Grid subscription delivery endpoint to `https://<host>/webhook/`.  
See [docs/api.md](./docs/api.md) for full request/response schemas.

---

## Configuration

All settings are loaded from environment variables with the `VENDING_` prefix (or from a `.env` file).  
See [`.env.example`](.env.example) for a full annotated list, and [docs/configuration.md](./docs/configuration.md) for detailed descriptions.

| Variable | Default | Description |
|---|---|---|
| `VENDING_AZURE_TENANT_ID` | *(required)* | Azure tenant ID |
| `VENDING_AZURE_CLIENT_ID` | `""` | Service principal client ID (empty = Managed Identity) |
| `VENDING_AZURE_CLIENT_SECRET` | `""` | Service principal secret |
| `VENDING_ROOT_MANAGEMENT_GROUP` | `ITL` | Default management group for new subscriptions |
| `VENDING_ENVIRONMENT_MG_MAPPING` | *(JSON — see below)* | JSON mapping of environment names to management group names |
| `VENDING_PLATFORM_SPN_OBJECT_ID` | `""` | Object ID of the platform service principal (granted Owner) |
| `VENDING_OPS_GROUP_OBJECT_ID` | `""` | Object ID of the Operations group (granted Contributor) |
| `VENDING_SECURITY_GROUP_OBJECT_ID` | `""` | Object ID of the Security group (granted Security Reader) |
| `VENDING_FINOPS_GROUP_OBJECT_ID` | `""` | Object ID of the FinOps group (granted Cost Management Reader) |
| `VENDING_DEFAULT_ALERT_EMAIL` | `""` | Fallback e-mail for budget alerts when `itl-owner` tag is absent |
| `VENDING_AUTHORIZATION_SERVICE_URL` | `http://itl-authorization:8004` | Internal authorization service base URL |
| `VENDING_KEYCLOAK_URL` | `http://keycloak:8080` | Keycloak base URL |
| `VENDING_KEYCLOAK_REALM` | `ITL` | Keycloak realm |
| `VENDING_MOCK_MODE` | `false` | Enable the `/webhook/test` mock endpoint |
| `VENDING_EVENT_GRID_SAS_KEY` | `""` | SAS key for validating incoming Event Grid deliveries |
| `VENDING_EVENT_GRID_TOPIC_ENDPOINT` | `""` | Event Grid Custom Topic endpoint for outbound `SubscriptionProvisioned` notification events. Leave empty to disable outbound notifications. |
| `VENDING_TAG_ENVIRONMENT` | `itl-environment` | Tag key for the target environment / management group |
| `VENDING_TAG_AKS` | `itl-aks` | Tag key to enable AKS/Flux setup |
| `VENDING_TAG_BUDGET` | `itl-budget` | Tag key for the monthly budget amount in EUR |
| `VENDING_TAG_OWNER` | `itl-owner` | Tag key for the budget alert e-mail address |
| `VENDING_TAG_SNOW_TICKET` | `itl-snow-ticket` | Tag key for the ServiceNow ticket number |
| `VENDING_SNOW_INSTANCE` | `""` | ServiceNow hostname (e.g. `myco.service-now.com`). Required for ServiceNow integration. |
| `VENDING_SNOW_USER` | `""` | ServiceNow username (basic auth) |
| `VENDING_SNOW_PASSWORD` | `""` | ServiceNow password (basic auth) |
| `VENDING_SNOW_TABLE` | `sc_req_item` | ServiceNow table to query / update |
| `VENDING_SNOW_REQUIRE_STATE` | `approved` | Required ticket state before provisioning is allowed |
| `VENDING_SNOW_TIMEOUT` | `10` | HTTP timeout in seconds for ServiceNow calls |
| `VENDING_SNOW_SUCCESS_STATE` | `""` | State to set on ticket after successful provisioning |
| `VENDING_SNOW_FAILURE_STATE` | `""` | State to set on ticket after failed provisioning |
| `VENDING_RETRY_STRATEGY` | `none` | Retry strategy: `none` (inline, always 200), `dead_letter` (500 on failure, lets Event Grid retry), `queue` (enqueue to Azure Storage Queue for async retry) |
| `VENDING_STORAGE_ACCOUNT_NAME` | `""` | Azure Storage Account name for the `queue` retry strategy |
| `VENDING_PROVISIONING_QUEUE_NAME` | `provisioning-jobs` | Work queue name |
| `VENDING_PROVISIONING_DLQ_NAME` | `provisioning-jobs-deadletter` | Dead-letter queue name |
| `VENDING_QUEUE_MAX_DELIVERY_COUNT` | `5` | Failures before a queue message is moved to the DLQ |
| `VENDING_QUEUE_VISIBILITY_TIMEOUT` | `30` | Seconds before a failed queue message reappears |
| `VENDING_WORKER_SECRET` | `""` | Shared secret for `POST /worker/process-job` and `POST /webhook/replay`. Leave empty to allow unauthenticated access (private networks only). |

#### Environment → Management Group mapping

`VENDING_ENVIRONMENT_MG_MAPPING` accepts a JSON object. Any number of custom environments can be added:

```bash
VENDING_ENVIRONMENT_MG_MAPPING='{
  "production":  "ITL-Production",
  "staging":     "ITL-Staging",
  "development": "ITL-Development",
  "sandbox":     "ITL-Sandbox",
  "acceptance":  "ITL-Acceptance",
  "test":        "ITL-Test",
  "customer-a":  "CustomerA-Prod",
  "customer-b":  "CustomerB-Prod"
}'
```

If the `itl-environment` tag value is not found in the mapping, the subscription falls back to the `sandbox` management group (or `ITL-Sandbox` if that key is also absent).

### Tag-based provisioning

Subscriptions can carry Azure resource tags that control how they are provisioned:

| Tag | Values | Effect |
|-----|--------|--------|
| `itl-environment` | Any string (e.g. `production`, `staging`, `acceptance`, `customer-a`) | Determines management group placement via `VENDING_ENVIRONMENT_MG_MAPPING`; unknown values fall back to the `sandbox` MG |
| `itl-aks` | `true` / `false` | Signals that AKS base charts should be installed via Flux |
| `itl-budget` | Integer amount in EUR (e.g. `500`) | Creates an Azure Cost Management budget with e-mail alerts at 80 % and 100 % |
| `itl-owner` | E-mail address | Contact for budget alerts; overrides `VENDING_DEFAULT_ALERT_EMAIL` |
| `itl-snow-ticket` | Ticket number (e.g. `RITM0041872`) | ServiceNow ticket to validate before provisioning and update with the outcome |

Invalid tag values are silently ignored and fall back to defaults so provisioning always continues.

The tag key names above are defaults and can be overridden to match your own tagging conventions:

| Environment variable | Default | Description |
|---|---|---|
| `VENDING_TAG_ENVIRONMENT` | `itl-environment` | Tag key for the target environment / management group |
| `VENDING_TAG_AKS` | `itl-aks` | Tag key to enable AKS/Flux setup |
| `VENDING_TAG_BUDGET` | `itl-budget` | Tag key for the monthly budget amount in EUR |
| `VENDING_TAG_OWNER` | `itl-owner` | Tag key for the budget alert e-mail address |

---

## Infrastructure deployment (Bicep)

```bash
az deployment group create \
  --resource-group rg-itl-subvending \
  --template-file infra/main.bicep \
  --parameters infra/params.bicepparam \
  --parameters eventGridSasKey='<secret>' keycloakUrl='https://keycloak.itlusions.com'
```

See [docs/infrastructure.md](./docs/infrastructure.md) for full deployment instructions.

---

## Kubernetes deployment

```bash
# Create secrets first
kubectl create secret generic subscription-vending-secret \
  --from-literal=azure-tenant-id=<tenant-id>

# Apply manifests
kubectl apply -f k8s/
```

See [docs/kubernetes.md](./docs/kubernetes.md) for full deployment instructions.

---

## Running tests

```bash
pip install -e ".[dev]"
pytest
```

---

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for the full guide — branching strategy, commit conventions, PR process, and coding standards.

- **Report a bug** → [Bug Report](.github/ISSUE_TEMPLATE/bug_report.md)
- **Request a feature** → [Feature Request](.github/ISSUE_TEMPLATE/feature_request.md)
- **Propose an architectural decision** → [ADR](.github/ISSUE_TEMPLATE/adr.md)
- **Report a security vulnerability** → [SECURITY.md](./SECURITY.md) (private advisory)

---

## GitHub Project

Active sprint planning and backlog: **[Project #21 — Subscription Vending](https://github.com/orgs/ITlusions/projects/21)**

### Issue types

| Template | Label | Use for |
|---|---|---|
| Epic | `type:epic` | Multi-sprint body of work with child stories |
| Story | `type:story` | User-facing value, deliverable in one sprint |
| Task | `type:task` | Technical/operational work |
| Bug | `bug` | Defect or regression |
| Spike | `type:spike` | Time-boxed investigation |
| ADR | `documentation` | Architecture Decision Record |

### Onboarding a new project

The `.github/scripts/onboard-project.ps1` script provisions a GitHub ProjectV2 with full Agile fields (Sprint, Priority, Story Points, Work Type, Effort, Epic, Blocked, Risk), milestones, and type labels:

```powershell
.\.github\scripts\onboard-project.ps1 `
    -ProjectTitle "My Service" `
    -RepoName     "ITlusions/ITL.MyService" `
    -SprintCount  4 `
    -CreateLabels `
    -CreateViews
```
