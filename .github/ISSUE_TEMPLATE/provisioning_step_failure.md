---
name: Provisioning step failure
about: A specific provisioning step failed for a subscription
labels: bug, provisioning
---

## Affected step

<!-- Tick the step that failed -->

- [ ] Step 0 — Read subscription tags
- [ ] Step 1 — Move to management group
- [ ] Step 2 — Attach ITL Foundation Policy Initiative
- [ ] Step 3 — Create RBAC role assignments
- [ ] Step 4 — Assign default Azure Policies
- [ ] Step 5 — Create cost budget alert
- [ ] Step 6 — Publish outbound notification event

## Subscription details

- **Subscription ID:** <!-- e.g. 00000000-0000-0000-0000-000000000001 -->
- **Subscription name:** 
- **Environment tag (`itl-environment`):** 
- **Other relevant tags:** 

## Error output

```json
<!-- Paste the ProvisioningResult or step error from the response body or logs -->
```

## Service logs

```
<!-- Paste relevant structured log lines here -->
```

## Expected outcome

<!-- What should have happened for this step -->

## Deployment context

- Service version:
- Deployment: <!-- Docker / Kubernetes / local -->
- Mock mode enabled: <!-- yes / no -->
