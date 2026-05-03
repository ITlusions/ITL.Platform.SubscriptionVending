"""Pydantic schemas for Event Grid webhook requests and responses.

These are HTTP surface contracts — they live in ``schemas/`` and must never
be imported by domain or service logic.  Convert to/from domain objects at
the handler boundary.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EventGridEventData(BaseModel):
    """Payload inside an Event Grid event's ``data`` field."""

    subscription_id: str = Field(..., description="The newly created Azure subscription ID")
    subscription_name: str = Field("", description="Display name of the subscription")
    management_group_id: str = Field("", description="Target management group ID")
    additional_properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Any additional properties from the event",
    )


class EventGridEvent(BaseModel):
    """Single Event Grid event envelope (CloudEvents or legacy schema)."""

    id: str
    subject: str
    event_type: str = Field(..., alias="eventType")
    data: dict[str, Any]
    data_version: str = Field("", alias="dataVersion")
    event_time: str = Field("", alias="eventTime")
    topic: str = ""

    model_config = {"populate_by_name": True}


class WebhookResponse(BaseModel):
    """Standard response returned by webhook handlers."""

    status: str
    message: str = ""
    subscription_id: str = ""


class HealthResponse(BaseModel):
    """Response model for the ``/health`` endpoint."""

    status: str
