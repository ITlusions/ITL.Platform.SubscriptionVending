"""Azure Policy assignment helper."""

from __future__ import annotations

import asyncio
import logging
import uuid

import httpx

from ...core.config import Settings
from .credential import get_credential as _get_credential

logger = logging.getLogger(__name__)

# Default timeout (seconds) for calls to the Authorization service
_AUTHORIZATION_SERVICE_TIMEOUT: int = 30

# Default policy definition IDs to assign (e.g. Azure Security Benchmark)
DEFAULT_POLICY_DEFINITION_IDS: list[str] = []


async def attach_foundation_initiative(
    authorization_url: str,
    subscription_id: str,
) -> str:
    """
    Attach the ITL Foundation Initiative to the new subscription.

    Calls the Authorization service sync endpoint and returns the
    ``initiative_id`` from the response body.
    """
    async with httpx.AsyncClient(timeout=_AUTHORIZATION_SERVICE_TIMEOUT) as client:
        resp = await client.post(
            f"{authorization_url}/sync/foundation",
            params={"subscription_id": subscription_id},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("initiative_id", "")


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
    """
    policies = policy_definition_ids or DEFAULT_POLICY_DEFINITION_IDS
    scope = f"/subscriptions/{subscription_id}"

    if not policies:
        logger.debug("No default policies configured — skipping policy assignment")
        return

    credential = _get_credential(settings)

    def _assign() -> None:
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
