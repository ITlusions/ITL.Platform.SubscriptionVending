"""
ITL Subscription Vending: Tag-based provisioning configuration.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from azure.mgmt.subscription import SubscriptionClient

from ..config import Settings

logger = logging.getLogger(__name__)


@dataclass
class SubscriptionConfig:
    """Provisioning configuration derived from subscription tags."""

    environment: str = "sandbox"
    aks_enabled: bool = False
    budget_eur: int = 0
    owner_email: str = ""
    management_group_name: str = "ITL-Sandbox"

    @property
    def enforcement_mode(self) -> str:
        """Strict enforcement in production, informational everywhere else."""
        if self.environment == "production":
            return "Default"
        return "DoNotEnforce"


def _resolve_management_group(environment: str, settings: Settings) -> str:
    """Return the MG name for *environment* using the mapping in *settings*.

    Falls back to the 'sandbox' MG (or default_mg) when environment is not found.
    """
    return settings.mg_mapping.get(environment, settings.default_mg)


async def read_subscription_config(
    credential,
    subscription_id: str,
    settings: Settings,
) -> SubscriptionConfig:
    """Read subscription tags from Azure and convert them to a :class:`SubscriptionConfig`.

    Falls back to defaults when the subscription cannot be retrieved or a tag
    value is invalid, so the provisioning workflow can always continue.
    """
    try:
        client = SubscriptionClient(credential)
        sub = await asyncio.to_thread(client.subscriptions.get, subscription_id)
        tags: dict[str, str] = sub.tags or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[%s] Could not retrieve subscription tags: %s", subscription_id, exc
        )
        tags = {}

    config = SubscriptionConfig()

    if settings.tag_environment in tags:
        env = tags[settings.tag_environment].lower()
        # Accept ANY environment value — let the mapping handle resolution
        config.environment = env

    # Resolve MG name from settings so operators can override it via env vars
    config.management_group_name = _resolve_management_group(config.environment, settings)

    if settings.tag_aks in tags:
        config.aks_enabled = tags[settings.tag_aks].lower() == "true"

    if settings.tag_budget in tags:
        try:
            config.budget_eur = int(tags[settings.tag_budget])
        except ValueError:
            logger.warning(
                "[%s] Invalid %s tag value: %r",
                subscription_id,
                settings.tag_budget,
                tags[settings.tag_budget],
            )

    if settings.tag_owner in tags:
        config.owner_email = tags[settings.tag_owner]

    logger.info(
        "[%s] Subscription config loaded: env=%s, mg=%s, aks=%s, budget=%d",
        subscription_id,
        config.environment,
        config.management_group_name,
        config.aks_enabled,
        config.budget_eur,
    )
    return config
