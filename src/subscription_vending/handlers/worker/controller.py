"""Business logic for the queue worker handler."""

from __future__ import annotations

import base64
import logging

from fastapi import HTTPException, status

from subscription_vending.core.config import get_settings
from subscription_vending.core.job import ProvisioningJob
from subscription_vending.infrastructure.queue.azure_queue import move_to_dlq
from subscription_vending.workflow import WorkflowEngine
from .models import QueueMessage, WorkerResponse

logger = logging.getLogger(__name__)

_settings = get_settings()
_engine = WorkflowEngine(_settings)


async def handle_process_job(payload: QueueMessage, x_worker_secret: str | None) -> WorkerResponse:
    """Decode and run a ProvisioningJob from a Storage Queue message."""
    if _settings.worker_secret and x_worker_secret != _settings.worker_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid worker secret",
        )

    try:
        raw = base64.b64decode(payload.message).decode()
        job = ProvisioningJob.from_json(raw)
    except Exception as exc:
        logger.error("Failed to decode queue message: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid message",
        ) from exc

    logger.info(
        "Processing job %s for subscription %s (attempt %d/%d)",
        job.job_id,
        job.subscription_id,
        payload.delivery_count,
        _settings.queue_max_delivery_count,
    )

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

    result = await _engine.run(
        subscription_id=job.subscription_id,
        subscription_name=job.subscription_name,
        management_group_id=job.management_group_id,
    )

    if result.errors:
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
