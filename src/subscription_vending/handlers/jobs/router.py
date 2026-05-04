"""Router for jobs monitoring — GET /jobs/stats, /jobs/list, /jobs/dlq."""

from __future__ import annotations

from fastapi import APIRouter, Query

from ...core.config import get_settings
from .controller import enqueue_job, find_job, peek_queue, purge_dlq, queue_stats
from .models import (
    EnqueueJobRequest,
    EnqueueJobResponse,
    JobLookupResponse,
    JobsListResponse,
    JobsStatsResponse,
    PurgeResponse,
)

router = APIRouter(prefix="/jobs", tags=["Jobs"])
_settings = get_settings()


@router.get(
    "/stats",
    response_model=JobsStatsResponse,
    summary="Approximate message count for both queues",
)
async def stats() -> JobsStatsResponse:
    """Return approximate message counts for the provisioning queue and DLQ."""
    return queue_stats()


@router.get(
    "/list",
    response_model=JobsListResponse,
    summary="Peek pending messages in the provisioning queue (non-destructive)",
)
async def list_jobs(
    count: int = Query(default=10, ge=1, le=32, description="Number of messages to peek"),
) -> JobsListResponse:
    """Peek pending provisioning jobs without removing them from the queue."""
    return peek_queue(_settings.provisioning_queue_name, count)


@router.get(
    "/dlq",
    response_model=JobsListResponse,
    summary="Peek failed jobs in the dead-letter queue (non-destructive)",
)
async def list_dlq(
    count: int = Query(default=10, ge=1, le=32, description="Number of messages to peek"),
) -> JobsListResponse:
    """Peek failed provisioning jobs in the dead-letter queue."""
    return peek_queue(_settings.provisioning_dlq_name, count)


@router.delete(
    "/dlq",
    response_model=PurgeResponse,
    summary="Clear all messages from the dead-letter queue",
)
async def purge_dlq_route() -> PurgeResponse:
    """Delete every message from the dead-letter queue.  Non-reversible."""
    return purge_dlq()


@router.post(
    "/enqueue",
    response_model=EnqueueJobResponse,
    status_code=202,
    summary="Enqueue a job directly to the provisioning queue",
)
async def enqueue_job_route(body: EnqueueJobRequest) -> EnqueueJobResponse:
    """Push a provisioning job onto the queue without going through the webhook."""
    return enqueue_job(body)


# NOTE: this wildcard route must be last so it does not shadow /stats, /list, /dlq
@router.get(
    "/{job_id}",
    response_model=JobLookupResponse,
    summary="Look up a specific job by ID (peeks both queues)",
)
async def get_job(job_id: str) -> JobLookupResponse:
    """Search both the provisioning queue and the DLQ for a job with the given ID."""
    return find_job(job_id)
