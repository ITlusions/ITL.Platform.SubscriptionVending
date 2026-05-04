"""Domain objects for the provisioning workflow.

``StepContext`` and ``ProvisioningResult`` are pure data containers with no
I/O or framework dependencies.  They can be imported by any layer without
creating circular imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..infrastructure.azure.tags import SubscriptionConfig
    from .config import Settings


@dataclass
class ProvisioningResult:
    """Mutable result object that accumulates workflow outcomes.

    Steps record failures by appending to ``errors``.
    The ``success`` property is ``True`` when no errors have been recorded.
    """

    subscription_id:  str
    management_group: str = ""
    initiative_id:    str = ""
    rbac_roles:       list[str] = field(default_factory=list)
    errors:           list[str] = field(default_factory=list)
    plan:             list[str] = field(default_factory=list)
    dry_run:          bool = False

    @property
    def success(self) -> bool:
        """Return ``True`` when no errors have been recorded."""
        return len(self.errors) == 0


@dataclass
class StepContext:
    """Passed to every workflow step and gate check.

    Attributes:
        subscription_id:           The newly created Azure subscription ID.
        subscription_name:         Display name of the subscription.
        config:                    Tag-derived provisioning config (environment,
                                   budget, owner, etc.).
        settings:                  Service settings / env-var config.
        result:                    Mutable result object — append to
                                   ``result.errors`` on failure.
        dry_run:                   When ``True`` no Azure mutations or outbound
                                   HTTP calls are made.  Steps should log what
                                   *would* happen instead.
        credential:                Azure credential object (``None`` in dry-run
                                   mode).
        event_management_group_id: Management group ID from the Event Grid event
                                   payload.  Used as a fallback by
                                   :data:`~workflow.STEP_MG` when no
                                   ``itl-environment`` tag is present.
    """

    subscription_id:           str
    subscription_name:         str
    config:                    SubscriptionConfig
    settings:                  Settings
    result:                    ProvisioningResult
    dry_run:                   bool = False
    credential:                Any = None
    event_management_group_id: str = ""
