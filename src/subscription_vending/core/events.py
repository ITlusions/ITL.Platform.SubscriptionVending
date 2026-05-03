"""Lifecycle event bus for the provisioning workflow.

Extensions can subscribe to named lifecycle events and react without
modifying the core workflow.

Usage — subscribe in any extension module::

    from subscription_vending.core.events import LifecycleEvent, on

    @on(LifecycleEvent.PROVISIONING_SUCCEEDED)
    async def notify_on_success(ctx) -> None:
        ...

    @on(LifecycleEvent.PROVISIONING_FAILED)
    async def alert_on_failure(ctx) -> None:
        ...

The workflow fires events automatically; extensions just listen.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from enum import Enum, auto
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

# Type alias for event handler coroutines
EventHandler = Callable[["StepContext"], Awaitable[None]]  # type: ignore[name-defined]


class LifecycleEvent(Enum):
    """Named points in the provisioning lifecycle."""

    PROVISIONING_STARTED   = auto()  # before any step runs
    PROVISIONING_SUCCEEDED = auto()  # all steps done, no errors
    PROVISIONING_FAILED    = auto()  # all steps done, at least one error
    PROVISIONING_COMPLETED = auto()  # always fires (success or failure)


# Module-level registry: event → list of handlers
_HANDLERS: dict[LifecycleEvent, list[EventHandler]] = defaultdict(list)


def on(event: LifecycleEvent) -> Callable[[EventHandler], EventHandler]:
    """Register a coroutine as a handler for *event*.

    Example::

        @on(LifecycleEvent.PROVISIONING_SUCCEEDED)
        async def my_handler(ctx: StepContext) -> None:
            ...
    """
    def _decorator(fn: EventHandler) -> EventHandler:
        _HANDLERS[event].append(fn)
        logger.debug("Registered handler '%s' for event %s", fn.__qualname__, event.name)
        return fn
    return _decorator


async def emit(event: LifecycleEvent, ctx: "StepContext") -> None:  # type: ignore[name-defined]
    """Fire *event*, calling every registered handler in order.

    Errors in handlers are caught, logged, and recorded in ``ctx.result.errors``
    so they never abort the remaining handlers or the workflow.
    """
    handlers = _HANDLERS.get(event, [])
    if not handlers:
        return
    logger.debug("Emitting %s (%d handler(s))", event.name, len(handlers))
    for fn in handlers:
        try:
            await fn(ctx)
        except Exception as exc:  # noqa: BLE001
            ctx.result.errors.append(f"Event handler '{fn.__qualname__}' failed: {exc}")
            logger.exception("Handler '%s' raised for event %s", fn.__qualname__, event.name)
