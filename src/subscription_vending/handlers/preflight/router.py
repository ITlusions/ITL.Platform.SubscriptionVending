"""Router for the preflight handler — POST /webhook/preflight."""

from __future__ import annotations

from fastapi import APIRouter

from .controller import handle_preflight
from .models import PreflightRequest, PreflightResponse

router = APIRouter(prefix="/webhook", tags=["Preflight"])


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
    return await handle_preflight(body)
