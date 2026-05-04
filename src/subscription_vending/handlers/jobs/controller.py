"""Business logic for the jobs handler."""

from __future__ import annotations

import base64
import json
import logging

from ...core.config import get_settings
from .models import (
    EnqueueJobRequest,
    EnqueueJobResponse,
    JobLookupResponse,
    JobsListResponse,
    JobsStatsResponse,
    PurgeResponse,
    QueueJob,
    QueueStat,
)

logger = logging.getLogger(__name__)

_settings = get_settings()


def _get_queue_client(queue_name: str):
    try:
        from azure.storage.queue import QueueClient  # noqa: PLC0415
        from azure.identity import DefaultAzureCredential  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError("azure-storage-queue is not installed") from exc

    conn_str = getattr(_settings, "storage_connection_string", "")
    if conn_str:
        return QueueClient.from_connection_string(conn_str, queue_name)

    account = _settings.storage_account_name
    if not account:
        raise RuntimeError("VENDING_STORAGE_ACCOUNT_NAME is not configured")

    return QueueClient(
        account_url=f"https://{account}.queue.core.windows.net",
        queue_name=queue_name,
        credential=DefaultAzureCredential(),
    )


def _decode(raw: str) -> QueueJob:
    try:
        data = json.loads(base64.b64decode(raw).decode())
        return QueueJob(**{k: v for k, v in data.items() if k in QueueJob.model_fields})
    except Exception:  # noqa: BLE001
        return QueueJob(subscription_id=raw[:80])


def peek_queue(queue_name: str, count: int) -> JobsListResponse:
    client = _get_queue_client(queue_name)
    msgs = list(client.peek_messages(max_messages=min(count, 32)))
    return JobsListResponse(
        queue=queue_name,
        count=len(msgs),
        messages=[_decode(m.content) for m in msgs],
    )


def queue_stats() -> JobsStatsResponse:
    def _stat(name: str) -> QueueStat:
        try:
            props = _get_queue_client(name).get_queue_properties()
            return QueueStat(queue=name, approximate_message_count=props.approximate_message_count)
        except Exception as exc:  # noqa: BLE001
            return QueueStat(queue=name, error=str(exc))

    return JobsStatsResponse(
        provisioning=_stat(_settings.provisioning_queue_name),
        dead_letter=_stat(_settings.provisioning_dlq_name),
    )


def purge_dlq() -> PurgeResponse:
    """Delete all messages from the dead-letter queue.  Returns approximate count removed."""
    client = _get_queue_client(_settings.provisioning_dlq_name)
    try:
        props = client.get_queue_properties()
        count: int | None = props.approximate_message_count
    except Exception:  # noqa: BLE001
        count = None
    client.clear_messages()
    return PurgeResponse(queue=_settings.provisioning_dlq_name, deleted=count)


def find_job(job_id: str) -> JobLookupResponse:
    """Peek both queues and return the first message matching job_id."""
    for queue_name in (_settings.provisioning_queue_name, _settings.provisioning_dlq_name):
        try:
            client = _get_queue_client(queue_name)
            msgs = list(client.peek_messages(max_messages=32))
            for m in msgs:
                job = _decode(m.content)
                if job.job_id == job_id:
                    return JobLookupResponse(found=True, queue=queue_name, job=job)
        except Exception:  # noqa: BLE001
            continue
    return JobLookupResponse(found=False)


def enqueue_job(request: EnqueueJobRequest) -> EnqueueJobResponse:
    """Enqueue a job directly to the provisioning queue (bypasses the webhook)."""
    import uuid  # noqa: PLC0415

    job_id = request.job_id or str(uuid.uuid4())
    payload = {
        "job_id": job_id,
        "subscription_id": request.subscription_id,
        "subscription_name": request.subscription_name,
        "management_group_id": request.management_group_id,
        "attempt": request.attempt,
    }
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    client = _get_queue_client(_settings.provisioning_queue_name)
    result = client.send_message(encoded)
    return EnqueueJobResponse(
        job_id=job_id,
        message_id=result.id,
        queue=_settings.provisioning_queue_name,
    )
