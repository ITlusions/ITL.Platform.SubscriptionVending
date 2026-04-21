"""Mock webhook handler — POST /webhook/test (mock mode only)."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..models import WebhookResponse
from ..workflow import run_provisioning_workflow
from ..config import Settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["Mock"])

_settings = Settings()


class MockEventRequest(BaseModel):
    """Simplified request body for triggering a mock provisioning run."""

    subscription_id: str = Field(..., description="Subscription ID to provision")
    subscription_name: str = Field("mock-subscription", description="Display name")
    management_group_id: str = Field("", description="Target management group (optional)")


@router.post(
    "/test",
    response_model=WebhookResponse,
    summary="Trigger a mock provisioning workflow (mock_mode only)",
)
async def mock_webhook(body: MockEventRequest) -> WebhookResponse:
    """
    Simulate an Event Grid subscription-created event without a real Event Grid
    delivery.  Useful for local development and integration testing.
    """
    logger.info(
        "Mock provisioning triggered for subscription %s", body.subscription_id
    )

    results = await run_provisioning_workflow(
        subscription_id=body.subscription_id,
        subscription_name=body.subscription_name,
        management_group_id=body.management_group_id,
        settings=_settings,
    )

    any_error = any(v.startswith("error") for v in results.values())
    return WebhookResponse(
        status="error" if any_error else "ok",
        message=str(results),
        subscription_id=body.subscription_id,
    )
