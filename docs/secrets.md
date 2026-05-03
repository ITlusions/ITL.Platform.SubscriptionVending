---
layout: default
title: Secrets Handling
---

# Secrets Handling

This document defines which values are considered secrets, how they are kept out of source control, and how they are injected into the service in each supported deployment context.

---

## What counts as a secret

| Variable | Why it is a secret |
|----------|--------------------|
| `VENDING_AZURE_TENANT_ID` | Identifies the Azure AD directory; leaking it narrows the attack surface for tenant-level attacks |
| `VENDING_AZURE_CLIENT_ID` | Service principal identity used to authenticate against Azure APIs |
| `VENDING_AZURE_CLIENT_SECRET` | Service principal password; grants full access to all Azure APIs the SPN has been granted |
| `VENDING_EVENT_GRID_SAS_KEY` | Shared-access-signature key that authorises Event Grid to deliver events to the webhook; any holder can send arbitrary events |

The following variables are **not** secrets — they are IDs, URLs, and configuration flags that are safe to store in source-controlled ConfigMaps, deployment manifests, or application settings:

`VENDING_ROOT_MANAGEMENT_GROUP`, `VENDING_ENVIRONMENT_MG_MAPPING`, `VENDING_PLATFORM_SPN_OBJECT_ID`, `VENDING_OPS_GROUP_OBJECT_ID`, `VENDING_SECURITY_GROUP_OBJECT_ID`, `VENDING_FINOPS_GROUP_OBJECT_ID`, `VENDING_DEFAULT_ALERT_EMAIL`, `VENDING_AUTHORIZATION_SERVICE_URL`, `VENDING_KEYCLOAK_URL`, `VENDING_KEYCLOAK_REALM`, `VENDING_MOCK_MODE`, tag-key overrides.

---

## 1. Local development (`.env` file)

**Never commit `.env` to source control.** The repository's `.gitignore` already ignores it:

```
# Environment files (keep .env.example, ignore .env)
.env
```

### Setup

```bash
cp .env.example .env
# Edit .env and fill in secrets for your local environment
```

`.env.example` is committed and annotated with every supported variable. It contains no real values — only placeholders such as `<your-tenant-id>`.

### How secrets are loaded

`pydantic-settings` reads `.env` automatically via:

```python
model_config = SettingsConfigDict(env_file=".env", env_prefix="VENDING_")
```

Variables already present in the shell environment take precedence over `.env` entries, so you can override individual values without editing the file.

### Minimum required secret

```env
VENDING_AZURE_TENANT_ID=<your-tenant-id>
```

For a fully local/mock run that does not call Azure APIs, any non-empty string is acceptable.

---

## 2. Docker Compose

`docker-compose.yml` loads the local `.env` file using `env_file`:

```yaml
services:
  subscription-vending:
    env_file:
      - .env
    environment:
      VENDING_MOCK_MODE: "true"   # non-secret override only
```

- All secrets come from `.env` (never hard-coded in `docker-compose.yml`).
- The `environment:` block is reserved for non-secret overrides that must be explicit for the Compose profile (here, enabling mock mode).
- `.env` is gitignored and must be created locally before running `docker-compose up`.

### Quick start

```bash
cp .env.example .env
# Set at minimum: VENDING_AZURE_TENANT_ID=<your-tenant-id>
docker-compose up --build
```

---

## 3. Kubernetes

Secrets are stored in a `kubernetes.io/Opaque` Secret object, **not** in the ConfigMap or any YAML file committed to source control.

### Secret keys

| Secret key | Mapped to env var | Required |
|------------|-------------------|----------|
| `azure-tenant-id` | `VENDING_AZURE_TENANT_ID` | **Yes** |
| `azure-client-id` | `VENDING_AZURE_CLIENT_ID` | No (Managed Identity fallback) |
| `azure-client-secret` | `VENDING_AZURE_CLIENT_SECRET` | No (Managed Identity fallback) |
| `event-grid-sas-key` | `VENDING_EVENT_GRID_SAS_KEY` | No |

### Create the Secret

**Minimum (Managed Identity authentication):**

```bash
kubectl create secret generic subscription-vending-secret \
  --from-literal=azure-tenant-id=<your-tenant-id>
```

**Full (service principal authentication):**

```bash
kubectl create secret generic subscription-vending-secret \
  --from-literal=azure-tenant-id=<your-tenant-id> \
  --from-literal=azure-client-id=<your-client-id> \
  --from-literal=azure-client-secret=<your-client-secret> \
  --from-literal=event-grid-sas-key=<your-sas-key>
```

### How secrets are wired into the pod

`k8s/deployment.yaml` injects each secret key individually via `secretKeyRef`, which means Kubernetes decrypts and injects only the named keys — no entire Secret is mounted as a volume or exposed as environment data beyond what is explicitly declared:

```yaml
env:
  - name: VENDING_AZURE_TENANT_ID
    valueFrom:
      secretKeyRef:
        name: subscription-vending-secret
        key: azure-tenant-id
  - name: VENDING_AZURE_CLIENT_ID
    valueFrom:
      secretKeyRef:
        name: subscription-vending-secret
        key: azure-client-id
        optional: true
  - name: VENDING_AZURE_CLIENT_SECRET
    valueFrom:
      secretKeyRef:
        name: subscription-vending-secret
        key: azure-client-secret
        optional: true
  - name: VENDING_EVENT_GRID_SAS_KEY
    valueFrom:
      secretKeyRef:
        name: subscription-vending-secret
        key: event-grid-sas-key
        optional: true
```

Non-secret configuration is sourced from the ConfigMap via `envFrom.configMapRef`.

### Production hardening recommendations

- Enable **Kubernetes Secrets encryption at rest** (`EncryptionConfiguration` with an AES-CBC or KMS provider).
- In AKS, use the [Secrets Store CSI Driver](https://secrets-store-csi-driver.sigs.k8s.io/) with Azure Key Vault provider to pull secrets directly from Key Vault — this avoids storing secret values in etcd entirely.
- Apply RBAC (`Role`/`RoleBinding`) to restrict which service accounts and users can `get`/`list` the `subscription-vending-secret` object.

---

## 4. Azure infrastructure (Bicep)

The Bicep template (`infra/main.bicep`) declares `eventGridSasKey` as a `@secure()` parameter so that Azure Resource Manager never logs or exposes its value in deployment history:

```bicep
@description('SAS key for Event Grid delivery')
@secure()
param eventGridSasKey string
```

The parameter file (`infra/params.bicepparam`) intentionally omits the secret value:

```
// eventGridSasKey should be supplied via --parameters or Key Vault reference
```

### Supplying the secret at deploy time

**Inline (CI/CD pipeline — value comes from a pipeline secret):**

```bash
az deployment group create \
  --resource-group rg-itl-subvending \
  --template-file infra/main.bicep \
  --parameters infra/params.bicepparam \
  --parameters eventGridSasKey="$EVENT_GRID_SAS_KEY"
```

**Azure Key Vault reference (recommended for production):**

```bash
az deployment group create \
  --resource-group rg-itl-subvending \
  --template-file infra/main.bicep \
  --parameters infra/params.bicepparam \
  --parameters "eventGridSasKey=$(az keyvault secret show \
      --vault-name <vault-name> \
      --name event-grid-sas-key \
      --query value -o tsv)"
```

Alternatively, use a [Key Vault dynamic reference](https://learn.microsoft.com/azure/azure-resource-manager/templates/key-vault-parameter) inside a `bicepparam` file to avoid the secret ever touching the shell:

```bicep
// params.bicepparam (not committed with a real secret)
param eventGridSasKey = getSecret('<subscription-id>', '<rg>', '<vault-name>', 'event-grid-sas-key')
```

---

## Summary

| Deployment context | Secret storage | Mechanism |
|-------------------|---------------|-----------|
| Local development | `.env` (gitignored) | `pydantic-settings` reads `env_file=".env"` |
| Docker Compose | `.env` (gitignored) | `env_file:` directive in `docker-compose.yml` |
| Kubernetes | `kubernetes.io/Opaque` Secret | `secretKeyRef` in `k8s/deployment.yaml` |
| Azure (Bicep) | Passed at deploy time / Key Vault reference | `@secure()` Bicep parameter |

The golden rule in every context: **secrets never appear in files that are committed to source control.**
