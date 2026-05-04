"""Router for the replay handler — POST /webhook/replay."""

from __future__ import annotations

from fastapi import APIRouter, Header

from .controller import handle_replay
from .models import ReplayRequest, ReplayResponse

router = APIRouter(prefix="/webhook", tags=["Replay"])


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
    return await handle_replay(payload, x_replay_secret)
