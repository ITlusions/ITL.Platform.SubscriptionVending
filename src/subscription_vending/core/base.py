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

from ..workflow import StepContext, WorkflowStep, register_step


class BaseStep(ABC):
    """Abstract base for all custom provisioning steps.

    Provides:

    - ``logger``              -- per-class logger named after the subclass module
    - ``_build_payload(ctx)`` -- standard provisioning result dict shared by all steps
    - ``__call__``            -- wraps ``execute()`` with catch-all error recording
    - ``register()``          -- registers this instance with the workflow
    """

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
        register_step(self, depends_on=depends_on)
        return self