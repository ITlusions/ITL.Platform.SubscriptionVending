"""Azure Storage Queue adapter — enqueue and worker helpers.

Used by retry_strategy = "queue".
Requires azure-storage-queue to be installed:
    pip install azure-storage-queue
"""

from __future__ import annotations

import base64
import logging

logger = logging.getLogger(__name__)

try:
    from azure.storage.queue import QueueClient
    from azure.identity import ManagedIdentityCredential
    _QUEUE_AVAILABLE = True
except ImportError:
    _QUEUE_AVAILABLE = False


def _get_queue_client(
    account_name: str,
    queue_name: str,
    *,
    connection_string: str = "",
) -> "QueueClient":
    """Return a QueueClient using Managed Identity (or connection string for local dev)."""
    if not _QUEUE_AVAILABLE:
        raise RuntimeError(
            "azure-storage-queue is not installed. "
            "Run: pip install azure-storage-queue"
        )

    if connection_string:
        return QueueClient.from_connection_string(connection_string, queue_name)

    credential = ManagedIdentityCredential()
    return QueueClient(
        account_url=f"https://{account_name}.queue.core.windows.net",
        queue_name=queue_name,
        credential=credential,
    )


def ensure_queues_exist(account_name: str, queue_name: str, dlq_name: str) -> None:
    """Create the work queue and dead-letter queue if they don't exist yet."""
    for name in (queue_name, dlq_name):
        client = _get_queue_client(account_name, name)
        try:
            client.create_queue()
            logger.info("Queue created: %s", name)
        except Exception:  # noqa: BLE001 — already exists or transient
            pass


def enqueue_job(
    account_name: str,
    queue_name: str,
    job_json: str,
    *,
    connection_string: str = "",
) -> None:
    """Encode and enqueue a ProvisioningJob JSON message."""
    client = _get_queue_client(account_name, queue_name, connection_string=connection_string)
    encoded = base64.b64encode(job_json.encode()).decode()
    client.send_message(encoded)
    logger.info("Job enqueued to %s", queue_name)


def move_to_dlq(
    account_name: str,
    dlq_name: str,
    job_json: str,
    *,
    connection_string: str = "",
) -> None:
    """Write a failed job to the dead-letter queue for manual inspection."""
    client = _get_queue_client(account_name, dlq_name, connection_string=connection_string)
    encoded = base64.b64encode(job_json.encode()).decode()
    client.send_message(encoded)
    logger.warning("Job moved to DLQ %s", dlq_name)
