# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

## [0.1.0] — 2026-05-03

### Added
- FastAPI microservice listening to Azure Event Grid `Microsoft.Resources.ResourceActionSuccess` events
- 7-step provisioning workflow: tag reading, management group placement, Foundation Policy Initiative attachment, RBAC role assignments, Azure Policy assignment, cost budget alerts, outbound `SubscriptionProvisioned` notification
- Tag-driven configuration via subscription tags (`itl-environment`, `itl-budget`, `itl-owner`, etc.)
- Mock endpoint (`POST /webhook/test`) for local testing without a real Event Grid delivery
- `DefaultAzureCredential` auth — supports Managed Identity and Workload Identity out of the box
- Multi-stage Dockerfile for production container builds
- Docker Compose setup for local development
- Kubernetes manifests (`deployment.yaml`, `service.yaml`, `configmap.yaml`)
- Azure Bicep infrastructure templates (`infra/`)
- Hatch-based build system with dynamic versioning via `__about__.py`
- GitHub Actions pipeline — test, version bump, container build & push to GHCR
- Dedicated GitHub Pages publish workflow (Jekyll, dark theme)
- Full documentation site at [itlusions.github.io/ITL.Platform.SubscriptionVending](https://itlusions.github.io/ITL.Platform.SubscriptionVending/)
- Pytest test suite covering app, event grid, notifications, RBAC, tags, and workflow

[Unreleased]: https://github.com/ITlusions/ITL.Platform.SubscriptionVending/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ITlusions/ITL.Platform.SubscriptionVending/releases/tag/v0.1.0
