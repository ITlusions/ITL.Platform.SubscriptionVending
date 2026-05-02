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
| `VENDING_MG_PRODUCTION` | `ITL-Production` | Management group name for subscriptions tagged `itl-environment=production`. |
| `VENDING_MG_STAGING` | `ITL-Staging` | Management group name for subscriptions tagged `itl-environment=staging`. |
| `VENDING_MG_DEVELOPMENT` | `ITL-Development` | Management group name for subscriptions tagged `itl-environment=development`. |
| `VENDING_MG_SANDBOX` | `ITL-Sandbox` | Management group name for subscriptions tagged `itl-environment=sandbox`. Also the fallback when the tag is missing or invalid. |

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
| `itl-environment` | `production`, `staging`, `development`, `sandbox` | Selects the target management group from the `VENDING_MG_*` variables. Also determines policy enforcement mode (`Default` for production, `DoNotEnforce` for all others). | `sandbox` |
| `itl-aks` | `true`, `false` | Marks the subscription for AKS/Flux base chart installation. | `false` |
| `itl-budget` | Integer (e.g. `500`) | Creates a monthly Azure Cost Management budget at the specified EUR amount with e-mail alerts at 80 % and 100 %. | No budget alert |
| `itl-owner` | E-mail address | Contact address for budget alert notifications. Overrides `VENDING_DEFAULT_ALERT_EMAIL`. | `VENDING_DEFAULT_ALERT_EMAIL` |

Invalid tag values are silently ignored and the corresponding default is used, so provisioning always continues even when tags are malformed.
