"""Router for the Event Grid webhook handler — POST /webhook/."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status

from .controller import handle_event_grid_delivery

router = APIRouter(prefix="/webhook", tags=["Event Grid"])


@router.post(
    "/",
    response_model=None,
    summary="Receive an Event Grid subscription-created event",
)
async def receive_event(
    request: Request,
    aeg_event_type: str | None = Header(default=None, alias="aeg-event-type"),
    aeg_sas_key: str | None = Header(default=None, alias="aeg-sas-key"),
) -> Any:
    """
    Handle Event Grid webhook delivery.

    Supports both:
    - **Validation handshake** (``validationCode`` present in the first event).
    - **SubscriptionCreated** events that trigger the provisioning workflow.
    """
    body = await request.json()
    events: list[dict[str, Any]] = body if isinstance(body, list) else [body]
    if not events:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty event payload",
        )
    return await handle_event_grid_delivery(events, aeg_event_type, aeg_sas_key)
