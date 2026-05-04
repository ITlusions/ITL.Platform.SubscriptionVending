"""Business logic for the mock webhook handler."""

from __future__ import annotations

import logging

from subscription_vending.schemas.event_grid import WebhookResponse
from subscription_vending.workflow import WorkflowEngine
from subscription_vending.core.config import get_settings
from .models import MockEventRequest

logger = logging.getLogger(__name__)

_settings = get_settings()
_engine = WorkflowEngine(_settings)


async def handle_mock_provision(body: MockEventRequest) -> WebhookResponse:
    """Execute the provisioning workflow for a mock request and return the result."""
    logger.info(
        "Mock provisioning triggered for subscription %s", body.subscription_id
    )

    results = await _engine.run(
        subscription_id=body.subscription_id,
        subscription_name=body.subscription_name,
        management_group_id=body.management_group_id,
        dry_run=body.dry_run,
    )

    any_error = any(v.startswith("error") for v in results.values())
    return WebhookResponse(
        status="error" if any_error else "ok",
        message=str(results),
        subscription_id=body.subscription_id,
    )
