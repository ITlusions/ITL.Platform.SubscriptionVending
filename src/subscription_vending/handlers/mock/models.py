"""Request/response models for the mock webhook handler."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MockEventRequest(BaseModel):
    """Simplified request body for triggering a mock provisioning run."""

    subscription_id: str = Field(..., description="Subscription ID to provision")
    subscription_name: str = Field("mock-subscription", description="Display name")
    management_group_id: str = Field("", description="Target management group (optional)")
    dry_run: bool = Field(False, description="When true, log what would happen without making any Azure calls")
