"""Request/response models for the queue worker handler."""

from __future__ import annotations

from pydantic import BaseModel


class QueueMessage(BaseModel):
    """A single base64-encoded Storage Queue message as delivered by an Azure Function trigger."""

    message: str               # base64-encoded ProvisioningJob JSON
    delivery_count: int = 1    # How many times this message has been delivered


class WorkerResponse(BaseModel):
    status: str                # "ok" | "error" | "dead_lettered"
    job_id: str = ""
    subscription_id: str = ""
    errors: list[str] = []
