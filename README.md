# ITL.Platform.SubscriptionVending

Subscription Vending is a FastAPI microservice that automatically provisions new Azure subscriptions after creation.  
The service listens to Azure Event Grid events and executes a fixed provisioning workflow: management group placement, RBAC role assignments, policy assignments, and optional cost budget alerts.

> **Detailed documentation** is available in the [`/docs`](./docs) folder:
> - [Architecture overview](./docs/architecture.md)
> - [Configuration reference](./docs/configuration.md)
> - [Provisioning workflow](./docs/provisioning-workflow.md)
> - [API reference](./docs/api.md)
> - [Local development guide](./docs/development.md)
> - [Infrastructure deployment (Bicep)](./docs/infrastructure.md)
> - [Kubernetes deployment](./docs/kubernetes.md)

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
│       └── subscriptionOwnerRoleAssignment.bicep
├── k8s/
│   ├── deployment.yaml
│   ├── service.yaml
│   └── configmap.yaml
└── src/
    └── subscription_vending/
        ├── main.py
        ├── config.py
        ├── models.py
        ├── workflow.py
        ├── handlers/
        │   ├── event_grid.py
        │   └── mock.py
        └── azure/
            ├── management_groups.py
            ├── rbac.py
            ├── policy.py
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

## Configuration

All settings are loaded from environment variables with the `VENDING_` prefix (or from a `.env` file).  
See [`.env.example`](.env.example) for a full annotated list, and [docs/configuration.md](./docs/configuration.md) for detailed descriptions.

| Variable | Default | Description |
|---|---|---|
| `VENDING_AZURE_TENANT_ID` | *(required)* | Azure tenant ID |
| `VENDING_AZURE_CLIENT_ID` | `""` | Service principal client ID (empty = Managed Identity) |
| `VENDING_AZURE_CLIENT_SECRET` | `""` | Service principal secret |
| `VENDING_ROOT_MANAGEMENT_GROUP` | `ITL` | Default management group for new subscriptions |
| `VENDING_MG_PRODUCTION` | `ITL-Production` | Management group for `itl-environment=production` |
| `VENDING_MG_STAGING` | `ITL-Staging` | Management group for `itl-environment=staging` |
| `VENDING_MG_DEVELOPMENT` | `ITL-Development` | Management group for `itl-environment=development` |
| `VENDING_MG_SANDBOX` | `ITL-Sandbox` | Management group for `itl-environment=sandbox` (also the fallback) |
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

### Tag-based provisioning

Subscriptions can carry Azure resource tags that control how they are provisioned:

| Tag | Values | Effect |
|-----|--------|--------|
| `itl-environment` | `production`, `staging`, `development`, `sandbox` | Determines management group placement and policy enforcement mode |
| `itl-aks` | `true` / `false` | Signals that AKS base charts should be installed via Flux |
| `itl-budget` | Integer amount in EUR (e.g. `500`) | Creates an Azure Cost Management budget with e-mail alerts at 80 % and 100 % |
| `itl-owner` | E-mail address | Contact for budget alerts; overrides `VENDING_DEFAULT_ALERT_EMAIL` |

Invalid tag values are silently ignored and fall back to defaults so provisioning always continues.

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
