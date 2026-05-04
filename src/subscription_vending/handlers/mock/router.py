"""Router for the mock webhook handler — POST /webhook/test (mock mode only)."""

from __future__ import annotations

from fastapi import APIRouter

from ...schemas.event_grid import WebhookResponse
from .controller import handle_mock_provision
from .models import MockEventRequest

router = APIRouter(prefix="/webhook", tags=["Mock"])


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
    return await handle_mock_provision(body)
