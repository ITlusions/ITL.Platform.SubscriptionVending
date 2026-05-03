"""Base class for custom provisioning steps.

Inherit from :class:`BaseStep`, implement :meth:`execute`, then call
``.register()`` on the instance to add it to the workflow.

Example::

    from subscription_vending.core.base import BaseStep
    from subscription_vending.workflow import StepContext

    class MyStep(BaseStep):
        async def execute(self, ctx: StepContext) -> None:
            ...

    MyStep().register()

``depends_on`` example::

    step_a = MyStep().register()
    MyLaterStep().register(depends_on=[step_a])
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import httpx

from .events import LifecycleEvent, on as _on_event

if TYPE_CHECKING:
    from ..workflow import StepContext, WorkflowStep


class BaseStep(ABC):
    """Abstract base for all custom provisioning steps.

    Provides:

    - ``logger``              -- per-class logger named after the subclass module
    - ``_build_payload(ctx)`` -- standard provisioning result dict shared by all steps
    - ``_http_post(...)``     -- POST JSON to a URL; errors recorded in ctx.result
    - ``on(event)``           -- class-level decorator to subscribe to a lifecycle event
    - ``__call__``            -- wraps ``execute()`` with catch-all error recording
    - ``register()``          -- registers this instance with the workflow
    """

    # Expose lifecycle events so subclasses don't need an extra import
    Event = LifecycleEvent

    @classmethod
    def on(cls, event: LifecycleEvent):  # noqa: A003
        """Subscribe a coroutine to a lifecycle event.

        Can be used as a decorator on any async function::

            class MyStep(BaseStep):
                ...

            @MyStep.on(MyStep.Event.PROVISIONING_SUCCEEDED)
            async def _on_success(ctx) -> None:
                ...

        Or directly via the module-level ``on()`` from ``core.events``.
        """
        return _on_event(event)

    @property
    def logger(self) -> logging.Logger:
        """Logger named after the concrete subclass module and class."""
        return logging.getLogger(f"{type(self).__module__}.{type(self).__qualname__}")

    def _build_payload(self, ctx: StepContext) -> dict:
        """Return the standard provisioning result payload."""
        return {
            "subscription_id":   ctx.subscription_id,
            "subscription_name": ctx.subscription_name,
            "environment":       ctx.config.environment,
            "management_group":  ctx.result.management_group,
            "rbac_roles":        ctx.result.rbac_roles,
            "errors":            list(ctx.result.errors),  # snapshot at call time
            "success":           len(ctx.result.errors) == 0,
        }

    async def _http_post(
        self,
        ctx: StepContext,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
    ) -> bool:
        """POST ``_build_payload(ctx)`` as JSON to *url*.

        Returns ``True`` on success.  HTTP and network errors are caught,
        recorded in ``ctx.result.errors``, and ``False`` is returned.
        """
        if not url:
            self.logger.debug("%s: URL not configured, skipping", type(self).__name__)
            return False

        if ctx.dry_run:
            self.logger.info("DRY RUN: %s would POST to %s", type(self).__name__, url)
            return False

        merged: dict[str, str] = {"Content-Type": "application/json"}
        if headers:
            merged.update(headers)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=self._build_payload(ctx), headers=merged)
                response.raise_for_status()
                self.logger.info("%s: POST %s -> %s", type(self).__name__, url, response.status_code)
                return True
        except httpx.HTTPStatusError as exc:
            ctx.result.errors.append(
                f"{type(self).__name__}: server returned {exc.response.status_code}"
            )
            self.logger.error("%s: HTTP error %s", type(self).__name__, exc)
        except httpx.RequestError as exc:
            ctx.result.errors.append(f"{type(self).__name__}: request failed - {exc}")
            self.logger.error("%s: request error %s", type(self).__name__, exc)
        return False

    @abstractmethod
    async def execute(self, ctx: StepContext) -> None:
        """Implement your step logic here.

        - Catch *known* exceptions yourself and append to ``ctx.result.errors``.
        - Let *unknown* exceptions bubble up -- caught by ``__call__`` with a
          generic message.
        """

    async def __call__(self, ctx: StepContext) -> None:
        try:
            await self.execute(ctx)
        except Exception as exc:  # noqa: BLE001
            name = type(self).__name__
            ctx.result.errors.append(f"{name} failed: {exc}")
            self.logger.exception("%s raised an unhandled exception", name)

    def register(
        self,
        *,
        depends_on: list[WorkflowStep] | None = None,
    ) -> "BaseStep":
        """Register this step with the provisioning workflow.

        Returns *self* so the instance can be stored and used as a dependency::

            step_a = StepA().register()
            StepB().register(depends_on=[step_a])
        """
        from ..workflow import register_step  # noqa: PLC0415
        register_step(self, depends_on=depends_on)
        return self