"""Exception hierarchy for the subscription vending service.

All application exceptions inherit from :class:`AppError` so callers can
catch the base type when they need to handle any known error.

Hierarchy::

    AppError
    ├── ProvisioningError          # workflow-level failures
    │   ├── GateCheckFailed        # a gate check blocked provisioning
    │   └── StepFailed             # a provisioning step failed
    ├── AzureIntegrationError      # Azure SDK / API errors
    │   ├── ManagementGroupError
    │   ├── RbacError
    │   ├── PolicyError
    │   └── NotificationError
    ├── ConfigurationError         # missing or invalid configuration
    └── AuthorizationError         # request authentication / authorisation
"""

from __future__ import annotations


class AppError(Exception):
    """Base class for all application errors."""

    def __init__(self, message: str, *, code: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.code = code

    def __str__(self) -> str:
        return self.message


# ── Provisioning errors ───────────────────────────────────────────────────────


class ProvisioningError(AppError):
    """Raised when the provisioning workflow fails."""


class GateCheckFailed(ProvisioningError):
    """Raised when a gate check blocks provisioning.

    Attributes:
        gate_name: Name of the gate that failed.
    """

    def __init__(self, message: str, *, gate_name: str = "", code: str = "") -> None:
        super().__init__(message, code=code)
        self.gate_name = gate_name


class StepFailed(ProvisioningError):
    """Raised when a provisioning step encounters a fatal error.

    Attributes:
        step_name: Name of the step that failed.
    """

    def __init__(self, message: str, *, step_name: str = "", code: str = "") -> None:
        super().__init__(message, code=code)
        self.step_name = step_name


# ── Azure integration errors ──────────────────────────────────────────────────


class AzureIntegrationError(AppError):
    """Base class for Azure SDK / REST API failures."""


class ManagementGroupError(AzureIntegrationError):
    """Raised when moving a subscription to a management group fails."""


class RbacError(AzureIntegrationError):
    """Raised when assigning RBAC roles fails."""


class PolicyError(AzureIntegrationError):
    """Raised when assigning policies or initiatives fails."""


class NotificationError(AzureIntegrationError):
    """Raised when publishing an outbound Event Grid event fails."""


# ── Configuration errors ──────────────────────────────────────────────────────


class ConfigurationError(AppError):
    """Raised when required configuration is missing or invalid."""


# ── Authorization errors ──────────────────────────────────────────────────────


class AuthorizationError(AppError):
    """Raised when a request cannot be authenticated or is forbidden."""
