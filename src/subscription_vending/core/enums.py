"""Core enumerations shared across all layers."""

from __future__ import annotations

from enum import Enum


class RetryStrategy(str, Enum):
    """Provisioning retry strategies.

    none
        Run the workflow inline. No retry on failure.
    queue
        Enqueue to an Azure Storage Queue; a worker retries on failure.
    dead_letter
        Return non-200 to Event Grid on failure so it retries automatically
        and eventually dead-letters after exhausting its retry policy.
    """

    NONE = "none"
    QUEUE = "queue"
    DEAD_LETTER = "dead_letter"
