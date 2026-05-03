"""Provisioning workflow executed after a new subscription is created."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

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
    """Passed to every workflow step.

    Attributes:
        subscription_id:          The newly created Azure subscription ID.
        subscription_name:        Display name of the subscription.
        config:                   Tag-derived provisioning config (environment, budget, etc.).
        settings:                 Service settings / env-var config.
        result:                   Mutable result object — append to ``result.errors`` on failure.
        dry_run:                  When ``True`` no Azure mutations or outbound HTTP calls are
                                  made.  Steps should log what *would* happen instead.
        credential:               Azure credential object (``None`` in dry-run mode).
        event_management_group_id: Management group ID from the Event Grid event payload.
                                  Used as a fallback by :data:`STEP_MG` when no
                                  ``itl-environment`` tag is present.
    """

    subscription_id:           str
    subscription_name:         str
    config:                    SubscriptionConfig
    settings:                  Settings
    result:                    "ProvisioningResult"
    dry_run:                   bool = False
    credential:                Any = None
    event_management_group_id: str = ""


# Type alias for a custom step coroutine.
WorkflowStep = Callable[[StepContext], Awaitable[None]]


@dataclass
class _StepEntry:
    fn: WorkflowStep
    depends_on: list[WorkflowStep] = field(default_factory=list)
    stop_on_error: bool = False


_EXTRA_STEPS: list[_StepEntry] = []


def _toposort(entries: list[_StepEntry]) -> list[_StepEntry]:
    """Return step entries ordered so every dependency runs before its dependent.

    Raises ``ValueError`` if a declared dependency is not registered, or if a
    dependency cycle is detected.
    """
    fn_to_entry: dict[WorkflowStep, _StepEntry] = {e.fn: e for e in entries}
    visiting: set[WorkflowStep] = set()   # cycle detection
    visited:  set[WorkflowStep] = set()
    order:    list[_StepEntry] = []

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
        order.append(fn_to_entry[fn])

    for entry in entries:
        _visit(entry.fn)

    return order


def register_step(
    fn: WorkflowStep | None = None,
    *,
    depends_on: list[WorkflowStep] | None = None,
    stop_on_error: bool = False,
) -> WorkflowStep | Callable[[WorkflowStep], WorkflowStep]:
    """Register *fn* as a provisioning step.

    Decorated steps are executed in topological order (``depends_on``).
    A raised exception is caught, recorded in ``ctx.result.errors``, and by
    default does **not** prevent remaining steps from running.

    Set ``stop_on_error=True`` to abort all remaining steps when this step
    records an error (either by raising or by appending to ``ctx.result.errors``).

    Usage (no dependencies)::

        from subscription_vending.workflow import register_step, StepContext

        @register_step
        async def my_step(ctx: StepContext) -> None:
            ...

    Usage (with dependency and stop-on-error)::

        @register_step(depends_on=[my_step], stop_on_error=True)
        async def critical_step(ctx: StepContext) -> None:
            ...
    """
    def _register(f: WorkflowStep) -> WorkflowStep:
        _EXTRA_STEPS.append(_StepEntry(fn=f, depends_on=list(depends_on or []), stop_on_error=stop_on_error))
        _name = getattr(f, "__qualname__", type(f).__qualname__)
        logger.debug("Registered workflow step: %s", _name)
        return f

    if fn is not None:
        # Used as @register_step (no parentheses)
        return _register(fn)
    # Used as @register_step(depends_on=[...]) or @register_step(stop_on_error=True)
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


# ── Built-in workflow steps (Steps 1–6) ───────────────────────────────────────
# Registered at module import time so they participate in the same topological
# sort as custom steps.  Use them as ``depends_on`` targets to insert a custom
# step between any two built-in steps::
#
#     from subscription_vending.workflow import STEP_RBAC
#     MyStep().register(depends_on=[STEP_RBAC])   # runs after RBAC, before policy


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
        return
    if ctx.dry_run:
        logger.info(
            "DRY RUN: would create budget alert for subscription %s (amount=%d EUR)",
            ctx.subscription_id,
            ctx.config.budget_eur,
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
        return
    await publish_provisioned_event(
        result=ctx.result,
        subscription_name=ctx.subscription_name,
        settings=ctx.settings,
    )


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

    Step 0 (preamble) reads subscription tags to build the :class:`StepContext`.
    All subsequent steps — built-in (:data:`STEP_MG` → :data:`STEP_NOTIFY`) and
    any custom steps registered via :func:`register_step` or
    :meth:`~core.base.BaseStep.register` — run through a shared topological
    sort driven by ``depends_on`` declarations.

    To insert a custom step *between* two built-in steps import the relevant
    step constant and use it as a dependency::

        from subscription_vending.workflow import STEP_RBAC, STEP_POLICY

        @register_step(depends_on=[STEP_RBAC])
        async def my_step(ctx: StepContext) -> None:
            ...  # runs after RBAC, before policy

    Returns a :class:`ProvisioningResult` summarising the outcome.
    """
    result = ProvisioningResult(subscription_id=subscription_id, dry_run=dry_run)

    logger.info(
        "Starting provisioning workflow for subscription %s (%s)%s",
        subscription_id,
        subscription_name,
        " [DRY RUN]" if dry_run else "",
    )

    # Step 0 — Read subscription tags (preamble: builds StepContext)
    from .azure.management_groups import _get_credential  # noqa: PLC0415

    if dry_run:
        logger.info("DRY RUN: skipping Azure tag read, using default SubscriptionConfig")
        config = SubscriptionConfig()
        credential = None
    else:
        credential = _get_credential(settings)
        config = await read_subscription_config(credential, subscription_id, settings)

    ctx = StepContext(
        subscription_id=subscription_id,
        subscription_name=subscription_name,
        config=config,
        settings=settings,
        result=result,
        dry_run=dry_run,
        credential=credential,
        event_management_group_id=management_group_id,
    )

    await emit(LifecycleEvent.PROVISIONING_STARTED, ctx)

    if _EXTRA_STEPS:
        try:
            ordered_steps = _toposort(_EXTRA_STEPS)
        except ValueError as exc:
            result.errors.append(f"Step ordering failed: {exc}")
            logger.exception("Failed to resolve workflow step order")
            ordered_steps = []
        for entry in ordered_steps:
            _step_name = getattr(entry.fn, "__qualname__", type(entry.fn).__qualname__)
            errors_before = len(result.errors)
            try:
                logger.info("Running workflow step: %s", _step_name)
                await entry.fn(ctx)
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"Step '{_step_name}' failed: {exc}")
                logger.exception("Workflow step %s failed", _step_name)
            if entry.stop_on_error and len(result.errors) > errors_before:
                logger.warning(
                    "Workflow aborted after step '%s' (stop_on_error=True); "
                    "%d step(s) skipped.",
                    _step_name,
                    len(ordered_steps) - ordered_steps.index(entry) - 1,
                )
                break

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
