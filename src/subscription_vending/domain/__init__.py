"""Backward-compat shim — domain objects have moved to core.

New code should import from:
    from subscription_vending.core.context import ProvisioningResult, StepContext
    from subscription_vending.core.job import ProvisioningJob
"""

from ..core.context import ProvisioningResult, StepContext  # noqa: F401
from ..core.job import ProvisioningJob  # noqa: F401

__all__ = ["ProvisioningResult", "StepContext", "ProvisioningJob"]
