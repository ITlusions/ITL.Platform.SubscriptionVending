"""Manual replay endpoint — POST /webhook/replay

Allows operators to re-trigger the provisioning workflow for a specific
subscription ID without a real Event Grid event. Available in all modes
(not gated by mock_mode).

This is Option C: manual recovery by re-running a known subscription.
Because all provisioning steps are idempotent (role assignment GUIDs are
deterministic, budget is an upsert), replaying a subscription that was
partially provisioned is safe.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

from ..config import get_settings
from ..workflow import run_provisioning_workflow

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["Replay"])

_settings = get_settings()


class ReplayRequest(BaseModel):
    subscription_id: str
    subscription_name: str = ""
    management_group_id: str = ""
    dry_run: bool = False


class ReplayResponse(BaseModel):
    status: str                   # "ok" | "error"
    subscription_id: str
    errors: list[str] = []
    plan: list[str] = []          # populated when dry_run=True


@router.post(
    "/replay",
    response_model=ReplayResponse,
    summary="Re-trigger provisioning for a subscription (idempotent)",
)
async def replay(
    payload: ReplayRequest,
    x_replay_secret: str | None = Header(default=None, alias="x-replay-secret"),
) -> ReplayResponse:
    """
    Manually replay the provisioning workflow for a subscription.

    Safe to call multiple times — steps are idempotent:
    - Role assignments use deterministic GUIDs (no-op if already assigned)
    - Budget creation is an upsert
    - MG placement is idempotent

    Useful for:
    - Recovering a partially provisioned subscription
    - Re-running after a transient Azure API failure
    - Applying configuration changes (new RBAC groups, budget updates)
    """
    if _settings.worker_secret and x_replay_secret != _settings.worker_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid replay secret")

    logger.info(
        "Manual replay triggered for subscription %s (dry_run=%s)",
        payload.subscription_id,
        payload.dry_run,
    )

    result = await run_provisioning_workflow(
        subscription_id=payload.subscription_id,
        subscription_name=payload.subscription_name,
        management_group_id=payload.management_group_id,
        settings=_settings,
        dry_run=payload.dry_run,
    )

    return ReplayResponse(
        status="ok" if result.success else "error",
        subscription_id=payload.subscription_id,
        errors=result.errors,
        plan=result.plan,
    )
