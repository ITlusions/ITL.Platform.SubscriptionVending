"""Step and gate registry for the provisioning workflow.

This module owns the two module-level registries (``_EXTRA_STEPS``,
``_GATE_STEPS``), the ``_StepEntry`` dataclass, the topological sorter, and
the public ``register_step`` / ``register_gate`` decorators.

``workflow.py`` imports from here so that custom steps and gate checks can also
import the registries without pulling in the full orchestration logic.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .context import StepContext

logger = logging.getLogger(__name__)

# Type alias for a step or gate coroutine.
WorkflowStep = Callable[["StepContext"], Awaitable[None]]


@dataclass
class _StepEntry:
    fn: WorkflowStep
    depends_on: list[WorkflowStep] = field(default_factory=list)
    stop_on_error: bool = False


_EXTRA_STEPS: list[_StepEntry] = []
_GATE_STEPS:  list[_StepEntry] = []


# ── Public registration helpers ───────────────────────────────────────────────


def register_gate(
    fn: WorkflowStep | None = None,
    *,
    stop_on_error: bool = True,
) -> WorkflowStep | Callable[[WorkflowStep], WorkflowStep]:
    """Register *fn* as a gate check that runs before any provisioning step.

    Gate checks execute in registration order, before the topological step
    graph.  They are ideal for pre-flight validation (e.g. ServiceNow ticket
    checks) that must abort provisioning if they fail.

    ``stop_on_error`` defaults to ``True`` for gate checks because failing a
    gate should prevent the workflow from running.

    Usage::

        from subscription_vending.core.registry import register_gate
        from subscription_vending.core.context import StepContext

        @register_gate
        async def require_snow_ticket(ctx: StepContext) -> None:
            if not ctx.config.snow_ticket:
                ctx.result.errors.append("No ServiceNow ticket on subscription")

    Class-based (via :class:`~core.base.BaseStep`)::

        MyGateStep().register_gate()
    """
    def _register(f: WorkflowStep) -> WorkflowStep:
        _GATE_STEPS.append(_StepEntry(fn=f, depends_on=[], stop_on_error=stop_on_error))
        _name = getattr(f, "__qualname__", type(f).__qualname__)
        logger.debug("Registered gate check: %s", _name)
        return f

    if fn is not None:
        return _register(fn)
    return _register


def register_step(
    fn: WorkflowStep | None = None,
    *,
    depends_on: list[WorkflowStep] | None = None,
    stop_on_error: bool = False,
) -> WorkflowStep | Callable[[WorkflowStep], WorkflowStep]:
    """Register *fn* as a provisioning step.

    Decorated steps are executed in topological order (``depends_on``).
    A raised exception is caught, recorded in ``ctx.result.errors``, and by
    default does **not** prevent remaining steps from running.

    Set ``stop_on_error=True`` to abort all remaining steps when this step
    records an error (either by raising or by appending to
    ``ctx.result.errors``).

    Usage (no dependencies)::

        from subscription_vending.core.registry import register_step
        from subscription_vending.core.context import StepContext

        @register_step
        async def my_step(ctx: StepContext) -> None:
            ...

    Usage (with dependency and stop-on-error)::

        @register_step(depends_on=[my_step], stop_on_error=True)
        async def critical_step(ctx: StepContext) -> None:
            ...
    """
    def _register(f: WorkflowStep) -> WorkflowStep:
        _EXTRA_STEPS.append(
            _StepEntry(fn=f, depends_on=list(depends_on or []), stop_on_error=stop_on_error)
        )
        _name = getattr(f, "__qualname__", type(f).__qualname__)
        logger.debug("Registered workflow step: %s", _name)
        return f

    if fn is not None:
        return _register(fn)
    return _register


# ── Topological sorter ────────────────────────────────────────────────────────


def toposort(entries: list[_StepEntry]) -> list[_StepEntry]:
    """Return step entries ordered so every dependency runs before its dependent.

    Raises ``ValueError`` if a declared dependency is not registered or if a
    dependency cycle is detected.
    """
    fn_to_entry: dict[WorkflowStep, _StepEntry] = {e.fn: e for e in entries}
    visiting: set[WorkflowStep] = set()
    visited:  set[WorkflowStep] = set()
    order:    list[_StepEntry] = []

    def _visit(fn: WorkflowStep) -> None:
        if fn in visited:
            return
        if fn in visiting:
            raise ValueError(
                f"Dependency cycle detected involving step '{fn.__qualname__}'"
            )
        visiting.add(fn)
        entry = fn_to_entry.get(fn)
        if entry:
            for dep in entry.depends_on:
                if dep not in fn_to_entry:
                    raise ValueError(
                        f"Step '{fn.__qualname__}' depends on '{dep.__qualname__}' "
                        "which is not registered."
                    )
                _visit(dep)
        visiting.discard(fn)
        visited.add(fn)
        order.append(fn_to_entry[fn])

    for entry in entries:
        _visit(entry.fn)

    return order
