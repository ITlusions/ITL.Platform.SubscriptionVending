"""Provisioning workflow executed after a new subscription is created."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .config import Settings
from .azure.management_groups import move_subscription_to_management_group
from .azure.rbac import create_initial_rbac
from .azure.policy import assign_default_policies, attach_foundation_initiative
from .azure.tags import read_subscription_config
from .azure.notifications import publish_provisioned_event

logger = logging.getLogger(__name__)


@dataclass
class ProvisioningResult:
    subscription_id:  str
    management_group: str = ""
    initiative_id:    str = ""
    rbac_roles:       list[str] = field(default_factory=list)
    errors:           list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


async def run_provisioning_workflow(
    subscription_id: str,
    subscription_name: str,
    management_group_id: str,
    settings: Settings,
) -> ProvisioningResult:
    """
    Execute the provisioning workflow for a new subscription.

    Steps:
      0. Read subscription tags to derive provisioning configuration.
      1. Move the subscription under the tag-determined management group
         (falls back to *management_group_id* or ``settings.root_management_group``).
      2. Attach the ITL Foundation Initiative to the subscription.
      3. Assign default RBAC roles.
      4. Assign default policies.
      5. Create a cost budget alert when the ``itl-budget`` tag is present.

    Returns a :class:`ProvisioningResult` summarising the outcome of each step.
    """
    result = ProvisioningResult(subscription_id=subscription_id)

    logger.info(
        "Starting provisioning workflow for subscription %s (%s)",
        subscription_id,
        subscription_name,
    )

    # Step 0 — Read subscription tags
    from .azure.management_groups import _get_credential  # noqa: PLC0415

    credential = _get_credential(settings)
    config = await read_subscription_config(credential, subscription_id, settings)

    # Step 1 — Management group placement
    # Prefer the tag-derived MG; fall back to the caller-supplied value or the
    # root MG configured in settings.
    try:
        mg_id = config.management_group_name or management_group_id or settings.root_management_group
        await move_subscription_to_management_group(
            subscription_id=subscription_id,
            management_group_id=mg_id,
            settings=settings,
        )
        result.management_group = mg_id
        logger.info("Subscription %s moved to management group %s", subscription_id, mg_id)
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"MG assignment failed: {exc}")
        logger.exception("Failed to move subscription to management group")

    # Step 2 — Attach foundation initiative
    try:
        initiative_id = await attach_foundation_initiative(
            authorization_url=settings.authorization_service_url,
            subscription_id=subscription_id,
        )
        result.initiative_id = initiative_id
        logger.info("Foundation initiative attached for subscription %s: %s", subscription_id, initiative_id)
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"Foundation initiative failed: {exc}")
        logger.exception("Failed to attach foundation initiative")

    # Step 3 — RBAC role assignments
    try:
        roles = await create_initial_rbac(subscription_id=subscription_id, settings=settings)
        result.rbac_roles = roles
        logger.info("Default RBAC roles assigned for subscription %s", subscription_id)
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"RBAC creation failed: {exc}")
        logger.exception("Failed to assign default RBAC roles")

    # Step 4 — Policy assignments
    try:
        await assign_default_policies(subscription_id=subscription_id, settings=settings)
        logger.info("Default policies assigned for subscription %s", subscription_id)
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"Policy assignment failed: {exc}")
        logger.exception("Failed to assign default policies")

    # Step 5 — Cost budget alert (only when itl-budget tag is set)
    if config.budget_eur > 0:
        try:
            contact_email = config.owner_email or settings.default_alert_email
            await _create_budget_alert(
                credential=credential,
                subscription_id=subscription_id,
                amount=config.budget_eur,
                contact_email=contact_email,
            )
            logger.info(
                "Budget alert created for subscription %s (amount=%d EUR, contact=%s)",
                subscription_id,
                config.budget_eur,
                contact_email,
            )
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"Budget alert failed: {exc}")
            logger.exception("Failed to create budget alert for subscription %s", subscription_id)

    # Step 6 — Publish outbound notification event (non-fatal)
    await publish_provisioned_event(
        result=result,
        subscription_name=subscription_name,
        settings=settings,
    )

    return result


async def _create_budget_alert(
    credential,
    subscription_id: str,
    amount: int,
    contact_email: str,
) -> None:
    """Create an Azure Cost Management budget with an e-mail alert.

    The budget is scoped to *subscription_id*, capped at *amount* EUR per
    calendar month, and sends an alert to *contact_email* at 80 % and 100 %
    of the threshold.
    """
    import asyncio  # noqa: PLC0415

    def _create() -> None:
        from azure.mgmt.consumption import ConsumptionManagementClient  # noqa: PLC0415
        from azure.mgmt.consumption.models import (  # noqa: PLC0415
            Budget,
            BudgetTimePeriod,
            Notification,
        )
        from datetime import date, timedelta  # noqa: PLC0415

        client = ConsumptionManagementClient(
            credential=credential,
            subscription_id=subscription_id,
        )
        scope = f"/subscriptions/{subscription_id}"
        budget_name = "itl-budget-alert"
        today = date.today()
        start = today.replace(day=1)
        end = start.replace(year=start.year + 3)

        notifications: dict = {}
        for threshold in (80, 100):
            key = f"Actual_{threshold}Percent"
            notifications[key] = Notification(
                enabled=True,
                operator="GreaterThan",
                threshold=threshold,
                contact_emails=[contact_email] if contact_email else [],
            )

        budget = Budget(
            time_grain="Monthly",
            amount=amount,
            time_period=BudgetTimePeriod(start_date=start, end_date=end),
            notifications=notifications,
        )
        client.budgets.create_or_update(scope=scope, budget_name=budget_name, parameters=budget)

    await asyncio.to_thread(_create)
