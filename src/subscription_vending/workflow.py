"""Provisioning workflow executed after a new subscription is created."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from .azure.management_groups import move_subscription_to_management_group
from .azure.notifications import publish_provisioned_event
from .azure.policy import assign_default_policies, attach_foundation_initiative
from .azure.rbac import create_initial_rbac
from .azure.tags import SubscriptionConfig, read_subscription_config
from .config import Settings
from .core.events import LifecycleEvent, emit

logger = logging.getLogger(__name__)


# ── Custom step registry ──────────────────────────────────────────────────────

@dataclass
class StepContext:
    """Passed to every custom workflow step.

    Attributes:
        subscription_id:   The newly created Azure subscription ID.
        subscription_name: Display name of the subscription.
        config:            Tag-derived provisioning config (environment, budget, etc.).
        settings:          Service settings / env-var config.
        result:            Mutable result object — append to ``result.errors`` on failure.
        dry_run:           When ``True`` no Azure mutations or outbound HTTP calls are
                           made.  Steps should log what *would* happen instead.
    """

    subscription_id:   str
    subscription_name: str
    config:            SubscriptionConfig
    settings:          Settings
    result:            "ProvisioningResult"
    dry_run:           bool = False


# Type alias for a custom step coroutine.
WorkflowStep = Callable[[StepContext], Awaitable[None]]


@dataclass
class _StepEntry:
    fn: WorkflowStep
    depends_on: list[WorkflowStep] = field(default_factory=list)


_EXTRA_STEPS: list[_StepEntry] = []


def _toposort(entries: list[_StepEntry]) -> list[WorkflowStep]:
    """Return custom steps ordered so every dependency runs before its dependent.

    Raises ``ValueError`` if a declared dependency is not registered, or if a
    dependency cycle is detected.
    """
    fn_to_entry: dict[WorkflowStep, _StepEntry] = {e.fn: e for e in entries}
    visiting: set[WorkflowStep] = set()   # cycle detection
    visited:  set[WorkflowStep] = set()
    order:    list[WorkflowStep] = []

    def _visit(fn: WorkflowStep) -> None:
        if fn in visited:
            return
        if fn in visiting:
            raise ValueError(
                f"Dependency cycle detected involving custom step '{fn.__qualname__}'"
            )
        visiting.add(fn)
        entry = fn_to_entry.get(fn)
        if entry:
            for dep in entry.depends_on:
                if dep not in fn_to_entry:
                    raise ValueError(
                        f"Step '{fn.__qualname__}' depends on '{dep.__qualname__}' "
                        "which is not registered."
                    )
                _visit(dep)
        visiting.discard(fn)
        visited.add(fn)
        order.append(fn)

    for entry in entries:
        _visit(entry.fn)

    return order


def register_step(
    fn: WorkflowStep | None = None,
    *,
    depends_on: list[WorkflowStep] | None = None,
) -> WorkflowStep | Callable[[WorkflowStep], WorkflowStep]:
    """Register *fn* as an extra provisioning step.

    Decorated steps run **after** all built-in steps (0–6).  If multiple
    steps are registered, they are sorted topologically according to the
    ``depends_on`` declarations before execution.  A raised exception is
    caught, recorded in ``ctx.result.errors``, and never prevents remaining
    steps from running.

    Usage (no dependencies)::

        from subscription_vending.workflow import register_step, StepContext

        @register_step
        async def my_step(ctx: StepContext) -> None:
            ...

    Usage (with dependency)::

        @register_step(depends_on=[my_step])
        async def my_later_step(ctx: StepContext) -> None:
            ...
    """
    def _register(f: WorkflowStep) -> WorkflowStep:
        _EXTRA_STEPS.append(_StepEntry(fn=f, depends_on=list(depends_on or [])))
        logger.debug("Registered custom workflow step: %s", f.__qualname__)
        return f

    if fn is not None:
        # Used as @register_step (no parentheses)
        return _register(fn)
    # Used as @register_step(depends_on=[...])
    return _register


@dataclass
class ProvisioningResult:
    subscription_id:  str
    management_group: str = ""
    initiative_id:    str = ""
    rbac_roles:       list[str] = field(default_factory=list)
    errors:           list[str] = field(default_factory=list)
    dry_run:          bool = False

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


async def run_provisioning_workflow(
    subscription_id: str,
    subscription_name: str,
    management_group_id: str,
    settings: Settings,
    *,
    dry_run: bool = False,
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
    result = ProvisioningResult(subscription_id=subscription_id, dry_run=dry_run)

    logger.info(
        "Starting provisioning workflow for subscription %s (%s)%s",
        subscription_id,
        subscription_name,
        " [DRY RUN]" if dry_run else "",
    )

    # Step 0 — Read subscription tags
    from .azure.management_groups import _get_credential  # noqa: PLC0415

    if dry_run:
        logger.info("DRY RUN: skipping Azure tag read, using default SubscriptionConfig")
        config = SubscriptionConfig()
        credential = None
    else:
        credential = _get_credential(settings)
        config = await read_subscription_config(credential, subscription_id, settings)

    # Step 1 — Management group placement
    # Prefer the tag-derived MG; fall back to the caller-supplied value or the
    # root MG configured in settings.
    mg_id = config.management_group_name or management_group_id or settings.root_management_group
    if dry_run:
        logger.info("DRY RUN: would move subscription %s to management group %s", subscription_id, mg_id)
        result.management_group = mg_id
    else:
        try:
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
    if dry_run:
        logger.info("DRY RUN: would attach foundation initiative for subscription %s", subscription_id)
    else:
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
    if dry_run:
        logger.info("DRY RUN: would assign default RBAC roles for subscription %s", subscription_id)
    else:
        try:
            roles = await create_initial_rbac(subscription_id=subscription_id, settings=settings)
            result.rbac_roles = roles
            logger.info("Default RBAC roles assigned for subscription %s", subscription_id)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"RBAC creation failed: {exc}")
            logger.exception("Failed to assign default RBAC roles")

    # Step 4 — Policy assignments
    if dry_run:
        logger.info("DRY RUN: would assign default policies for subscription %s", subscription_id)
    else:
        try:
            await assign_default_policies(subscription_id=subscription_id, settings=settings)
            logger.info("Default policies assigned for subscription %s", subscription_id)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"Policy assignment failed: {exc}")
            logger.exception("Failed to assign default policies")

    # Step 5 — Cost budget alert (only when itl-budget tag is set)
    if config.budget_eur > 0:
        if dry_run:
            logger.info(
                "DRY RUN: would create budget alert for subscription %s (amount=%d EUR)",
                subscription_id,
                config.budget_eur,
            )
        else:
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
    if dry_run:
        logger.info("DRY RUN: would publish provisioned event for subscription %s", subscription_id)
    else:
        await publish_provisioned_event(
            result=result,
            subscription_name=subscription_name,
            settings=settings,
        )

    # Custom steps — registered via @register_step, executed in dependency order
    ctx = StepContext(
        subscription_id=subscription_id,
        subscription_name=subscription_name,
        config=config,
        settings=settings,
        result=result,
        dry_run=dry_run,
    )

    await emit(LifecycleEvent.PROVISIONING_STARTED, ctx)

    if _EXTRA_STEPS:
        try:
            ordered_steps = _toposort(_EXTRA_STEPS)
        except ValueError as exc:
            result.errors.append(f"Custom step ordering failed: {exc}")
            logger.exception("Failed to resolve custom workflow step order")
            ordered_steps = []
        for step in ordered_steps:
            try:
                logger.info("Running custom workflow step: %s", step.__qualname__)
                await step(ctx)
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"Custom step '{step.__qualname__}' failed: {exc}")
                logger.exception("Custom workflow step %s failed", step.__qualname__)

    # Lifecycle events — fire after all steps
    await emit(LifecycleEvent.PROVISIONING_COMPLETED, ctx)
    if result.success:
        await emit(LifecycleEvent.PROVISIONING_SUCCEEDED, ctx)
    else:
        await emit(LifecycleEvent.PROVISIONING_FAILED, ctx)

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
