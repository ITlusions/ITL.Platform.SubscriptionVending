# Contributing to ITL.Platform.SubscriptionVending

Thank you for your interest in contributing! This guide covers everything you need to get started.

---

## Development setup

### Prerequisites

- Python 3.12+
- [Hatch](https://hatch.pypa.io/) (`pip install hatch`)
- Docker (optional, for container testing)

### Install

```bash
git clone https://github.com/ITlusions/ITL.Platform.SubscriptionVending.git
cd ITL.Platform.SubscriptionVending
pip install -e ".[dev]"
```

### Run tests

```bash
pytest
```

### Run locally

```bash
cp .env.example .env
# Edit .env — set at minimum VENDING_AZURE_TENANT_ID
uvicorn subscription_vending.main:app --reload --port 8000
```

### Run with Docker Compose

```bash
docker-compose up --build
```

---

## Branching strategy

| Branch | Purpose |
|---|---|
| `main` | Production-ready code. Every merge triggers a patch version bump and container push. |
| `develop` | Integration branch for ongoing work. |
| `feature/<short-desc>` | New features or improvements. Branch from `develop`. |
| `fix/<short-desc>` | Bug fixes. Branch from `main` for hotfixes, `develop` otherwise. |

---

## Commit conventions

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short description>

[optional body]

[optional footer]
```

**Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `ci`, `chore`  
**Scope:** `workflow`, `handlers`, `azure`, `config`, `ci`, `docs`, `k8s`, `infra`

Examples:

```
feat(workflow): add step 7 for tagging completion
fix(handlers): return 400 on missing subscription_id
docs(readme): update quickstart section
ci: pin actions to latest Node.js 24 compatible versions
```

---

## Pull requests

1. Fork the repo and create a branch from `develop` (or `main` for hotfixes)
2. Make your changes — keep each PR focused on a single concern
3. Run `pytest` and ensure all tests pass
4. Update relevant docs in `/docs` if behaviour changes
5. Update `CHANGELOG.md` under `[Unreleased]`
6. Open a PR against `develop` with a clear description

---

## Coding standards

- **Python 3.12+** with type hints on all public functions
- **async/await** for all route handlers and Azure SDK calls
- Pydantic v2 models for all request/response schemas
- No secrets in environment variables — use `DefaultAzureCredential`
- Each provisioning step in `workflow.py` must be independent (failures are logged, not raised)

---

## Reporting bugs

Use the [Bug Report](.github/ISSUE_TEMPLATE/bug_report.md) issue template.

## Requesting features

Use the [Feature Request](.github/ISSUE_TEMPLATE/feature_request.md) issue template.
