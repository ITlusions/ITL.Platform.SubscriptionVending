"""Azure Policy assignment helper."""

from __future__ import annotations

import asyncio
import logging
import uuid

from ..config import Settings

logger = logging.getLogger(__name__)

# Default policy definition IDs to assign (e.g. Azure Security Benchmark)
DEFAULT_POLICY_DEFINITION_IDS: list[str] = []


def _get_credential(settings: Settings):
    from azure.identity import ManagedIdentityCredential, ClientSecretCredential  # noqa: PLC0415

    if settings.azure_client_id and settings.azure_client_secret:
        return ClientSecretCredential(
            tenant_id=settings.azure_tenant_id,
            client_id=settings.azure_client_id,
            client_secret=settings.azure_client_secret,
        )
    return ManagedIdentityCredential()


async def assign_default_policies(
    subscription_id: str,
    settings: Settings,
    policy_definition_ids: list[str] | None = None,
) -> None:
    """
    Assign default Azure Policy definitions to the subscription scope.

    If *policy_definition_ids* is empty/None the module-level
    ``DEFAULT_POLICY_DEFINITION_IDS`` list is used (which ships empty so that
    callers can override it without code changes).

    Policy assignments are performed via the Azure Resource Management REST API
    using the ``azure-mgmt-resource`` package's ``ResourceManagementClient``
    (the standalone ``PolicyClient`` was removed from ``azure-mgmt-resource``
    in v23+).
    """
    policies = policy_definition_ids or DEFAULT_POLICY_DEFINITION_IDS
    scope = f"/subscriptions/{subscription_id}"

    if not policies:
        logger.debug("No default policies configured — skipping policy assignment")
        return

    credential = _get_credential(settings)

    def _assign() -> None:
        # azure-mgmt-resource v23+ exposes policy assignments via the
        # resource-management client's policy_assignments property.
        from azure.mgmt.resource import ResourceManagementClient  # noqa: PLC0415

        client = ResourceManagementClient(
            credential=credential,
            subscription_id=subscription_id,
        )
        for policy_id in policies:
            assignment_name = str(uuid.uuid4())[:24]
            client.policy_assignments.create(  # type: ignore[attr-defined]
                scope=scope,
                policy_assignment_name=assignment_name,
                parameters={
                    "properties": {
                        "policyDefinitionId": policy_id,
                        "displayName": f"ITL default policy {assignment_name}",
                    }
                },
            )
            logger.debug(
                "Policy %s assigned on subscription %s", policy_id, subscription_id
            )

    await asyncio.to_thread(_assign)
