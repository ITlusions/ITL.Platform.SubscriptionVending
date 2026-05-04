"""Built-in provisioning workflow steps (Steps 1–6).

Registered at module import time so they participate in the same topological
sort as custom steps.  Use them as ``depends_on`` targets to insert a custom
step between any two built-in steps::

    from subscription_vending.workflow import STEP_RBAC
    MyStep().register(depends_on=[STEP_RBAC])   # runs after RBAC, before policy
"""

from __future__ import annotations

import asyncio
import logging

from ..infrastructure.azure.management_groups import move_subscription_to_management_group
from ..infrastructure.azure.notifications import publish_provisioned_event
from ..infrastructure.azure.policy import assign_default_policies, attach_foundation_initiative
from ..infrastructure.azure.rbac import create_initial_rbac
from ..core.registry import register_step
from ..core.context import StepContext

logger = logging.getLogger(__name__)


@register_step
async def STEP_MG(ctx: StepContext) -> None:
    """Step 1 — Move subscription to the target management group."""
    mg_id = (
        ctx.config.management_group_name
        or ctx.event_management_group_id
        or ctx.settings.root_management_group
    )
    if ctx.dry_run:
        logger.info("DRY RUN: would move subscription %s to management group %s", ctx.subscription_id, mg_id)
        ctx.result.management_group = mg_id
        ctx.result.plan.append(f"[STEP_MG] Move subscription to management group '{mg_id}'")
        return
    try:
        await move_subscription_to_management_group(
            subscription_id=ctx.subscription_id,
            management_group_id=mg_id,
            settings=ctx.settings,
        )
        ctx.result.management_group = mg_id
        logger.info("Subscription %s moved to management group %s", ctx.subscription_id, mg_id)
    except Exception as exc:  # noqa: BLE001
        ctx.result.errors.append(f"MG assignment failed: {exc}")
        logger.exception("Failed to move subscription to management group")


@register_step(depends_on=[STEP_MG])
async def STEP_INITIATIVE(ctx: StepContext) -> None:
    """Step 2 — Attach the ITL Foundation Policy Initiative."""
    if ctx.dry_run:
        logger.info("DRY RUN: would attach foundation initiative for subscription %s", ctx.subscription_id)
        ctx.result.plan.append("[STEP_INITIATIVE] Attach ITL Foundation Policy Initiative")
        return
    try:
        initiative_id = await attach_foundation_initiative(
            authorization_url=ctx.settings.authorization_service_url,
            subscription_id=ctx.subscription_id,
        )
        ctx.result.initiative_id = initiative_id
        logger.info("Foundation initiative attached for subscription %s: %s", ctx.subscription_id, initiative_id)
    except Exception as exc:  # noqa: BLE001
        ctx.result.errors.append(f"Foundation initiative failed: {exc}")
        logger.exception("Failed to attach foundation initiative")


@register_step(depends_on=[STEP_INITIATIVE])
async def STEP_RBAC(ctx: StepContext) -> None:
    """Step 3 — Assign default RBAC roles."""
    if ctx.dry_run:
        logger.info("DRY RUN: would assign default RBAC roles for subscription %s", ctx.subscription_id)
        ctx.result.plan.append("[STEP_RBAC] Assign default RBAC roles (Platform SPN, Ops, Security, FinOps)")
        return
    try:
        roles = await create_initial_rbac(subscription_id=ctx.subscription_id, settings=ctx.settings)
        ctx.result.rbac_roles = roles
        logger.info("Default RBAC roles assigned for subscription %s", ctx.subscription_id)
    except Exception as exc:  # noqa: BLE001
        ctx.result.errors.append(f"RBAC creation failed: {exc}")
        logger.exception("Failed to assign default RBAC roles")


@register_step(depends_on=[STEP_RBAC])
async def STEP_POLICY(ctx: StepContext) -> None:
    """Step 4 — Assign default Azure policies."""
    if ctx.dry_run:
        logger.info("DRY RUN: would assign default policies for subscription %s", ctx.subscription_id)
        ctx.result.plan.append("[STEP_POLICY] Assign default Azure policies")
        return
    try:
        await assign_default_policies(subscription_id=ctx.subscription_id, settings=ctx.settings)
        logger.info("Default policies assigned for subscription %s", ctx.subscription_id)
    except Exception as exc:  # noqa: BLE001
        ctx.result.errors.append(f"Policy assignment failed: {exc}")
        logger.exception("Failed to assign default policies")


@register_step(depends_on=[STEP_POLICY])
async def STEP_BUDGET(ctx: StepContext) -> None:
    """Step 5 — Create monthly cost budget alert (conditional on itl-budget tag)."""
    if ctx.config.budget_eur <= 0:
        if ctx.dry_run:
            ctx.result.plan.append("[STEP_BUDGET] Skipped — no itl-budget tag on subscription")
        return
    if ctx.dry_run:
        contact_email = ctx.config.owner_email or ctx.settings.default_alert_email
        logger.info(
            "DRY RUN: would create budget alert for subscription %s (amount=%d EUR)",
            ctx.subscription_id,
            ctx.config.budget_eur,
        )
        ctx.result.plan.append(
            f"[STEP_BUDGET] Create monthly budget alert — "
            f"€{ctx.config.budget_eur}/month, notify {contact_email or '(no email set)'}"
        )
        return
    try:
        contact_email = ctx.config.owner_email or ctx.settings.default_alert_email
        await _create_budget_alert(
            credential=ctx.credential,
            subscription_id=ctx.subscription_id,
            amount=ctx.config.budget_eur,
            contact_email=contact_email,
        )
        logger.info(
            "Budget alert created for subscription %s (amount=%d EUR, contact=%s)",
            ctx.subscription_id,
            ctx.config.budget_eur,
            contact_email,
        )
    except Exception as exc:  # noqa: BLE001
        ctx.result.errors.append(f"Budget alert failed: {exc}")
        logger.exception("Failed to create budget alert for subscription %s", ctx.subscription_id)


@register_step(depends_on=[STEP_BUDGET])
async def STEP_NOTIFY(ctx: StepContext) -> None:
    """Step 6 — Publish outbound SubscriptionProvisioned event (conditional)."""
    if ctx.dry_run:
        logger.info("DRY RUN: would publish provisioned event for subscription %s", ctx.subscription_id)
        ctx.result.plan.append("[STEP_NOTIFY] Publish SubscriptionProvisioned event to Event Grid")
        return
    await publish_provisioned_event(
        result=ctx.result,
        subscription_name=ctx.subscription_name,
        settings=ctx.settings,
    )


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
