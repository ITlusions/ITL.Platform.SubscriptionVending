"""Retry dispatcher — routes a provisioning trigger to the configured strategy.

Strategies
----------
none (default)
    Run the workflow inline in the Event Grid handler. Fire-and-forget.
    No retry on failure.

queue
    Encode the job as a ProvisioningJob and enqueue it to an Azure Storage
    Queue.  A separate worker (queue trigger or /worker/process-job) picks
    it up and retries on failure up to queue_max_delivery_count times before
    moving to the dead-letter queue.

dead_letter
    Run the workflow inline.  On failure, return a non-200 response to Event
    Grid so it retries the delivery automatically (up to its own retry policy,
    typically 24 hours / 30 attempts).  After exhausting retries, Event Grid
    writes the event to the configured dead-letter storage container.

    NOTE: This strategy requires configuring a dead-letter destination on the
    Event Grid subscription in Bicep/ARM.  See infra/modules/mgVendingRoleAssignment.bicep
    for deployment context.  The event_grid.py handler must propagate the
    non-200 response when this strategy is active.
"""

from __future__ import annotations

import logging

from ..config import Settings
from ..core.enums import RetryStrategy
from ..domain.job import ProvisioningJob
from ..retry.azure_queue import enqueue_job, ensure_queues_exist
from ..workflow import ProvisioningResult, WorkflowEngine

logger = logging.getLogger(__name__)

# Queues are created lazily on first use so startup is not blocked.
_queues_ensured: bool = False


async def dispatch(
    subscription_id: str,
    subscription_name: str,
    management_group_id: str,
    settings: Settings,
) -> tuple[ProvisioningResult | None, bool]:
    """
    Dispatch a provisioning job according to settings.retry_strategy.

    Returns
    -------
    result
        The ProvisioningResult for "none" and "dead_letter" strategies.
        None for "queue" (result is not available synchronously).
    should_return_error
        True when the HTTP response to Event Grid should be non-200.
        Only relevant for "dead_letter" on failure.
    """
    strategy = RetryStrategy(settings.retry_strategy.lower())

    # ------------------------------------------------------------------ #
    # Strategy: none                                                       #
    # ------------------------------------------------------------------ #
    if strategy == RetryStrategy.NONE:
        result = await WorkflowEngine(settings).run(
            subscription_id=subscription_id,
            subscription_name=subscription_name,
            management_group_id=management_group_id,
        )
        return result, False

    # ------------------------------------------------------------------ #
    # Strategy: queue                                                      #
    # ------------------------------------------------------------------ #
    if strategy == RetryStrategy.QUEUE:
        if not settings.storage_account_name:
            logger.error(
                "retry_strategy=queue but VENDING_STORAGE_ACCOUNT_NAME is not set — "
                "falling back to inline execution"
            )
            result = await WorkflowEngine(settings).run(
                subscription_id=subscription_id,
                subscription_name=subscription_name,
                management_group_id=management_group_id,
            )
            return result, False

        global _queues_ensured
        if not _queues_ensured:
            ensure_queues_exist(
                settings.storage_account_name,
                settings.provisioning_queue_name,
                settings.provisioning_dlq_name,
            )
            _queues_ensured = True

        job = ProvisioningJob(
            subscription_id=subscription_id,
            subscription_name=subscription_name,
            management_group_id=management_group_id,
        )
        enqueue_job(
            settings.storage_account_name,
            settings.provisioning_queue_name,
            job.to_json(),
        )
        logger.info(
            "Job %s enqueued for subscription %s",
            job.job_id,
            subscription_id,
        )
        return None, False

    # ------------------------------------------------------------------ #
    # Strategy: dead_letter                                                #
    # ------------------------------------------------------------------ #
    if strategy == RetryStrategy.DEAD_LETTER:
        result = await WorkflowEngine(settings).run(
            subscription_id=subscription_id,
            subscription_name=subscription_name,
            management_group_id=management_group_id,
        )
        # Signal to the caller to return non-200 so Event Grid retries
        should_return_error = not result.success
        if should_return_error:
            logger.warning(
                "Provisioning failed for %s — returning non-200 so Event Grid retries",
                subscription_id,
            )
        return result, should_return_error

    # Unknown strategy — warn and fall back to inline
    logger.warning("Unknown retry_strategy=%r — falling back to inline (none)", strategy)
    result = await WorkflowEngine(settings).run(
        subscription_id=subscription_id,
        subscription_name=subscription_name,
        management_group_id=management_group_id,
    )
    return result, False
