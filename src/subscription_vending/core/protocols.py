"""Port contracts (Protocols) for the subscription vending service.

These structural interfaces decouple the workflow orchestrator from concrete
Azure SDK implementations.  Any object that satisfies the structural type
(duck typing) is a valid adapter — no inheritance required.

Usage in tests::

    class InMemoryManagementGroupPort:
        async def move_subscription(self, subscription_id, management_group_id, settings):
            ...   # in-memory stub; satisfies ManagementGroupPort

This allows ``workflow.py`` to be tested without real Azure credentials.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .domain.context import ProvisioningResult
    from .config import Settings


@runtime_checkable
class ManagementGroupPort(Protocol):
    """Move a subscription to an Azure Management Group."""

    async def move_subscription(
        self,
        subscription_id: str,
        management_group_id: str,
        settings: Settings,
    ) -> None:
        """Move *subscription_id* to *management_group_id*."""
        ...


@runtime_checkable
class RbacPort(Protocol):
    """Assign default RBAC roles on a subscription."""

    async def create_initial_rbac(
        self,
        subscription_id: str,
        settings: Settings,
    ) -> list[str]:
        """Assign default roles; return list of role assignment IDs."""
        ...


@runtime_checkable
class PolicyPort(Protocol):
    """Assign Azure Policy definitions and initiatives."""

    async def assign_default_policies(
        self,
        subscription_id: str,
        settings: Settings,
    ) -> None:
        """Assign default policy definitions to *subscription_id*."""
        ...

    async def attach_foundation_initiative(
        self,
        authorization_url: str,
        subscription_id: str,
    ) -> str:
        """Attach the ITL Foundation Policy Initiative; return initiative ID."""
        ...


@runtime_checkable
class NotificationPort(Protocol):
    """Publish outbound provisioning events."""

    async def publish_provisioned_event(
        self,
        result: ProvisioningResult,
        subscription_name: str,
        settings: Settings,
    ) -> None:
        """Publish a SubscriptionProvisioned event to Event Grid."""
        ...


@runtime_checkable
class TagReaderPort(Protocol):
    """Read subscription tags and derive provisioning configuration."""

    async def read_subscription_config(
        self,
        credential: object,
        subscription_id: str,
        settings: Settings,
    ) -> object:
        """Return a :class:`~azure.tags.SubscriptionConfig` for *subscription_id*."""
        ...
