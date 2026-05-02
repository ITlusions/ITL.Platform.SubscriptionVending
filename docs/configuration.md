# Configuration Reference

All configuration is provided through environment variables with the `VENDING_` prefix.  
Variables can also be placed in a `.env` file in the project root (loaded automatically by Pydantic Settings).

Copy [`.env.example`](../.env.example) to `.env` and fill in the values before starting the service.

---

## Azure credentials

| Variable | Default | Description |
|----------|---------|-------------|
| `VENDING_AZURE_TENANT_ID` | *(required)* | Azure Active Directory tenant ID. Must always be set. |
| `VENDING_AZURE_CLIENT_ID` | `""` | Service principal application (client) ID. Leave empty to use Managed Identity. |
| `VENDING_AZURE_CLIENT_SECRET` | `""` | Service principal secret. Required when `VENDING_AZURE_CLIENT_ID` is set. |

When both `VENDING_AZURE_CLIENT_ID` and `VENDING_AZURE_CLIENT_SECRET` are populated the service uses `ClientSecretCredential`. If either is empty, `ManagedIdentityCredential` is used instead. Managed Identity is recommended for all Azure-hosted deployments.

---

## Management group placement

| Variable | Default | Description |
|----------|---------|-------------|
| `VENDING_ROOT_MANAGEMENT_GROUP` | `ITL` | Name of the root/default management group. Used as a fallback when no `itl-environment` tag is present. |
| `VENDING_ENVIRONMENT_MG_MAPPING` | *(JSON — see below)* | JSON string mapping environment names to management group names. Supports unlimited custom environments. |

### Environment → Management Group mapping

`VENDING_ENVIRONMENT_MG_MAPPING` accepts a JSON object where each key is an `itl-environment` tag value and each value is the target management group name.

**Default mapping:**

```bash
VENDING_ENVIRONMENT_MG_MAPPING='{
  "production": "ITL-Production",
  "staging": "ITL-Staging",
  "development": "ITL-Development",
  "sandbox": "ITL-Sandbox"
}'
```

Any number of additional environments can be added:

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

If the `itl-environment` tag value is not found in the mapping, the subscription falls back to the `sandbox` management group (or `ITL-Sandbox` if that key is also absent from the mapping). If the JSON value is malformed, the entire mapping falls back to `{"sandbox": "ITL-Sandbox"}`.

---

## RBAC role assignments

The following variables control which Azure AD principals receive default role assignments on each new subscription. Leave a variable empty to skip the corresponding role assignment.

| Variable | Default | Role granted | Description |
|----------|---------|-------------|-------------|
| `VENDING_PLATFORM_SPN_OBJECT_ID` | `""` | Owner | Object ID of the ITL platform service principal. |
| `VENDING_OPS_GROUP_OBJECT_ID` | `""` | Contributor | Object ID of the ITL Operations Azure AD group. |
| `VENDING_SECURITY_GROUP_OBJECT_ID` | `""` | Security Reader | Object ID of the ITL Security Azure AD group. |
| `VENDING_FINOPS_GROUP_OBJECT_ID` | `""` | Cost Management Reader | Object ID of the ITL FinOps Azure AD group. |

> **Note:** These values are Azure AD **object IDs**, not display names or client IDs. You can look up object IDs in the Azure Portal under **Azure Active Directory → Groups / Enterprise applications**.

---

## Budget alerts

| Variable | Default | Description |
|----------|---------|-------------|
| `VENDING_DEFAULT_ALERT_EMAIL` | `""` | Fallback e-mail address for budget alert notifications when the `itl-owner` subscription tag is not set. If empty and the tag is absent, no notification contact is configured. |

---

## Authorization service

| Variable | Default | Description |
|----------|---------|-------------|
| `VENDING_AUTHORIZATION_SERVICE_URL` | `http://itl-authorization:8004` | Base URL of the internal ITL Authorization service. Used to attach the ITL Foundation Policy Initiative to new subscriptions. |

---

## Keycloak

| Variable | Default | Description |
|----------|---------|-------------|
| `VENDING_KEYCLOAK_URL` | `http://keycloak:8080` | Base URL of the Keycloak identity provider. |
| `VENDING_KEYCLOAK_REALM` | `ITL` | Keycloak realm name. |

---

## Event Grid

| Variable | Default | Description |
|----------|---------|-------------|
| `VENDING_EVENT_GRID_SAS_KEY` | `""` | Shared-access-signature key injected by Event Grid as the `aeg-sas-key` header. When set, the webhook rejects any request whose header does not match. Leave empty to disable SAS key validation. |

---

## Feature flags

| Variable | Default | Description |
|----------|---------|-------------|
| `VENDING_MOCK_MODE` | `false` | Set to `true` to mount the `POST /webhook/test` mock endpoint. Intended for local development and integration testing only. Never enable in production. |

---

## Tag-based provisioning

Azure subscription tags are read at the start of the provisioning workflow. They override defaults derived from environment variables.

| Tag | Expected values | Effect | Fallback |
|-----|----------------|--------|---------|
| `itl-environment` | Any string (e.g. `production`, `staging`, `acceptance`, `customer-a`) | Selects the target management group via `VENDING_ENVIRONMENT_MG_MAPPING`. Also determines policy enforcement mode (`Default` for `production`, `DoNotEnforce` for all others). | `sandbox` MG |
| `itl-aks` | `true`, `false` | Marks the subscription for AKS/Flux base chart installation. | `false` |
| `itl-budget` | Integer (e.g. `500`) | Creates a monthly Azure Cost Management budget at the specified EUR amount with e-mail alerts at 80 % and 100 %. | No budget alert |
| `itl-owner` | E-mail address | Contact address for budget alert notifications. Overrides `VENDING_DEFAULT_ALERT_EMAIL`. | `VENDING_DEFAULT_ALERT_EMAIL` |

Invalid tag values are silently ignored and the corresponding default is used, so provisioning always continues even when tags are malformed.

### Configurable tag key names

The tag key names shown above are defaults. You can override them to match your own tagging conventions using the following environment variables:

| Environment variable | Default value | Description |
|---|---|---|
| `VENDING_TAG_ENVIRONMENT` | `itl-environment` | Tag key used to determine the target environment / management group |
| `VENDING_TAG_AKS` | `itl-aks` | Tag key used to enable AKS/Flux setup |
| `VENDING_TAG_BUDGET` | `itl-budget` | Tag key for the monthly budget amount in EUR |
| `VENDING_TAG_OWNER` | `itl-owner` | Tag key for the budget alert e-mail address |

For example, to use `myorg-environment` instead of `itl-environment`:

```bash
VENDING_TAG_ENVIRONMENT=myorg-environment
VENDING_TAG_AKS=myorg-aks
VENDING_TAG_BUDGET=cost-budget
VENDING_TAG_OWNER=cost-owner
```
