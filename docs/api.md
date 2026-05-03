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

### `POST /webhook/test` *(mock mode only)*

Triggers the provisioning workflow directly without a real Event Grid event. Only available when `VENDING_MOCK_MODE=true`.

#### Request body

```json
{
  "subscription_id": "00000000-0000-0000-0000-000000000001",
  "subscription_name": "my-test-subscription",
  "management_group_id": "ITL-Development"
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `subscription_id` | `string` | Yes | — | Subscription ID to provision |
| `subscription_name` | `string` | No | `mock-subscription` | Display name |
| `management_group_id` | `string` | No | `""` | Target management group (overridden by subscription tags) |

**Response** `200 OK`

```json
{
  "status": "ok",
  "message": "...",
  "subscription_id": "00000000-0000-0000-0000-000000000001"
}
```

`status` is `"error"` if the provisioning workflow returned any errors.

---

## OpenAPI / Swagger UI

When the service is running locally, open the following URLs in your browser:

| URL | Description |
|-----|-------------|
| `http://localhost:8000/docs` | Swagger UI (interactive) |
| `http://localhost:8000/redoc` | ReDoc (read-only) |
| `http://localhost:8000/openapi.json` | Raw OpenAPI 3.0 schema |
