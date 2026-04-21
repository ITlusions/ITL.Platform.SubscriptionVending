# ITL.Platform.SubscriptionVending

Subscription Vending — FastAPI microservice that automatically provisions new Azure subscriptions after creation.  
The service listens to Event Grid events and executes a fixed provisioning workflow (management group placement, RBAC, policies).

---

## Directory structure

```
ITL.Platform.SubscriptionVending/
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── infra/
│   ├── main.bicep
│   └── params.bicepparam
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
            └── policy.py
```

---

## Quickstart

### Prerequisites

- Python 3.12+
- Docker (optional, for container-based dev)
- Azure CLI (for infra deployment)

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

Set `VENDING_MOCK_MODE=true` to enable the `POST /webhook/test` endpoint:

```bash
curl -X POST http://localhost:8000/webhook/test \
  -H "Content-Type: application/json" \
  -d '{"subscription_id": "00000000-0000-0000-0000-000000000001", "subscription_name": "test-sub"}'
```

---

## Configuration

All settings are loaded from environment variables with the `VENDING_` prefix.  
See [`.env.example`](.env.example) for a full list.

| Variable | Default | Description |
|---|---|---|
| `VENDING_AZURE_TENANT_ID` | *(required)* | Azure tenant ID |
| `VENDING_AZURE_CLIENT_ID` | `""` | Service principal client ID (empty = Managed Identity) |
| `VENDING_AZURE_CLIENT_SECRET` | `""` | Service principal secret |
| `VENDING_ROOT_MANAGEMENT_GROUP` | `ITL` | Default management group for new subscriptions |
| `VENDING_AUTHORIZATION_SERVICE_URL` | `http://itl-authorization:8004` | Internal authorization service |
| `VENDING_KEYCLOAK_URL` | `http://keycloak:8080` | Keycloak base URL |
| `VENDING_KEYCLOAK_REALM` | `ITL` | Keycloak realm |
| `VENDING_MOCK_MODE` | `false` | Enable `/webhook/test` mock endpoint |
| `VENDING_EVENT_GRID_SAS_KEY` | `""` | SAS key for validating Event Grid deliveries |

---

## Infrastructure deployment (Bicep)

```bash
az deployment group create \
  --resource-group rg-itl-subvending \
  --template-file infra/main.bicep \
  --parameters infra/params.bicepparam \
  --parameters azureTenantId=<tenant-id> containerImage=<acr>/itl-subscription-vending:latest
```

---

## Kubernetes deployment

```bash
# Create secrets first
kubectl create secret generic subscription-vending-secret \
  --from-literal=azure-tenant-id=<tenant-id>

# Apply manifests
kubectl apply -f k8s/
```

---

## Running tests

```bash
pip install -e ".[dev]"
pytest
```
