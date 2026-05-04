"""Provisioning workflow package.

Import steps first so all built-in ``@register_step`` decorators fire before
the orchestrator is loaded (and before any extension packages register custom steps).
"""

from __future__ import annotations

# Steps must be imported before engine so that all @register_step
# decorators have run by the time WorkflowEngine.run executes.
from . import steps as _steps  # noqa: F401
from .steps import (  # noqa: F401
    STEP_BUDGET,
    STEP_INITIATIVE,
    STEP_MG,
    STEP_NOTIFY,
    STEP_POLICY,
    STEP_RBAC,
)
from .engine import run_provisioning_workflow, WorkflowEngine  # noqa: F401

# ── Backward-compat re-exports ─────────────────────────────────────────────────
# External code (extensions, tests) that imports from subscription_vending.workflow
# continues to work without modification.  New code should import from the source
# modules directly.
from ..core.context import ProvisioningResult, StepContext  # noqa: F401
from ..core.registry import (  # noqa: F401
    WorkflowStep,
    _EXTRA_STEPS,
    _GATE_STEPS,
    _StepEntry,
    register_gate,
    register_step,
    toposort as _toposort,
)

__all__ = [
    "run_provisioning_workflow",
    "WorkflowEngine",
    "STEP_MG",
    "STEP_INITIATIVE",
    "STEP_RBAC",
    "STEP_POLICY",
    "STEP_BUDGET",
    "STEP_NOTIFY",
    "ProvisioningResult",
    "StepContext",
    "WorkflowStep",
    "_EXTRA_STEPS",
    "_GATE_STEPS",
    "_StepEntry",
    "register_gate",
    "register_step",
]
