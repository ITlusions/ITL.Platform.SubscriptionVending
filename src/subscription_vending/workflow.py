"""Provisioning workflow executed after a new subscription is created."""

from __future__ import annotations

import logging

from .config import Settings
from .azure.management_groups import move_subscription_to_management_group
from .azure.rbac import create_initial_rbac
from .azure.policy import assign_default_policies

logger = logging.getLogger(__name__)


async def run_provisioning_workflow(
    subscription_id: str,
    subscription_name: str,
    management_group_id: str,
    settings: Settings,
) -> dict[str, str]:
    """
    Execute the fixed provisioning workflow for a new subscription.

    Steps:
      1. Move the subscription under the target management group.
      2. Assign default RBAC roles.
      3. Assign default policies.

    Returns a dict summarising the outcome of each step.
    """
    results: dict[str, str] = {}

    logger.info(
        "Starting provisioning workflow for subscription %s (%s)",
        subscription_id,
        subscription_name,
    )

    # Step 1 — Management group placement
    try:
        mg_id = management_group_id or settings.root_management_group
        await move_subscription_to_management_group(
            subscription_id=subscription_id,
            management_group_id=mg_id,
            settings=settings,
        )
        results["management_group"] = "ok"
        logger.info("Subscription %s moved to management group %s", subscription_id, mg_id)
    except Exception as exc:  # noqa: BLE001
        results["management_group"] = f"error: {exc}"
        logger.exception("Failed to move subscription to management group")

    # Step 2 — RBAC role assignments
    try:
        await create_initial_rbac(subscription_id=subscription_id, settings=settings)
        results["rbac"] = "ok"
        logger.info("Default RBAC roles assigned for subscription %s", subscription_id)
    except Exception as exc:  # noqa: BLE001
        results["rbac"] = f"error: {exc}"
        logger.exception("Failed to assign default RBAC roles")

    # Step 3 — Policy assignments
    try:
        await assign_default_policies(subscription_id=subscription_id, settings=settings)
        results["policy"] = "ok"
        logger.info("Default policies assigned for subscription %s", subscription_id)
    except Exception as exc:  # noqa: BLE001
        results["policy"] = f"error: {exc}"
        logger.exception("Failed to assign default policies")

    return results
