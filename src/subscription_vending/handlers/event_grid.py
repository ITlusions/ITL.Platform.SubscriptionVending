"""Event Grid webhook handler — POST /webhook."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status

from ..config import Settings
from ..models import EventGridEvent, WebhookResponse
from ..workflow import run_provisioning_workflow

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Event Grid"])

# Singleton settings loaded once at import time.
_settings = Settings()


def _verify_sas_key(aeg_sas_key: str | None, sas_key: str) -> None:
    """Raise 403 if the provided SAS key does not match the configured one."""
    if sas_key and aeg_sas_key != sas_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Event Grid SAS key",
        )


@router.post(
    "/webhook",
    response_model=WebhookResponse,
    summary="Receive an Event Grid subscription-created event",
)
async def receive_event(
    request: Request,
    aeg_sas_key: str | None = Header(default=None, alias="aeg-sas-key"),
) -> WebhookResponse:
    """
    Handle Event Grid webhook delivery.

    Supports both:
    - **Validation handshake** (``validationCode`` present in the first event).
    - **SubscriptionCreated** events that trigger the provisioning workflow.
    """
    _verify_sas_key(aeg_sas_key, _settings.event_grid_sas_key)

    body: list[dict[str, Any]] = await request.json()

    # Event Grid delivers a list; handle the first event.
    if not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty event payload",
        )

    first_event: dict[str, Any] = body[0]

    # --- Subscription validation handshake ---------------------------------
    validation_code: str | None = first_event.get("data", {}).get("validationCode")
    if validation_code:
        logger.info("Event Grid validation handshake received")
        return WebhookResponse(
            status="validationResponse",
            message=validation_code,
        )

    # --- Parse and process the event ---------------------------------------
    try:
        event = EventGridEvent.model_validate(first_event)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to parse Event Grid event")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid event schema: {exc}",
        ) from exc

    data = event.data
    subscription_id: str = data.get("subscriptionId", "")
    if not subscription_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event data missing 'subscriptionId'",
        )

    subscription_name: str = data.get("displayName", "")
    management_group_id: str = data.get("managementGroupId", "")

    logger.info(
        "Processing subscription-created event for subscription %s", subscription_id
    )

    results = await run_provisioning_workflow(
        subscription_id=subscription_id,
        subscription_name=subscription_name,
        management_group_id=management_group_id,
        settings=_settings,
    )

    any_error = any(v.startswith("error") for v in results.values())
    return WebhookResponse(
        status="error" if any_error else "ok",
        message=str(results),
        subscription_id=subscription_id,
    )
