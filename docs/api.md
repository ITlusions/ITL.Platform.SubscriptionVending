---
layout: default
title: API Reference
---

# API Reference

The service exposes a minimal HTTP API. The interactive Swagger UI is available at `/docs` and the ReDoc UI at `/redoc` when the service is running.

---

## Endpoints

### `GET /health`

Returns the liveness status of the service. Used by Kubernetes liveness and readiness probes.

**Response** `200 OK`

```json
{"status": "ok"}
```

---

### `POST /webhook/`

Receives Event Grid webhook deliveries. Handles two cases:

1. **Subscription validation handshake** — required by Event Grid before it starts delivering events.
2. **SubscriptionCreated events** — triggers the provisioning workflow for each new subscription.

#### Headers

| Header | Required | Description |
|--------|----------|-------------|
| `aeg-event-type` | No | Set to `SubscriptionValidation` for handshakes; `Notification` for regular event delivery |
| `aeg-sas-key` | Conditional | Must match `VENDING_EVENT_GRID_SAS_KEY` when that setting is non-empty |

#### Request body (validation handshake)

```json
[
  {
    "id": "...",
    "eventType": "Microsoft.EventGrid.SubscriptionValidationEvent",
    "subject": "",
    "data": {
      "validationCode": "512d38b6-c7b8-40c8-89fe-f46f9e9622b1"
    },
    "dataVersion": "1",
    "eventTime": "2024-01-01T00:00:00Z"
  }
]
```

**Response** `200 OK`

```json
{"validationResponse": "512d38b6-c7b8-40c8-89fe-f46f9e9622b1"}
```

#### Request body (subscription created event)

```json
[
  {
    "id": "abc123",
    "eventType": "Microsoft.Resources.ResourceActionSuccess",
    "subject": "/subscriptions/00000000-0000-0000-0000-000000000001",
    "data": {
      "operationName": "Microsoft.Subscription/aliases/write",
      "resourceUri": "/subscriptions/00000000-0000-0000-0000-000000000001",
      "displayName": "my-new-subscription",
      "managementGroupId": "ITL-Development"
    },
    "dataVersion": "1",
    "eventTime": "2024-01-01T00:00:00Z"
  }
]
```

**Response** `200 OK` (empty body)

The provisioning workflow runs asynchronously within the request. Event Grid always receives a `200 OK` to prevent retries; errors are surfaced in logs only.

#### Error responses

| Code | Reason |
|------|--------|
| `400 Bad Request` | Empty payload, or validation handshake missing `validationCode` |
| `401 Unauthorized` | `aeg-sas-key` header does not match `VENDING_EVENT_GRID_SAS_KEY` |

---

### `POST /webhook/preflight`

Validates prerequisites and returns a dry-run plan showing what the provisioning workflow *would* do, without making any Azure changes. Always available — not gated by `VENDING_MOCK_MODE`.

The ServiceNow gate check (if configured) is executed with a **real HTTP call** during preflight so you get an accurate ticket validation result.

#### Request body

```json
{
  "subscription_id": "00000000-0000-0000-0000-000000000001",
  "subscription_name": "my-new-subscription",
  "management_group_id": "ITL-Development",
  "snow_ticket": "RITM0041872"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `subscription_id` | `string` | Yes | Subscription ID to simulate provisioning for |
| `subscription_name` | `string` | No | Display name of the subscription |
| `management_group_id` | `string` | No | Target management group (subscription tags take precedence) |
| `snow_ticket` | `string` | No | ServiceNow ticket number to validate. Overrides the `itl-snow-ticket` tag on the subscription for this preflight run only. |

#### Response `200 OK`

```json
{
  "gate_passed": true,
  "steps": [
    { "description": "[SNOW gate] Ticket 'RITM0041872' validated — approval='approved'", "status": "planned" },
    { "description": "[STEP_MG] Move subscription to management group 'ITL-Development'", "status": "planned" },
    { "description": "[STEP_RBAC] Assign Owner to platform SPN", "status": "planned" }
  ],
  "errors": [],
  "summary": "3 steps planned, 0 blocked"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `gate_passed` | `boolean` | `true` if all gate checks passed |
| `steps` | `list` | Ordered list of `{description, status}` entries. `status` is `"planned"` for steps that would run or `"blocked"` for steps skipped due to a gate failure. |
| `errors` | `list[string]` | Error messages from failed gate checks or step simulations |
| `summary` | `string` | Human-readable summary line |

---

### `POST /webhook/replay`

Idempotent re-trigger of the provisioning workflow for any subscription, without requiring a real Event Grid event. All provisioning steps are safe to repeat — duplicate management group moves and role assignments are no-ops in Azure.

Always available (not gated by `VENDING_MOCK_MODE`). Optionally secured via the `x-replay-secret` header checked against `VENDING_WORKER_SECRET`.

#### Headers

| Header | Required | Description |
|--------|----------|-------------|
| `x-replay-secret` | Conditional | Must match `VENDING_WORKER_SECRET` when that setting is non-empty. |

#### Request body

```json
{
  "subscription_id": "00000000-0000-0000-0000-000000000001",
  "subscription_name": "my-subscription",
  "management_group_id": "ITL-Development",
  "dry_run": false
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `subscription_id` | `string` | Yes | — | Subscription ID to provision |
| `subscription_name` | `string` | No | `""` | Display name |
| `management_group_id` | `string` | No | `""` | Target management group (subscription tags take precedence) |
| `dry_run` | `boolean` | No | `false` | When `true`, simulate the workflow without making any Azure changes |

#### Response `200 OK`

```json
{
  "status": "ok",
  "subscription_id": "00000000-0000-0000-0000-000000000001",
  "errors": [],
  "plan": ["[STEP_MG] Moved to ITL-Development", "[STEP_RBAC] Assigned Owner to platform SPN"]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | `string` | `"ok"` on success, `"error"` if any provisioning step failed |
| `subscription_id` | `string` | Echo of the requested subscription ID |
| `errors` | `list[string]` | Error messages from failed steps |
| `plan` | `list[string]` | Human-readable log of steps that ran (populated in `dry_run` mode and live runs) |

#### Error responses

| Code | Reason |
|------|--------|
| `401 Unauthorized` | `x-replay-secret` header does not match `VENDING_WORKER_SECRET` |

---

### `POST /worker/process-job` *(queue strategy only)*

Processes a single provisioning job dequeued from Azure Storage Queue. Only mounted when `VENDING_RETRY_STRATEGY=queue`.

Designed to be called by a queue trigger (Azure Functions, ACA Job, or Kubernetes CronJob) that passes the raw queue message payload in the request body.

A `500` response leaves the message in the queue so the caller can retry. After `VENDING_QUEUE_MAX_DELIVERY_COUNT` failures the worker moves the message to the dead-letter queue and returns `200`.

#### Headers

| Header | Required | Description |
|--------|----------|-------------|
| `x-worker-secret` | Conditional | Must match `VENDING_WORKER_SECRET` when that setting is non-empty. |

#### Request body

```json
{
  "message": "<base64-encoded ProvisioningJob JSON>",
  "delivery_count": 1
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `message` | `string` | Yes | — | Base64-encoded JSON of a `ProvisioningJob` object |
| `delivery_count` | `integer` | No | `1` | Number of times this message has been delivered. When this exceeds `VENDING_QUEUE_MAX_DELIVERY_COUNT` the job is dead-lettered. |

**`ProvisioningJob` JSON fields:**

| Field | Type | Description |
|-------|------|-------------|
| `subscription_id` | `string` | Azure subscription ID |
| `subscription_name` | `string` | Display name |
| `management_group_id` | `string` | Target management group |
| `attempt` | `integer` | Attempt counter (informational) |
| `job_id` | `string` | UUID assigned at enqueue time (idempotency key) |

#### Response `200 OK` — success

```json
{"status": "ok", "subscription_id": "00000000-0000-0000-0000-000000000001"}
```

#### Response `200 OK` — dead-lettered

```json
{"status": "dead_lettered", "subscription_id": "00000000-0000-0000-0000-000000000001"}
```

#### Response `500` — provisioning failed (message will be retried)

```json
{"detail": "Provisioning failed"}
```

#### Error responses

| Code | Reason |
|------|--------|
| `401 Unauthorized` | `x-worker-secret` header does not match `VENDING_WORKER_SECRET` |
| `422 Unprocessable Entity` | `message` field is not valid base64 or not valid JSON |

---

### `POST /webhook/test` *(mock mode only)*

Triggers the provisioning workflow directly without a real Event Grid event. Only available when `VENDING_MOCK_MODE=true`.

#### Request body

```json
{
  "subscription_id": "00000000-0000-0000-0000-000000000001",
  "subscription_name": "my-test-subscription",
  "management_group_id": "ITL-Development",
  "dry_run": false
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `subscription_id` | `string` | Yes | — | Subscription ID to provision |
| `subscription_name` | `string` | No | `mock-subscription` | Display name |
| `management_group_id` | `string` | No | `""` | Target management group (overridden by subscription tags) |
| `dry_run` | `boolean` | No | `false` | When `true`, log what would happen without making any Azure calls or outbound HTTP requests |

**Response** `200 OK`

```json
{
  "status": "ok",
  "message": "...",
  "subscription_id": "00000000-0000-0000-0000-000000000001"
}
```

`status` is `"error"` if the provisioning workflow returned any errors. When `dry_run` was `true`, all Azure mutations are skipped and only log output is produced.

---

## Configuration

### `GET /config`

Returns the active service configuration with all secret fields redacted. Useful for verifying which settings are active without exposing credentials.

The fields `azure_client_secret`, `worker_secret`, and `event_grid_sas_key` are replaced with `"***"` when non-empty.

**Response** `200 OK`

```json
{
  "azure_tenant_id": "00000000-0000-0000-0000-000000000001",
  "azure_client_id": "my-client-id",
  "azure_client_secret": "***",
  "retry_strategy": "queue",
  "provisioning_queue_name": "vending-jobs",
  "provisioning_dlq_name": "vending-jobs-dlq",
  "worker_secret": "***",
  "event_grid_sas_key": "***",
  "mock_mode": false
}
```

---

## Jobs API

The `/jobs/*` endpoints provide visibility into the Azure Storage Queue used by the `queue` retry strategy. They are always registered but are most useful when `VENDING_RETRY_STRATEGY=queue`.

All `/jobs/*` endpoints connect to Azure Storage using the same credentials as the main service (`VENDING_STORAGE_CONNECTION_STRING` or `DefaultAzureCredential` + `VENDING_STORAGE_ACCOUNT_NAME`).

---

### `GET /jobs/stats`

Returns approximate message counts for both the provisioning queue and the dead-letter queue.

**Response** `200 OK`

```json
{
  "provisioning": {
    "queue": "vending-jobs",
    "approximate_message_count": 3
  },
  "dead_letter": {
    "queue": "vending-jobs-dlq",
    "approximate_message_count": 1
  }
}
```

If a queue cannot be reached, the response includes `"error": "<message>"` in place of `approximate_message_count`.

---

### `GET /jobs/list`

Peeks the top N messages in the provisioning queue without removing them.

#### Query parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `count` | `5` | Number of messages to peek (1–32) |

**Response** `200 OK`

```json
{
  "queue": "vending-jobs",
  "count": 1,
  "messages": [
    {
      "job_id": "abc123",
      "subscription_id": "00000000-0000-0000-0000-000000000001",
      "subscription_name": "my-subscription",
      "management_group_id": "ITL-Development",
      "attempt": 1
    }
  ]
}
```

---

### `GET /jobs/dlq`

Peeks the top N messages in the dead-letter queue. Response shape is identical to `/jobs/list`.

#### Query parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `count` | `5` | Number of messages to peek |

---

### `DELETE /jobs/dlq`

Clears **all** messages from the dead-letter queue. This is a destructive, irreversible operation.

**Response** `200 OK`

```json
{"queue": "vending-jobs-dlq", "deleted": 3}
```

---

### `POST /jobs/enqueue`

Enqueues a provisioning job directly to the provisioning queue, bypassing the Event Grid webhook. Useful for manual re-queuing or testing without a real Event Grid event.

**Response** `202 Accepted`

#### Request body

```json
{
  "subscription_id": "00000000-0000-0000-0000-000000000001",
  "subscription_name": "my-subscription",
  "management_group_id": "ITL-Development",
  "job_id": "",
  "attempt": 1
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `subscription_id` | `string` | Yes | — | Azure subscription ID |
| `subscription_name` | `string` | Yes | — | Display name |
| `management_group_id` | `string` | No | `""` | Target management group |
| `job_id` | `string` | No | auto | Custom job ID; a UUID is generated when empty |
| `attempt` | `integer` | No | `1` | Attempt counter (informational) |

**Response** `202 Accepted`

```json
{
  "job_id": "abc123",
  "message_id": "d3b07384-d113-4ec6-b7b7-d85b72a2f51b",
  "queue": "vending-jobs"
}
```

---

### `GET /jobs/{job_id}`

Looks up a specific job by ID, peeking across both the provisioning queue and the dead-letter queue (up to 32 messages each).

**Response** `200 OK` — found

```json
{
  "found": true,
  "queue": "vending-jobs",
  "job": {
    "job_id": "abc123",
    "subscription_id": "00000000-0000-0000-0000-000000000001",
    "subscription_name": "my-subscription",
    "management_group_id": "ITL-Development",
    "attempt": 1
  }
}
```

**Response** `200 OK` — not found

```json
{"found": false, "queue": null, "job": null}
```

---

## OpenAPI / Swagger UI

When the service is running locally, open the following URLs in your browser:

| URL | Description |
|-----|-------------|
| `http://localhost:8000/docs` | Swagger UI (interactive) |
| `http://localhost:8000/redoc` | ReDoc (read-only) |
| `http://localhost:8000/openapi.json` | Raw OpenAPI 3.0 schema |
