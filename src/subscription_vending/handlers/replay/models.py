"""Request/response models for the replay handler."""

from __future__ import annotations

from pydantic import BaseModel


class ReplayRequest(BaseModel):
    subscription_id: str
    subscription_name: str = ""
    management_group_id: str = ""
    dry_run: bool = False


class ReplayResponse(BaseModel):
    status: str                   # "ok" | "error"
    subscription_id: str
    errors: list[str] = []
    plan: list[str] = []          # populated when dry_run=True
