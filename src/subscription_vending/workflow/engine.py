"""Provisioning workflow engine — :class:`WorkflowEngine`."""

from __future__ import annotations

import logging

from ..core.config import Settings
from ..core.context import ProvisioningResult, StepContext
from ..core.events import LifecycleEvent, emit
from ..core.registry import _EXTRA_STEPS, _GATE_STEPS, _StepEntry, toposort as _toposort
from ..infrastructure.azure.credential import get_credential as _get_credential
from ..infrastructure.azure.tags import SubscriptionConfig, read_subscription_config

logger = logging.getLogger(__name__)


async def _run_step(entry: _StepEntry, ctx: StepContext, *, label: str) -> bool:
    """Run *entry* against *ctx*.

    Returns ``True`` when the step produced new errors **and**
    ``entry.stop_on_error`` is set, signalling the caller to abort.
    """
    name = getattr(entry.fn, "__qualname__", type(entry.fn).__qualname__)
    errors_before = len(ctx.result.errors)
    try:
        logger.info("Running %s: %s", label, name)
        await entry.fn(ctx)
    except Exception as exc:  # noqa: BLE001
        ctx.result.errors.append(f"{label} '{name}' failed: {exc}")
        logger.exception("%s %s raised an unhandled exception", label, name)
    return entry.stop_on_error and len(ctx.result.errors) > errors_before


async def _emit_terminal_events(result: ProvisioningResult, ctx: StepContext) -> None:
    """Emit COMPLETED + SUCCEEDED/FAILED lifecycle events."""
    await emit(LifecycleEvent.PROVISIONING_COMPLETED, ctx)
    if result.success:
        await emit(LifecycleEvent.PROVISIONING_SUCCEEDED, ctx)
    else:
        await emit(LifecycleEvent.PROVISIONING_FAILED, ctx)


class WorkflowEngine:
    """Settings-bound engine for executing the provisioning workflow.

    Encapsulates the full provisioning logic so callers don't need to thread
    ``settings`` through every call site::

        engine = WorkflowEngine(settings)
        result = await engine.run(subscription_id, subscription_name, management_group_id)
    """

    def __init__(self, settings: Settings) -> None:
        self._settings: Settings = settings

    async def run(
        self,
        subscription_id: str,
        subscription_name: str,
        management_group_id: str,
        *,
        dry_run: bool = False,
    ) -> ProvisioningResult:
        """Execute the provisioning workflow for a new subscription.

        Step 0 (preamble) reads subscription tags to build the :class:`StepContext`.
        Gate checks run next; a failing gate with ``stop_on_error=True`` aborts
        everything.  Remaining steps run in topological order driven by their
        ``depends_on`` declarations.

        To insert a custom step *between* two built-in steps, import the relevant
        step constant and use it as a dependency::

            from subscription_vending.workflow import STEP_RBAC

            @register_step(depends_on=[STEP_RBAC])
            async def my_step(ctx: StepContext) -> None:
                ...  # runs after RBAC, before policy

        Returns a :class:`ProvisioningResult` summarising the outcome.
        """
        settings = self._settings
        result = ProvisioningResult(subscription_id=subscription_id, dry_run=dry_run)

        logger.info(
            "Starting provisioning workflow for subscription %s (%s)%s",
            subscription_id,
            subscription_name,
            " [DRY RUN]" if dry_run else "",
        )

        # Step 0 — Read subscription tags (preamble: builds StepContext)
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

        # ── Gate checks (always run before workflow steps) ────────────────────
        for entry in _GATE_STEPS:
            if await _run_step(entry, ctx, label="gate check"):
                _gate_name = getattr(entry.fn, "__qualname__", type(entry.fn).__qualname__)
                logger.warning(
                    "Provisioning aborted at gate '%s' (stop_on_error=True).", _gate_name
                )
                await _emit_terminal_events(result, ctx)
                return result

        # ── Workflow steps (topologically sorted) ──────────────────────────────
        if _EXTRA_STEPS:
            try:
                ordered_steps = _toposort(_EXTRA_STEPS)
            except ValueError as exc:
                result.errors.append(f"Step ordering failed: {exc}")
                logger.exception("Failed to resolve workflow step order")
                ordered_steps = []

            for i, entry in enumerate(ordered_steps):
                if await _run_step(entry, ctx, label="workflow step"):
                    _step_name = getattr(entry.fn, "__qualname__", type(entry.fn).__qualname__)
                    logger.warning(
                        "Workflow aborted after step '%s' (stop_on_error=True); "
                        "%d step(s) skipped.",
                        _step_name,
                        len(ordered_steps) - i - 1,
                    )
                    break

        await _emit_terminal_events(result, ctx)
        return result
