"""Azure Management Groups helper."""

from __future__ import annotations

import asyncio
import logging

from azure.identity import ManagedIdentityCredential, ClientSecretCredential
from azure.mgmt.managementgroups import ManagementGroupsAPI

from ..config import Settings

logger = logging.getLogger(__name__)


def _get_credential(settings: Settings):
    """Return the appropriate Azure credential based on configuration."""
    if settings.azure_client_id and settings.azure_client_secret:
        return ClientSecretCredential(
            tenant_id=settings.azure_tenant_id,
            client_id=settings.azure_client_id,
            client_secret=settings.azure_client_secret,
        )
    return ManagedIdentityCredential()


async def move_subscription_to_management_group(
    subscription_id: str,
    management_group_id: str,
    settings: Settings,
) -> None:
    """
    Move *subscription_id* under *management_group_id*.

    Uses the Azure Management Groups SDK synchronously inside a thread pool so
    that the async event loop is not blocked.
    """
    credential = _get_credential(settings)

    def _move() -> None:
        client = ManagementGroupsAPI(credential=credential)
        client.management_group_subscriptions.create(
            group_id=management_group_id,
            subscription_id=subscription_id,
        )

    await asyncio.to_thread(_move)
    logger.debug(
        "Subscription %s moved to management group %s",
        subscription_id,
        management_group_id,
    )
