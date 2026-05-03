---
layout: default
title: Kubernetes Deployment
---

# Kubernetes Deployment

The `k8s/` directory contains Kubernetes manifests for deploying the service on any Kubernetes cluster, including AKS.

---

## Manifests

| File | Description |
|------|-------------|
| `k8s/deployment.yaml` | Deployment with 1 replica, liveness/readiness probes on `/health`, and resource limits |
| `k8s/service.yaml` | ClusterIP Service exposing port 8000 |
| `k8s/configmap.yaml` | Non-secret environment variables |

Sensitive values (tenant ID, client credentials, Event Grid SAS key) are read from a Kubernetes Secret, not the ConfigMap.

---

## Prerequisites

- A running Kubernetes cluster (AKS, kind, etc.)
- `kubectl` configured to target the cluster
- A container registry accessible from the cluster (e.g. Azure Container Registry)
- The service container image built and pushed to the registry

---

## 1. Build and push the container image

```bash
# Build
docker build -t myacr.azurecr.io/itl-subscription-vending:latest .

# Push
docker push myacr.azurecr.io/itl-subscription-vending:latest
```

Update the `image:` field in `k8s/deployment.yaml` to match your registry and tag.

---

## 2. Create the Secret

The following secret keys are read by the Deployment:

| Secret key | Maps to env var | Required |
|-----------|----------------|----------|
| `azure-tenant-id` | `VENDING_AZURE_TENANT_ID` | Yes |
| `azure-client-id` | `VENDING_AZURE_CLIENT_ID` | No (Managed Identity fallback) |
| `azure-client-secret` | `VENDING_AZURE_CLIENT_SECRET` | No (Managed Identity fallback) |
| `event-grid-sas-key` | `VENDING_EVENT_GRID_SAS_KEY` | No |

**Minimum secret (Managed Identity authentication):**

```bash
kubectl create secret generic subscription-vending-secret \
  --from-literal=azure-tenant-id=<your-tenant-id>
```

**Full secret (service principal authentication):**

```bash
kubectl create secret generic subscription-vending-secret \
  --from-literal=azure-tenant-id=<your-tenant-id> \
  --from-literal=azure-client-id=<your-client-id> \
  --from-literal=azure-client-secret=<your-client-secret> \
  --from-literal=event-grid-sas-key=<your-sas-key>
```

---

## 3. Update the ConfigMap

Edit `k8s/configmap.yaml` to set non-secret environment variables for your environment. Example values to customise:

```yaml
data:
  VENDING_ROOT_MANAGEMENT_GROUP: "ITL"
  VENDING_MG_PRODUCTION: "ITL-Production"
  VENDING_MG_STAGING: "ITL-Staging"
  VENDING_MG_DEVELOPMENT: "ITL-Development"
  VENDING_MG_SANDBOX: "ITL-Sandbox"
  VENDING_PLATFORM_SPN_OBJECT_ID: "<object-id>"
  VENDING_OPS_GROUP_OBJECT_ID: "<object-id>"
  VENDING_SECURITY_GROUP_OBJECT_ID: "<object-id>"
  VENDING_FINOPS_GROUP_OBJECT_ID: "<object-id>"
  VENDING_DEFAULT_ALERT_EMAIL: "alerts@example.com"
  VENDING_AUTHORIZATION_SERVICE_URL: "http://itl-authorization:8004"
  VENDING_KEYCLOAK_URL: "https://keycloak.example.com"
  VENDING_KEYCLOAK_REALM: "ITL"
  VENDING_MOCK_MODE: "false"
```

---

## 4. Apply the manifests

```bash
kubectl apply -f k8s/
```

This creates the Deployment, Service, and ConfigMap in the current namespace.

To target a specific namespace:

```bash
kubectl apply -f k8s/ -n <namespace>
```

---

## 5. Verify the deployment

```bash
# Check pod status
kubectl get pods -l app=subscription-vending

# Check logs
kubectl logs -l app=subscription-vending --tail=50

# Check liveness
kubectl exec -it <pod-name> -- curl http://localhost:8000/health
```

The service is healthy when `/health` returns `{"status": "ok"}`.

---

## 6. Expose the webhook endpoint

The Event Grid webhook requires a publicly reachable HTTPS endpoint. Options:

- **Azure Application Gateway** — recommended for production AKS workloads
- **NGINX Ingress Controller** with a valid TLS certificate
- **Azure API Management** — for API gateway patterns

Example Ingress (requires an Ingress controller and cert-manager):

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: subscription-vending
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  tls:
    - hosts:
        - subvending.example.com
      secretName: subvending-tls
  rules:
    - host: subvending.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: subscription-vending
                port:
                  number: 8000
```

After exposing the service, configure the Event Grid subscription to deliver events to `https://subvending.example.com/webhook/`.

---

## Resource limits

The Deployment configures the following resource limits (adjust as needed):

| | Request | Limit |
|--|---------|-------|
| CPU | 100m | 500m |
| Memory | 256Mi | 512Mi |

---

## Updating the deployment

To roll out a new container image:

```bash
kubectl set image deployment/subscription-vending \
  subscription-vending=myacr.azurecr.io/itl-subscription-vending:<new-tag>
```

Or update `k8s/deployment.yaml` and re-apply:

```bash
kubectl apply -f k8s/deployment.yaml
```
