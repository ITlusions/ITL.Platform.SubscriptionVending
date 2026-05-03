"""Queue worker — POST /worker/process-job

Processes a single ProvisioningJob from the Storage Queue.
Called by:
  - Azure Functions queue trigger (production)
  - A background polling loop (self-hosted / Kubernetes)
  - curl / test tooling manually

The caller is responsible for:
  - Fetching the message from the queue
  - Deleting the message on success
  - Letting the message reappear (visibility timeout) on failure
  - Moving to DLQ after max_delivery_count failures
"""

from __future__ import annotations

import base64
import logging

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

from ..config import get_settings
from ..retry.models import ProvisioningJob
from ..retry.queue_client import move_to_dlq
from ..workflow import run_provisioning_workflow

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/worker", tags=["Queue Worker"])

_settings = get_settings()


class QueueMessage(BaseModel):
    """A single base64-encoded Storage Queue message as delivered by an Azure Function trigger."""
    message: str               # base64-encoded ProvisioningJob JSON
    delivery_count: int = 1    # How many times this message has been delivered


class WorkerResponse(BaseModel):
    status: str                # "ok" | "error" | "dead_lettered"
    job_id: str = ""
    subscription_id: str = ""
    errors: list[str] = []


@router.post(
    "/process-job",
    response_model=WorkerResponse,
    summary="Process a single provisioning job from the Storage Queue",
)
async def process_job(
    payload: QueueMessage,
    x_worker_secret: str | None = Header(default=None, alias="x-worker-secret"),
) -> WorkerResponse:
    """
    Decode and run a ProvisioningJob.

    On success  → return 200 OK. The caller should delete the queue message.
    On failure  → return 500. The caller should let the message reappear.
    After max_delivery_count failures → move to DLQ and return 200 (so the
    caller deletes the poison message from the work queue).
    """
    # Optional shared-secret guard so the endpoint is not openly callable
    if _settings.worker_secret and x_worker_secret != _settings.worker_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid worker secret")

    # Decode
    try:
        raw = base64.b64decode(payload.message).decode()
        job = ProvisioningJob.from_json(raw)
    except Exception as exc:
        logger.error("Failed to decode queue message: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid message") from exc

    logger.info(
        "Processing job %s for subscription %s (attempt %d/%d)",
        job.job_id,
        job.subscription_id,
        payload.delivery_count,
        _settings.queue_max_delivery_count,
    )

    # Dead-letter threshold reached — move and ack
    if payload.delivery_count > _settings.queue_max_delivery_count:
        logger.error(
            "Job %s exceeded max delivery count (%d) — moving to DLQ",
            job.job_id,
            _settings.queue_max_delivery_count,
        )
        if _settings.storage_account_name:
            move_to_dlq(
                _settings.storage_account_name,
                _settings.provisioning_dlq_name,
                job.to_json(),
            )
        return WorkerResponse(
            status="dead_lettered",
            job_id=job.job_id,
            subscription_id=job.subscription_id,
            errors=[f"Exceeded max delivery count ({_settings.queue_max_delivery_count})"],
        )

    # Run the workflow
    result = await run_provisioning_workflow(
        subscription_id=job.subscription_id,
        subscription_name=job.subscription_name,
        management_group_id=job.management_group_id,
        settings=_settings,
    )

    if result.errors:
        # Return 500 so the caller keeps the message in the queue for retry
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "job_id": job.job_id,
                "subscription_id": job.subscription_id,
                "errors": result.errors,
            },
        )

    return WorkerResponse(
        status="ok",
        job_id=job.job_id,
        subscription_id=job.subscription_id,
    )
