"""Publish outbound subscription-vended notification events to an Event Grid Custom Topic."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ...core.config import Settings

if TYPE_CHECKING:
    from ...core.context import ProvisioningResult

logger = logging.getLogger(__name__)

_EVENT_TYPE = "ITL.SubscriptionVending.SubscriptionProvisioned"
_DATA_VERSION = "1.0"


def _get_publisher_client(endpoint: str, settings: Settings):
    """Return an EventGridPublisherClient authenticated via Managed Identity or SP."""
    from azure.eventgrid import EventGridPublisherClient  # noqa: PLC0415
    from azure.identity import (  # noqa: PLC0415
        ClientSecretCredential,
        ManagedIdentityCredential,
    )

    if settings.azure_client_id and settings.azure_client_secret:
        credential = ClientSecretCredential(
            tenant_id=settings.azure_tenant_id,
            client_id=settings.azure_client_id,
            client_secret=settings.azure_client_secret,
        )
    else:
        credential = ManagedIdentityCredential()

    return EventGridPublisherClient(endpoint, credential)


async def publish_provisioned_event(
    result: ProvisioningResult,
    subscription_name: str,
    settings: Settings,
) -> None:
    """Publish a *SubscriptionProvisioned* event to the configured notification topic.

    This is a fire-and-forget notification step.  If ``settings.event_grid_topic_endpoint``
    is empty the function returns immediately.  Any publishing error is logged as a
    warning and does not propagate to the caller.
    """
    if not settings.event_grid_topic_endpoint:
        logger.debug(
            "VENDING_EVENT_GRID_TOPIC_ENDPOINT not configured — skipping notification for %s",
            result.subscription_id,
        )
        return

    def _publish() -> None:
        from azure.eventgrid import EventGridEvent  # noqa: PLC0415

        client = _get_publisher_client(settings.event_grid_topic_endpoint, settings)
        event = EventGridEvent(
            event_type=_EVENT_TYPE,
            subject=f"/subscriptions/{result.subscription_id}",
            data={
                "subscription_id": result.subscription_id,
                "subscription_name": subscription_name,
                "management_group": result.management_group,
                "initiative_id": result.initiative_id,
                "rbac_roles": result.rbac_roles,
                "errors": result.errors,
                "success": result.success,
            },
            data_version=_DATA_VERSION,
        )
        client.send([event])

    try:
        await asyncio.to_thread(_publish)
        logger.info(
            "Notification event published for subscription %s (success=%s)",
            result.subscription_id,
            result.success,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to publish notification event for subscription %s: %s",
            result.subscription_id,
            exc,
        )
