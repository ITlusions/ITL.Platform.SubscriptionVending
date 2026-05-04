"""Response models for the jobs handler."""

from __future__ import annotations

from pydantic import BaseModel


class QueueJob(BaseModel):
    job_id: str = ""
    subscription_id: str = ""
    subscription_name: str = ""
    management_group_id: str = ""
    attempt: int = 1


class JobsListResponse(BaseModel):
    queue: str
    count: int
    messages: list[QueueJob]


class QueueStat(BaseModel):
    queue: str
    approximate_message_count: int | None = None
    error: str | None = None


class JobsStatsResponse(BaseModel):
    provisioning: QueueStat
    dead_letter: QueueStat


class PurgeResponse(BaseModel):
    queue: str
    deleted: int | None = None  # approximate; None when Azure doesn't report count


class JobLookupResponse(BaseModel):
    found: bool
    queue: str | None = None
    job: QueueJob | None = None


class EnqueueJobRequest(BaseModel):
    job_id: str = ""          # auto-generated UUID when empty
    subscription_id: str
    subscription_name: str
    management_group_id: str = ""
    attempt: int = 1


class EnqueueJobResponse(BaseModel):
    job_id: str
    message_id: str
    queue: str
