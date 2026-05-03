"""Preflight handler — POST /webhook/preflight

Returns a structured dry-run plan showing what the provisioning workflow
*would* do, including a live ServiceNow ticket validation (read-only).
No Azure changes are made.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..config import get_settings
from ..workflow import run_provisioning_workflow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["Preflight"])

_settings = get_settings()


class PreflightRequest(BaseModel):
    """Input for a preflight dry-run check."""

    subscription_id: str = Field(..., description="Subscription ID (real or placeholder)")
    subscription_name: str = Field("preflight-subscription", description="Display name")
    management_group_id: str = Field("", description="Target management group (optional)")
    snow_ticket: str = Field(
        "",
        description=(
            "ServiceNow ticket number to validate (e.g. RITM0041872). "
            "When provided this overrides any tag already on the subscription."
        ),
    )


class PreflightStepResult(BaseModel):
    description: str
    status: str  # "planned" | "blocked"


class PreflightResponse(BaseModel):
    subscription_id: str
    subscription_name: str
    management_group: str
    gate_passed: bool
    steps: list[PreflightStepResult]
    errors: list[str]
    summary: str


@router.post(
    "/preflight",
    response_model=PreflightResponse,
    summary="Dry-run: validate ticket and show what provisioning would do",
)
async def preflight(body: PreflightRequest) -> PreflightResponse:
    """
    Run the full provisioning workflow in dry-run mode.

    - The ServiceNow gate **does** make a real (read-only) call to verify the
      ticket exists and is approved.
    - No Azure resources are created or modified.
    - Returns a step-by-step plan and any blocking errors.

    Use this endpoint before submitting a real subscription-created event to
    confirm that all prerequisites are in place.
    """
    logger.info("Preflight check requested for subscription %s", body.subscription_id)

    # If a ticket number is supplied in the request body, inject it as a fake
    # subscription tag so the SNOW gate can pick it up via ctx.config.snow_ticket.
    # We do this by monkey-patching the config after the tag-read step (dry_run
    # skips real Azure tag reads) — the simplest approach is to set the env var
    # temporarily, but instead we use a lightweight wrapper step registered just
    # for this call.  Since dry_run skips the real tag read and uses a default
    # SubscriptionConfig, we patch it directly via a registered gate.

    # Capture and inject snow_ticket if provided
    snow_ticket = body.snow_ticket.strip()

    if snow_ticket:
        from ..workflow import _GATE_STEPS, StepContext, register_gate, _StepEntry  # noqa: PLC0415

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
        result = await run_provisioning_workflow(
            subscription_id=body.subscription_id,
            subscription_name=body.subscription_name,
            management_group_id=body.management_group_id,
            settings=_settings,
            dry_run=True,
        )
    finally:
        # Always clean up the injected gate entry
        if _inject_entry is not None:
            from ..workflow import _GATE_STEPS  # noqa: PLC0415
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
    # Any errors that made it into result.errors are blocking
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
