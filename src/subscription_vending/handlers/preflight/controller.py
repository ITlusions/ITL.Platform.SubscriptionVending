"""Business logic for the preflight handler."""

from __future__ import annotations

import logging

from subscription_vending.core.config import get_settings
from subscription_vending.workflow import WorkflowEngine
from .models import PreflightRequest, PreflightResponse, PreflightStepResult

logger = logging.getLogger(__name__)

_settings = get_settings()
_engine = WorkflowEngine(_settings)


async def handle_preflight(body: PreflightRequest) -> PreflightResponse:
    """Run the provisioning workflow in dry-run mode and return a structured plan."""
    logger.info("Preflight check requested for subscription %s", body.subscription_id)

    snow_ticket = body.snow_ticket.strip()

    if snow_ticket:
        from subscription_vending.workflow import _GATE_STEPS, StepContext, _StepEntry  # noqa: PLC0415

        async def _inject_ticket(ctx: StepContext) -> None:
            ctx.config.snow_ticket = snow_ticket
            ctx.result.plan.append(
                f"[preflight] Using supplied ticket: {snow_ticket!r}"
            )

        _inject_entry = _StepEntry(fn=_inject_ticket, depends_on=[], stop_on_error=False)
        _GATE_STEPS.insert(0, _inject_entry)
    else:
        _inject_entry = None  # type: ignore[assignment]

    try:
        result = await _engine.run(
            subscription_id=body.subscription_id,
            subscription_name=body.subscription_name,
            management_group_id=body.management_group_id,
            dry_run=True,
        )
    finally:
        if _inject_entry is not None:
            from subscription_vending.workflow import _GATE_STEPS  # noqa: PLC0415
            try:
                _GATE_STEPS.remove(_inject_entry)
            except ValueError:
                pass

    gate_passed = result.success or not any(
        "gate" in e.lower() or "ticket" in e.lower() for e in result.errors
    )

    steps = [
        PreflightStepResult(description=p, status="planned")
        for p in result.plan
    ]
    for e in result.errors:
        steps.append(PreflightStepResult(description=e, status="blocked"))

    if result.errors:
        summary = f"Preflight FAILED — {len(result.errors)} blocking issue(s). No provisioning will occur."
    else:
        summary = f"Preflight OK — {len(result.plan)} step(s) ready to execute."

    return PreflightResponse(
        subscription_id=result.subscription_id,
        subscription_name=body.subscription_name,
        management_group=result.management_group,
        gate_passed=gate_passed,
        steps=steps,
        errors=result.errors,
        summary=summary,
    )
