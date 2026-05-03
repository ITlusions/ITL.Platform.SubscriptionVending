---
layout: default
title: Infrastructure Deployment
---

# Infrastructure Deployment (Bicep)

The `infra/` directory contains Azure Bicep templates that deploy the complete cloud infrastructure required to run Subscription Vending as an Azure Function App.

---

## Resources deployed

| Resource type | Name pattern | Notes |
|---------------|-------------|-------|
| Storage Account | `{prefix}sa` | Required by Azure Functions |
| App Service Plan | `{prefix}-plan` | Y1 (Consumption), Linux |
| Function App | `{prefix}-func` | Python 3.12, system-assigned Managed Identity |
| Event Grid System Topic | `{prefix}-eg-topic` | Scoped to the Azure subscription |
| Event Grid Subscription | `{prefix}-subscription` | Delivers `Microsoft.Resources.ResourceActionSuccess` events to the Function App webhook |
| Role Assignment | — | Owner on the Azure subscription for the Function App's Managed Identity |

---

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `location` | `resourceGroup().location` | Azure region for all resources |
| `namePrefix` | `itl-vending` | Prefix applied to all resource names |
| `rootManagementGroup` | `ITL` | Root management group name passed to the Function App as `VENDING_ROOT_MANAGEMENT_GROUP` |
| `eventGridSasKey` | *(required, secure)* | SAS key injected by Event Grid as the `aeg-sas-key` header on every delivery |
| `keycloakUrl` | *(required)* | Keycloak base URL passed to the Function App as `VENDING_KEYCLOAK_URL` |

---

## Prerequisites

- Azure CLI installed and logged in: `az login`
- An existing resource group (or create one before deployment)
- Contributor access to the resource group
- Owner access to the Azure subscription (required for the role-assignment module)

---

## Deploy

### 1. Create a resource group (if it doesn't exist)

```bash
az group create \
  --name rg-itl-subvending \
  --location westeurope
```

### 2. Deploy the Bicep template

```bash
az deployment group create \
  --resource-group rg-itl-subvending \
  --template-file infra/main.bicep \
  --parameters infra/params.bicepparam \
  --parameters eventGridSasKey='<your-sas-key>' keycloakUrl='https://keycloak.example.com'
```

Replace `<your-sas-key>` with a strong random string. This same value must be stored in `VENDING_EVENT_GRID_SAS_KEY` in the Function App's configuration.

### 3. Check the outputs

After a successful deployment the following outputs are printed:

| Output | Description |
|--------|-------------|
| `functionAppUrl` | HTTPS URL of the Function App |
| `webhookEndpoint` | Full URL of the webhook endpoint (`/webhook/`) |
| `managedIdentityPrincipalId` | Object ID of the Function App's Managed Identity |

Save `managedIdentityPrincipalId` — you may need it to set `VENDING_PLATFORM_SPN_OBJECT_ID` or for other RBAC assignments.

---

## Post-deployment configuration

After deployment, set any additional application settings on the Function App that were not included in the Bicep template (e.g. RBAC object IDs):

```bash
az functionapp config appsettings set \
  --resource-group rg-itl-subvending \
  --name itl-vending-func \
  --settings \
    VENDING_PLATFORM_SPN_OBJECT_ID=<object-id> \
    VENDING_OPS_GROUP_OBJECT_ID=<object-id> \
    VENDING_SECURITY_GROUP_OBJECT_ID=<object-id> \
    VENDING_FINOPS_GROUP_OBJECT_ID=<object-id> \
    VENDING_DEFAULT_ALERT_EMAIL=alerts@example.com \
    VENDING_AZURE_TENANT_ID=<tenant-id>
```

---

## Customising the parameters file

Edit `infra/params.bicepparam` to set default values for your environment:

```bicep
using './main.bicep'

param location = 'westeurope'
param namePrefix = 'itl-vending'
param rootManagementGroup = 'ITL'
param keycloakUrl = 'https://keycloak.example.com'
// eventGridSasKey is always supplied at deployment time (never store secrets in params files)
```

---

## Module: subscriptionOwnerRoleAssignment.bicep

The `infra/modules/subscriptionOwnerRoleAssignment.bicep` module assigns the **Owner** role to the Function App's Managed Identity at the Azure subscription scope. This is required for the Function App to:

- Move subscriptions between management groups
- Create RBAC role assignments on new subscriptions
- Assign Azure Policies to subscriptions
- Create Cost Management budgets

The module is deployed at subscription scope (using `scope: subscription()`) as part of the main deployment.

---

## Updating an existing deployment

Re-run the same `az deployment group create` command — Bicep is idempotent and will only update resources that have changed.

To update application settings without redeploying all infrastructure, use `az functionapp config appsettings set` as shown in the post-deployment section above.
