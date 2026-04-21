"""Azure RBAC role-assignment helper."""

from __future__ import annotations

import asyncio
import logging
import uuid

from azure.identity import ManagedIdentityCredential, ClientSecretCredential
from azure.mgmt.authorization import AuthorizationManagementClient

from ..config import Settings

logger = logging.getLogger(__name__)

# Built-in role definition IDs (Contributor by default)
DEFAULT_ROLE_DEFINITION_IDS: list[str] = [
    "b24988ac-6180-42a0-ab88-20f7382dd24c",  # Contributor
]


def _get_credential(settings: Settings):
    if settings.azure_client_id and settings.azure_client_secret:
        return ClientSecretCredential(
            tenant_id=settings.azure_tenant_id,
            client_id=settings.azure_client_id,
            client_secret=settings.azure_client_secret,
        )
    return ManagedIdentityCredential()


async def assign_default_roles(
    subscription_id: str,
    settings: Settings,
    principal_id: str = "",
    role_definition_ids: list[str] | None = None,
) -> None:
    """
    Assign default RBAC roles on the subscription scope.

    *principal_id* must be the object ID of the Azure AD principal (user,
    group, or service principal) to which the roles will be assigned.
    When running with a service principal the caller should pass the SP's
    object ID explicitly.  When running with Managed Identity the object ID
    must be provided by the caller (e.g. retrieved from the Container App's
    identity output) because ``azure_client_id`` is not the same as the
    object ID required by the role-assignment API.

    If *principal_id* is empty and ``settings.azure_client_id`` is also empty
    (pure Managed Identity scenario) the assignment is skipped with a warning,
    since there is no object ID available to assign roles to.
    """
    resolved_principal_id = principal_id or settings.azure_client_id
    if not resolved_principal_id:
        logger.warning(
            "No principal_id available for RBAC role assignment on subscription %s — "
            "skipping. Provide principal_id explicitly or set VENDING_AZURE_CLIENT_ID.",
            subscription_id,
        )
        return

    credential = _get_credential(settings)
    roles = role_definition_ids or DEFAULT_ROLE_DEFINITION_IDS
    scope = f"/subscriptions/{subscription_id}"

    def _assign() -> None:
        client = AuthorizationManagementClient(
            credential=credential,
            subscription_id=subscription_id,
        )
        for role_id in roles:
            role_def_id = (
                f"/subscriptions/{subscription_id}/providers/Microsoft.Authorization"
                f"/roleDefinitions/{role_id}"
            )
            assignment_name = str(uuid.uuid4())
            client.role_assignments.create(
                scope=scope,
                role_assignment_name=assignment_name,
                parameters={
                    "properties": {
                        "roleDefinitionId": role_def_id,
                        "principalId": resolved_principal_id,
                    }
                },
            )
            logger.debug(
                "Role %s assigned on subscription %s", role_id, subscription_id
            )

    await asyncio.to_thread(_assign)
