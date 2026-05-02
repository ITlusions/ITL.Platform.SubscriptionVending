"""Azure RBAC role-assignment helper."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import NamedTuple

from azure.identity import ManagedIdentityCredential, ClientSecretCredential
from azure.mgmt.authorization import AuthorizationManagementClient
from azure.mgmt.authorization.models import RoleAssignmentCreateParameters

from ..config import Settings

logger = logging.getLogger(__name__)

# Built-in role definition IDs (Contributor by default)
DEFAULT_ROLE_DEFINITION_IDS: list[str] = [
    "b24988ac-6180-42a0-ab88-20f7382dd24c",  # Contributor
]

# Azure built-in role definition IDs
ROLE_DEFINITIONS: dict[str, str] = {
    "Owner":                "8e3af657-a8ff-443c-a75c-2fe8c4bcb635",
    "Contributor":          "b24988ac-6180-42a0-ab88-20f7382dd24c",
    "SecurityReader":       "39bc4728-0917-49c7-9d2c-d95423bc2eb4",
    "CostManagementReader": "72fafb9e-0641-4937-9268-a91bfd8191a3",
}


class RoleAssignmentSpec(NamedTuple):
    principal_id:         str
    role_definition_name: str
    description:          str


def _get_default_role_assignments(settings: Settings) -> list[RoleAssignmentSpec]:
    """Return default role assignments based on configuration."""
    assignments: list[RoleAssignmentSpec] = []

    if getattr(settings, "platform_spn_object_id", ""):
        assignments.append(RoleAssignmentSpec(
            principal_id=settings.platform_spn_object_id,
            role_definition_name="Owner",
            description="ITL Platform Service Principal",
        ))

    if getattr(settings, "ops_group_object_id", ""):
        assignments.append(RoleAssignmentSpec(
            principal_id=settings.ops_group_object_id,
            role_definition_name="Contributor",
            description="ITL Operations group",
        ))

    if getattr(settings, "security_group_object_id", ""):
        assignments.append(RoleAssignmentSpec(
            principal_id=settings.security_group_object_id,
            role_definition_name="SecurityReader",
            description="ITL Security group",
        ))

    if getattr(settings, "finops_group_object_id", ""):
        assignments.append(RoleAssignmentSpec(
            principal_id=settings.finops_group_object_id,
            role_definition_name="CostManagementReader",
            description="ITL FinOps group",
        ))

    return assignments


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


async def create_initial_rbac(
    subscription_id: str,
    settings: Settings,
) -> list[str]:
    """
    Create standard role assignments on a new subscription.

    Iterates over all principals configured in *settings* and creates one role
    assignment per principal.  Errors for individual assignments are logged as
    warnings and do not abort the loop.

    Returns a list of successfully created role assignment IDs.
    """
    credential = _get_credential(settings)
    client = AuthorizationManagementClient(credential, subscription_id)
    scope = f"/subscriptions/{subscription_id}"

    role_assignment_ids: list[str] = []
    specs = _get_default_role_assignments(settings)

    for spec in specs:
        role_def_id = (
            f"/subscriptions/{subscription_id}"
            f"/providers/Microsoft.Authorization/roleDefinitions"
            f"/{ROLE_DEFINITIONS[spec.role_definition_name]}"
        )
        assignment_name = str(uuid.uuid4())

        try:
            result = await asyncio.to_thread(
                client.role_assignments.create,
                scope,
                assignment_name,
                RoleAssignmentCreateParameters(
                    role_definition_id=role_def_id,
                    principal_id=spec.principal_id,
                    description=spec.description,
                ),
            )
            role_assignment_ids.append(result.id)
            logger.info(
                "[%s] Role assignment created: %s -> %s",
                subscription_id, spec.role_definition_name, spec.principal_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[%s] Could not create role assignment for %s: %s",
                subscription_id, spec.principal_id, exc,
            )

    return role_assignment_ids
