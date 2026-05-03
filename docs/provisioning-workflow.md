---
layout: default
title: Provisioning Workflow
---

# Provisioning Workflow

When the service receives a `Microsoft.Resources.ResourceActionSuccess` event for a `Microsoft.Subscription/aliases/write` operation, it executes the following workflow for the new subscription (Steps 0–6). Each step is independent — a failure in one step is logged but does not stop subsequent steps.

---

## Step 0 — Read subscription tags

The service fetches the subscription's tags from the Azure Subscription API using the configured credential. The tags are converted into a `SubscriptionConfig` object that drives the remaining steps.

**Relevant tags:**

| Tag | Effect |
|-----|--------|
| `itl-environment` | Selects management group and policy enforcement mode |
| `itl-aks` | Flags the subscription for AKS/Flux setup |
| `itl-budget` | EUR amount for the monthly cost budget |
| `itl-owner` | E-mail address for budget alert notifications |

If the subscription cannot be fetched, or a tag value is invalid, the step falls back to defaults and the workflow continues.

---

## Step 1 — Management group placement

The subscription is moved under the appropriate management group using the Azure Management Groups API.

**Priority order for the target management group:**

1. Tag-derived MG name (from `itl-environment` tag + `VENDING_MG_*` settings)
2. `managementGroupId` field from the Event Grid event payload
3. `VENDING_ROOT_MANAGEMENT_GROUP` setting (default: `ITL`)

**Environment → management group mapping:**

The target MG is looked up from `VENDING_ENVIRONMENT_MG_MAPPING` (a JSON object). The mapping supports unlimited custom environment names:

| `itl-environment` tag | Default MG name | Configured via |
|----------------------|----------------|---------------|
| `production` | `ITL-Production` | `VENDING_ENVIRONMENT_MG_MAPPING` |
| `staging` | `ITL-Staging` | `VENDING_ENVIRONMENT_MG_MAPPING` |
| `development` | `ITL-Development` | `VENDING_ENVIRONMENT_MG_MAPPING` |
| `sandbox` *(or missing/unknown)* | `ITL-Sandbox` | `VENDING_ENVIRONMENT_MG_MAPPING` fallback |
| Any custom value (e.g. `acceptance`) | *(as configured)* | Add to `VENDING_ENVIRONMENT_MG_MAPPING` |

If the tag value is not in the mapping, the subscription falls back to the `sandbox` MG entry (or `ITL-Sandbox` if that key is absent).

**Required Azure permission:** `Microsoft.Management/managementGroups/subscriptions/write` at the management group scope.

---

## Step 2 — Attach ITL Foundation Initiative

The service calls the internal Authorization service (`VENDING_AUTHORIZATION_SERVICE_URL`) to attach the ITL Foundation Policy Initiative to the new subscription:

```
POST {VENDING_AUTHORIZATION_SERVICE_URL}/sync/foundation?subscription_id={id}
```

The Authorization service is responsible for looking up and assigning the correct policy initiative. The returned `initiative_id` is stored in the provisioning result for auditability.

**Enforcement mode** is determined by the `itl-environment` tag:

| Environment | Enforcement mode |
|-------------|-----------------|
| `production` | `Default` (enforced) |
| All others | `DoNotEnforce` |

If the Authorization service is unreachable, the error is recorded and the workflow continues.

---

## Step 3 — RBAC role assignments

Default Azure RBAC role assignments are created on the subscription scope for each principal configured via environment variables. Only non-empty object IDs receive a role assignment.

| Setting | Role | Azure built-in role ID |
|---------|------|----------------------|
| `VENDING_PLATFORM_SPN_OBJECT_ID` | Owner | `8e3af657-a8ff-443c-a75c-2fe8c4bcb635` |
| `VENDING_OPS_GROUP_OBJECT_ID` | Contributor | `b24988ac-6180-42a0-ab88-20f7382dd24c` |
| `VENDING_SECURITY_GROUP_OBJECT_ID` | Security Reader | `39bc4728-0917-49c7-9d2c-d95423bc2eb4` |
| `VENDING_FINOPS_GROUP_OBJECT_ID` | Cost Management Reader | `72fafb9e-0641-4937-9268-a91bfd8191a3` |

Each role assignment is created with a new random UUID as the assignment name. Failures for individual assignments are logged as warnings; the loop continues for remaining principals.

**Required Azure permission:** `Microsoft.Authorization/roleAssignments/write` at the subscription scope.

---

## Step 4 — Assign default policies

Azure Policy definitions listed in `DEFAULT_POLICY_DEFINITION_IDS` (in `azure/policy.py`) are assigned to the subscription. This list ships empty by default — operators can extend it in code or via a configuration override.

If no policies are configured, this step is skipped silently.

**Required Azure permission:** `Microsoft.Authorization/policyAssignments/write` at the subscription scope.

---

## Step 5 — Cost budget alert *(conditional)*

This step only executes when the `itl-budget` tag is set to a positive integer.

A monthly Azure Cost Management budget is created (or updated if it already exists) on the subscription scope with:

- **Budget name:** `itl-budget-alert`
- **Amount:** value of the `itl-budget` tag in EUR
- **Time grain:** Monthly (starts the first day of the current month)
- **Notifications:** e-mail alerts at 80 % and 100 % of the budget threshold
- **Contact e-mail:** `itl-owner` tag value, falling back to `VENDING_DEFAULT_ALERT_EMAIL`

If no contact e-mail is available, the notifications are created without a contact address.

**Required Azure permission:** `Microsoft.Consumption/budgets/write` at the subscription scope.

---

## Step 6 — Publish outbound notification event *(conditional)*

This step only executes when `VENDING_EVENT_GRID_TOPIC_ENDPOINT` is configured (non-empty).

The service publishes an `ITL.SubscriptionVending.SubscriptionProvisioned` event to the configured Azure Event Grid Custom Topic using `azure/notifications.py`.

**Event payload fields:**

| Field | Description |
|-------|-------------|
| `subscription_id` | The provisioned subscription ID |
| `subscription_name` | Display name of the provisioned subscription |
| `management_group` | Management group the subscription was moved to |
| `initiative_id` | Initiative ID returned by the Authorization service |
| `rbac_roles` | IDs of successfully created role assignments |
| `errors` | Error messages from failed steps |
| `success` | `true` when no errors were recorded |

**Non-fatal:** any error encountered while publishing the event is logged as a warning and does **not** affect the `ProvisioningResult`. If `VENDING_EVENT_GRID_TOPIC_ENDPOINT` is not set, this step is silently skipped.

**Relevant configuration:** `VENDING_EVENT_GRID_TOPIC_ENDPOINT` (see [configuration.md](./configuration.md)).

---

## Provisioning result

The workflow returns a `ProvisioningResult` object with the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `subscription_id` | `str` | The provisioned subscription ID |
| `management_group` | `str` | Management group the subscription was moved to |
| `initiative_id` | `str` | Initiative ID returned by the Authorization service |
| `rbac_roles` | `list[str]` | IDs of successfully created role assignments |
| `errors` | `list[str]` | Error messages from failed steps |
| `success` | `bool` *(property)* | `True` when `errors` is empty |

All results are logged at `INFO` level. Errors are additionally logged at `ERROR` level with full stack traces.
