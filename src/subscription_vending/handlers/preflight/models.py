"""Request/response models for the preflight handler."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PreflightRequest(BaseModel):
    """Input for a preflight dry-run check."""

    subscription_id: str = Field(..., description="Subscription ID (real or placeholder)")
    subscription_name: str = Field("preflight-subscription", description="Display name")
    management_group_id: str = Field("", description="Target management group (optional)")
    snow_ticket: str = Field(
        "",
        description=(
            "ServiceNow ticket number to validate (e.g. RITM0041872). "
            "When provided this overrides any tag already on the subscription."
        ),
    )


class PreflightStepResult(BaseModel):
    description: str
    status: str  # "planned" | "blocked"


class PreflightResponse(BaseModel):
    subscription_id: str
    subscription_name: str
    management_group: str
    gate_passed: bool
    steps: list[PreflightStepResult]
    errors: list[str]
    summary: str
