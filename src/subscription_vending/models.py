"""Pydantic models for Event Grid webhook requests and responses.

.. deprecated::
    Import directly from :mod:`subscription_vending.schemas.event_grid`.
    This module re-exports those classes for backward compatibility.
"""

from __future__ import annotations

from .schemas.event_grid import (  # noqa: F401
    EventGridEvent,
    EventGridEventData,
    HealthResponse,
    WebhookResponse,
)

__all__ = [
    "EventGridEvent",
    "EventGridEventData",
    "HealthResponse",
    "WebhookResponse",
]
