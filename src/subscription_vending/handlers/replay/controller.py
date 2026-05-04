"""Business logic for the replay handler."""

from __future__ import annotations

import logging

from fastapi import HTTPException, status

from subscription_vending.core.config import get_settings
from subscription_vending.workflow import WorkflowEngine
from .models import ReplayRequest, ReplayResponse

logger = logging.getLogger(__name__)

_settings = get_settings()
_engine = WorkflowEngine(_settings)


async def handle_replay(payload: ReplayRequest, x_replay_secret: str | None) -> ReplayResponse:
    """Validate the replay secret and run the provisioning workflow."""
    if _settings.worker_secret and x_replay_secret != _settings.worker_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid replay secret",
        )

    logger.info(
        "Manual replay triggered for subscription %s (dry_run=%s)",
        payload.subscription_id,
        payload.dry_run,
    )

    result = await _engine.run(
        subscription_id=payload.subscription_id,
        subscription_name=payload.subscription_name,
        management_group_id=payload.management_group_id,
        dry_run=payload.dry_run,
    )

    return ReplayResponse(
        status="ok" if result.success else "error",
        subscription_id=payload.subscription_id,
        errors=result.errors,
        plan=result.plan,
    )
