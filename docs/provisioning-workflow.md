---
layout: default
title: Provisioning Workflow
---

# Provisioning Workflow

When the service receives a `Microsoft.Resources.ResourceActionSuccess` event for a `Microsoft.Subscription/aliases/write` operation, it executes the following workflow for the new subscription.

The workflow has two phases:

1. **Gate checks** — pre-flight validations that run before any Azure mutation. A failing gate with `stop_on_error=True` aborts provisioning entirely.
2. **Provisioning steps** — the actual Azure operations, run in topological order.

A failure in a provisioning step is logged and recorded in `result.errors` by default, but does not stop subsequent steps (unless `stop_on_error=True` is set on that step).

All steps — built-in (Steps 1–6) **and** custom steps from `extensions/` — run through a shared topological sort driven by `depends_on` declarations. This means you can insert a custom step between any two built-in steps by referencing the relevant step constant:

```python
from subscription_vending.core.registry import register_step
from subscription_vending.domain.context import StepContext
from subscription_vending.workflow import STEP_RBAC

@register_step(depends_on=[STEP_RBAC])   # runs after RBAC, before policy
async def my_step(ctx: StepContext) -> None:
    ...
```

> `workflow.py` re-exports `register_step`, `register_gate`, and `StepContext` for backward compatibility.
> New code should import from `core.registry` and `domain.context` directly.

### Step constants

| Constant | Step | Import from |
|----------|------|--------------|
| `STEP_MG` | Management group placement | `subscription_vending.workflow` |
| `STEP_INITIATIVE` | Attach Foundation Initiative | `subscription_vending.workflow` |
| `STEP_RBAC` | RBAC role assignments | `subscription_vending.workflow` |
| `STEP_POLICY` | Policy assignments | `subscription_vending.workflow` |
| `STEP_BUDGET` | Budget alert | `subscription_vending.workflow` |
| `STEP_NOTIFY` | Outbound event publish | `subscription_vending.workflow` |

All constants are also re-exported from `subscription_vending` directly.

---

## Gate checks

Gate checks run **before Step 0** and before any Azure mutation. They are ideal for pre-flight validation — such as verifying that an approved ServiceNow ticket exists.

A gate check is registered with `register_gate`. By default `stop_on_error=True`, meaning a failing gate aborts the entire workflow immediately.

```python
from subscription_vending.core.registry import register_gate
from subscription_vending.domain.context import StepContext

@register_gate
async def require_snow_ticket(ctx: StepContext) -> None:
    if not ctx.config.snow_ticket:
        ctx.result.errors.append("No ServiceNow ticket on subscription")
```

Gate checks run in registration order. They do **not** participate in the topological sort and cannot declare `depends_on`.

`register_gate` is also re-exported from `subscription_vending` directly.

### `stop_on_error`

Both gate checks and regular provisioning steps support `stop_on_error`:

| Usage | Default | Behaviour |
|-------|---------|----------|
| `@register_gate` | `True` | Abort workflow if gate records an error |
| `@register_step` | `False` | Record error and continue remaining steps |
| `MyStep().register()` | `False` | Same as above |

```python
# Abort all remaining steps if this critical step fails
@register_step(depends_on=[STEP_MG], stop_on_error=True)
async def critical_validation(ctx: StepContext) -> None:
    ...

# Soft gate — warns but does not abort
@register_gate(stop_on_error=False)
async def advisory_check(ctx: StepContext) -> None:
    ...
```

---

## Preflight dry-run

Before committing a real event, you can validate that all prerequisites are in place by calling `POST /webhook/preflight`. This endpoint:

- Runs all gate checks **with real ServiceNow calls** (read-only)
- Simulates all provisioning steps in dry-run mode
- Returns a structured `plan` list showing what would happen
- Makes **no Azure changes**

See [api.md](./api.md#post-webhookpreflight) for the full request/response schema.

---

The service fetches the subscription's tags from the Azure Subscription API using the configured credential. The tags are converted into a `SubscriptionConfig` object that drives the remaining steps.

**Relevant tags:**

| Tag | Effect |
|-----|--------|
| `itl-environment` | Selects management group and policy enforcement mode |
| `itl-aks` | Flags the subscription for AKS/Flux setup |
| `itl-budget` | EUR amount for the monthly cost budget |
| `itl-owner` | E-mail address for budget alert notifications |
| `itl-snow-ticket` | ServiceNow ticket number (e.g. `RITM0041872`) — required when the ServiceNow gate extension is active |

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
| `errors` | `list[str]` | Error messages from failed steps or gates |
| `plan` | `list[str]` | Human-readable list of what each step did or would do (populated in dry-run mode) |
| `success` | `bool` *(property)* | `True` when `errors` is empty |
| `dry_run` | `bool` | `True` when the workflow was invoked in dry-run mode |

All results are logged at `INFO` level. Errors are additionally logged at `ERROR` level with full stack traces.

---

## Custom steps

After Step 6, the workflow executes any **custom steps** registered via `@register_step` or `BaseStep.register()`. Steps run in topological order based on their `depends_on` declarations. A failure in one custom step is recorded in `result.errors` but never prevents remaining steps from running.

### Writing a custom step

Create a `.py` file in `src/subscription_vending/extensions/`. It is picked up automatically at startup — no edits to `main.py` needed.

```python
# extensions/my_step.py
from __future__ import annotations
from ..workflow import StepContext, STEP_NOTIFY
from ..core.base import BaseStep

class MyStep(BaseStep):
    async def execute(self, ctx: StepContext) -> None:
        # ctx.subscription_id, ctx.subscription_name
        # ctx.config  — SubscriptionConfig (environment, budget, owner, …)
        # ctx.settings — VENDING_* env-var config
        # ctx.result  — append to ctx.result.errors on failure
        # ctx.dry_run — True when no Azure/HTTP calls should be made
        ...

# Runs last, after the built-in outbound notification
MyStep().register(depends_on=[STEP_NOTIFY])
```

### Step ordering with `depends_on`

Steps may declare dependencies on other custom steps. The scheduler runs a topological sort before execution:

```python
step_a = StepA().register()
StepB().register(depends_on=[step_a])  # always runs after step_a
```

A cycle or unregistered dependency is non-fatal: it is recorded in `result.errors` and no custom steps run that invocation.

### Built-in helpers provided by `BaseStep`

| Helper | Description |
|--------|-------------|
| `self.logger` | Per-class `logging.Logger` scoped to the subclass |
| `self._build_payload(ctx)` | Returns the standard provisioning result dict |
| `self._http_post(ctx, url, headers, timeout)` | POSTs the payload as JSON; catches HTTP/network errors into `result.errors` |

---

## Built-in extensions

Two notification extensions and two **ServiceNow extensions** ship in the `extensions/` package. All are prefixed with `_` so they are not auto-discovered by default.

### `_webhook_notify.py` — plain HTTPS webhook

POSTs the provisioning result to a plain HTTPS endpoint authenticated by a shared secret header.

| Env var | Required | Description |
|---------|----------|-------------|
| `VENDING_WEBHOOK_URL` | Yes | HTTPS endpoint to POST to |
| `VENDING_WEBHOOK_SECRET` | No | Sent as `X-Webhook-Secret` header |
| `VENDING_WEBHOOK_TIMEOUT` | No | Timeout in seconds (default: `10`) |

### `_api_notify.py` — REST API with Bearer token

POSTs the provisioning result to a REST API endpoint using `Authorization: Bearer` authentication.

| Env var | Required | Description |
|---------|----------|-------------|
| `VENDING_API_NOTIFY_URL` | Yes | API endpoint to POST to |
| `VENDING_API_NOTIFY_TOKEN` | No | Bearer token value |
| `VENDING_API_NOTIFY_TIMEOUT` | No | Timeout in seconds (default: `10`) |

If the URL env var is not set, the extension silently skips.

### `_servicenow_check.py` — ServiceNow ticket gate

Runs as a **gate check** before any provisioning step. Queries the ServiceNow Table API to verify that the ticket on the subscription (from the `itl-snow-ticket` tag) exists and is in the required state.

| Env var | Required | Description |
|---------|----------|-------------|
| `VENDING_SNOW_INSTANCE` | Yes | ServiceNow hostname, e.g. `myco.service-now.com` |
| `VENDING_SNOW_USER` | Yes | ServiceNow username (basic auth) |
| `VENDING_SNOW_PASSWORD` | Yes | ServiceNow password |
| `VENDING_SNOW_TABLE` | No | Table to query (default: `sc_req_item`; use `change_request` for CHG) |
| `VENDING_SNOW_REQUIRE_STATE` | No | Required `approval` or `state` value (default: `approved`; set to `""` for existence-only) |
| `VENDING_SNOW_TIMEOUT` | No | HTTP timeout in seconds (default: `10`) |

The check is **read-only** and runs even in dry-run mode so preflight results are accurate.

When `VENDING_SNOW_INSTANCE` is not set this gate is a no-op — the integration is opt-in.

To enable, import the module explicitly in `main.py`:

```python
import subscription_vending.extensions._servicenow_check  # noqa: F401
```

### `_servicenow_feedback.py` — ServiceNow provisioning outcome

Runs as a **provisioning step** after `STEP_NOTIFY`. PATCHes the ServiceNow ticket with `work_notes` describing the provisioning outcome and, optionally, transitions the ticket to a new state.

| Env var | Required | Description |
|---------|----------|-------------|
| `VENDING_SNOW_INSTANCE` | Yes | ServiceNow hostname (shared with check extension) |
| `VENDING_SNOW_USER` | Yes | ServiceNow username |
| `VENDING_SNOW_PASSWORD` | Yes | ServiceNow password |
| `VENDING_SNOW_TABLE` | No | Table to update (default: `sc_req_item`) |
| `VENDING_SNOW_SUCCESS_STATE` | No | `state` value to set on success (e.g. `3` = Closed Complete). Leave empty to not change state. |
| `VENDING_SNOW_FAILURE_STATE` | No | `state` value to set on failure (e.g. `4` = Closed Incomplete). Leave empty to not change state. |
| `VENDING_SNOW_TIMEOUT` | No | HTTP timeout in seconds (default: `10`) |

Feedback failures (e.g. ServiceNow unreachable) are **non-fatal** — they are logged as warnings and do not affect `result.errors`.

To enable, import the module explicitly in `main.py`:

```python
import subscription_vending.extensions._servicenow_feedback  # noqa: F401
```

---

## Lifecycle events

The workflow emits named lifecycle events that extensions can subscribe to without being registered as steps. Handlers run after all custom steps complete.

### Available events

| Event | When fired |
|-------|------------|
| `PROVISIONING_STARTED` | Before custom steps begin |
| `PROVISIONING_COMPLETED` | Always — after all steps finish |
| `PROVISIONING_SUCCEEDED` | Only when `result.errors` is empty |
| `PROVISIONING_FAILED` | Only when `result.errors` is non-empty |

### Subscribing to events

```python
from subscription_vending.core.events import LifecycleEvent, on
from subscription_vending.workflow import StepContext

@on(LifecycleEvent.PROVISIONING_SUCCEEDED)
async def notify_on_success(ctx: StepContext) -> None:
    ...

@on(LifecycleEvent.PROVISIONING_FAILED)
async def alert_on_failure(ctx: StepContext) -> None:
    for error in ctx.result.errors:
        ...
```

Handlers receive the same `StepContext` as custom steps. Errors in handlers are caught, recorded in `result.errors`, and never abort remaining handlers.
