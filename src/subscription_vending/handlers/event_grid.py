"""Event Grid webhook handler — POST /webhook/."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from pydantic import ValidationError

from ..config import Settings
from ..models import EventGridEvent
from ..retry.dispatcher import dispatch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["Event Grid"])

# Singleton settings loaded once at import time.
_settings = Settings()


def _verify_sas_key(aeg_sas_key: str | None, sas_key: str) -> None:
    """Raise 401 if the provided SAS key does not match the configured one."""
    if sas_key and aeg_sas_key != sas_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Event Grid SAS key",
        )


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
    _verify_sas_key(aeg_sas_key, _settings.event_grid_sas_key)

    body = await request.json()
    events: list[dict[str, Any]] = body if isinstance(body, list) else [body]
    if not events:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty event payload",
        )

    # --- Subscription validation handshake ---------------------------------
    first_event = events[0]
    if aeg_event_type == "SubscriptionValidation":
        validation_code: str | None = first_event.get("data", {}).get("validationCode")
        if not validation_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Event data missing 'validationCode'",
            )
        logger.info("Event Grid validation handshake received")
        return {"validationResponse": validation_code}

    for raw_event in events:
        try:
            event = EventGridEvent.model_validate(raw_event)
        except ValidationError:
            logger.warning(
                "Skipping invalid Event Grid event payload (id=%s, eventType=%s)",
                raw_event.get("id"),
                raw_event.get("eventType"),
            )
            continue

        if not _is_subscription_created(event):
            logger.debug("Event skipped: %s", event.event_type)
            continue

        subscription_id = _extract_subscription_id(event)
        data = event.data
        if not subscription_id:
            logger.warning("Could not extract subscription ID from: %s", event.subject)
            continue

        logger.info("New subscription received: %s", subscription_id)

        try:
            _result, should_error = await dispatch(
                subscription_id=subscription_id,
                subscription_name=data.get("displayName", ""),
                management_group_id=data.get("managementGroupId", ""),
                settings=_settings,
            )
            if should_error:
                # dead_letter strategy: return 500 so Event Grid retries
                return Response(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error dispatching %s: %s", subscription_id, exc)
            if _settings.retry_strategy == "dead_letter":
                return Response(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response(status_code=status.HTTP_200_OK)


def _is_subscription_created(event: EventGridEvent) -> bool:
    """Check whether the event creates a new subscription."""
    return (
        event.event_type == "Microsoft.Resources.ResourceActionSuccess"
        and "Microsoft.Subscription/aliases/write"
        in event.data.get("operationName", "")
    )


def _extract_subscription_id(event: EventGridEvent) -> str | None:
    """Extract subscription ID from event subject or resource URI."""
    resource_uri = event.data.get("resourceUri", "")
    if resource_uri.startswith("/subscriptions/"):
        parts = resource_uri.split("/")
        if len(parts) > 2 and parts[2]:
            return parts[2]

    if "/subscriptions/" in event.subject:
        parts = event.subject.split("/subscriptions/")
        if len(parts) > 1:
            subscription_id = parts[1].split("/")[0]
            if subscription_id:
                return subscription_id

    return None
