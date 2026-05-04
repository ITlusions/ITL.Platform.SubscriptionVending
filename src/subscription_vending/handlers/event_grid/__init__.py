"""Event Grid handler package."""

from __future__ import annotations

from .models import EventGridEvent
from .controller import (
    _settings,
    handle_event_grid_delivery,
    verify_sas_key,
    is_subscription_created,
    extract_subscription_id,
)
from .router import router
from . import controller  # noqa: F401 — exposed for test patching

# Private aliases kept for backward compat with existing tests
_is_subscription_created = is_subscription_created
_extract_subscription_id = extract_subscription_id

__all__ = [
    "router",
    "controller",
    "EventGridEvent",
    "_settings",
    "handle_event_grid_delivery",
    "verify_sas_key",
    "is_subscription_created",
    "extract_subscription_id",
    "_is_subscription_created",
    "_extract_subscription_id",
]
