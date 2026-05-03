# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | Yes |

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Report vulnerabilities privately via [GitHub Security Advisories](https://github.com/ITlusions/ITL.Platform.SubscriptionVending/security/advisories/new).

Include as much detail as possible:

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

We aim to acknowledge reports within **48 hours** and provide a resolution timeline within **7 days**.

## Security considerations for this service

- **Credential management** — the service uses `DefaultAzureCredential`. Never pass credentials via environment variables in production; use Managed Identity or Workload Identity instead.
- **Event Grid SAS key** — configure `VENDING_EVENT_GRID_SAS_KEY` to validate incoming webhook deliveries and reject unauthenticated requests.
- **Mock mode** — `VENDING_MOCK_MODE=true` enables the unauthenticated `/webhook/test` endpoint. Never enable this in production.
- **RBAC scope** — the service principal requires `Owner` at the subscription scope to perform role assignments. Limit this to the management groups in scope, not the root tenant.
