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
| Key Vault | `{prefix}-kv` | Stores the Event Grid SAS key; accessed via KV reference |
| Event Grid Custom Topic | `{prefix}-notifications` | Outbound `SubscriptionProvisioned` events |
| Event Grid System Topic | `{prefix}-eg-topic` | Scoped to the Azure subscription |
| Event Grid Subscription | `{prefix}-subscription` | Delivers `Microsoft.Resources.ResourceActionSuccess` events to the Function App webhook |
| Role Assignment (subscription) | — | Owner on the deployment subscription *(temporary — see Step 3 below)* |
| **Role Assignment (MG)** | — | **Custom `Subscription Vending Operator` role on the root management group — deployed separately** |

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
- **Contributor** access to the resource group
- **Owner** access to the Azure subscription (required for the subscription-scoped role-assignment module)
- **Owner or User Access Administrator** on the root management group (required for Step 3 — MG role assignment)

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

### 3. Assign the custom role on the root management group

The main deployment only assigns Owner on the deployment subscription. That is **not sufficient** — the Function App needs to move subscriptions into management groups and act on them after placement.

This step deploys `infra/modules/mgVendingRoleAssignment.bicep` at management group scope to create a minimal **`Subscription Vending Operator`** custom role and assign it to the Managed Identity:

```bash
# Retrieve the MI principal ID from the main deployment output
MI_PRINCIPAL_ID=$(az deployment group show \
  --resource-group rg-itl-subvending \
  --name main \
  --query properties.outputs.managedIdentityPrincipalId.value \
  --output tsv)

# Deploy the MG-scoped role assignment (requires Owner/UAA on the root MG)
az deployment mg create \
  --management-group-id ITL \
  --location westeurope \
  --template-file infra/modules/mgVendingRoleAssignment.bicep \
  --parameters principalId="$MI_PRINCIPAL_ID" namePrefix='itl-vending'
```

Replace `ITL` with your root management group ID if it differs from `rootManagementGroup` in `params.bicepparam`.

**Permissions granted by the custom role:**

| Action | Required for |
|--------|-------------|
| `Microsoft.Resources/subscriptions/read` + `tagNames/read` | Step 0 — read subscription tags |
| `Microsoft.Management/managementGroups/subscriptions/write` | Step 1 — MG placement |
| `Microsoft.Authorization/roleAssignments/write` | Step 3 — RBAC assignments |
| `Microsoft.Authorization/policyAssignments/write` | Step 4 — policy assignments |
| `Microsoft.Consumption/budgets/write` | Step 5 — budget alerts |

This role is assigned at the root MG scope so it automatically applies to all child management groups and subscriptions beneath it.

> **Note:** The subscription-scoped Owner assignment from Step 2 (`subscriptionOwnerRoleAssignment.bicep`) can be removed once the MG-scoped custom role is in place. It is kept for backwards compatibility with existing deployments.

### 4. Check the outputs

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

## Modules

### `subscriptionOwnerRoleAssignment.bicep`

Assigns the built-in **Owner** role to the Function App's Managed Identity at the **deployment subscription** scope. Deployed as part of `main.bicep`.

This grants sufficient permissions for the Function App to operate on the subscription it is deployed into, but **not** for subscriptions placed into other management groups. See `mgVendingRoleAssignment.bicep` below for the complete solution.

### `mgVendingRoleAssignment.bicep`

Creates a minimal **`Subscription Vending Operator`** custom role and assigns it to the Managed Identity at the **root management group** scope. This is the recommended approach for production — it follows least-privilege and covers all child subscriptions automatically.

Deployed separately via `az deployment mg create` (see Step 3 above). Requires Owner or User Access Administrator on the root management group.

**The custom role grants exactly:**
- `subscriptions/read` + `tagNames/read` — Step 0
- `managementGroups/subscriptions/write` — Step 1
- `roleAssignments/write` — Step 3
- `policyAssignments/write` — Step 4
- `budgets/write` — Step 5

---

## Updating an existing deployment

Re-run the same `az deployment group create` command — Bicep is idempotent and will only update resources that have changed.

To update application settings without redeploying all infrastructure, use `az functionapp config appsettings set` as shown in the post-deployment section above.
