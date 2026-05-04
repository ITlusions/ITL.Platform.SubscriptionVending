"""Router for the queue worker handler — POST /worker/process-job."""

from __future__ import annotations

from fastapi import APIRouter, Header

from .controller import handle_process_job
from .models import QueueMessage, WorkerResponse

router = APIRouter(prefix="/worker", tags=["Queue Worker"])


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
    return await handle_process_job(payload, x_worker_secret)
