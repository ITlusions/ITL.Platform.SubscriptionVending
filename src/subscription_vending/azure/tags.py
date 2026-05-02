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

_VALID_ENVIRONMENTS = {"production", "staging", "development", "sandbox"}


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
    """Return the MG name for *environment* using the names defined in *settings*."""
    mapping = {
        "production":  settings.mg_production,
        "staging":     settings.mg_staging,
        "development": settings.mg_development,
        "sandbox":     settings.mg_sandbox,
    }
    return mapping.get(environment, settings.mg_sandbox)


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

    if "itl-environment" in tags:
        env = tags["itl-environment"].lower()
        config.environment = env if env in _VALID_ENVIRONMENTS else "sandbox"

    # Resolve MG name from settings so operators can override it via env vars
    config.management_group_name = _resolve_management_group(config.environment, settings)

    if "itl-aks" in tags:
        config.aks_enabled = tags["itl-aks"].lower() == "true"

    if "itl-budget" in tags:
        try:
            config.budget_eur = int(tags["itl-budget"])
        except ValueError:
            logger.warning(
                "[%s] Invalid itl-budget tag value: %r",
                subscription_id,
                tags["itl-budget"],
            )

    if "itl-owner" in tags:
        config.owner_email = tags["itl-owner"]

    logger.info(
        "[%s] Subscription config loaded: env=%s, mg=%s, aks=%s, budget=%d",
        subscription_id,
        config.environment,
        config.management_group_name,
        config.aks_enabled,
        config.budget_eur,
    )
    return config
