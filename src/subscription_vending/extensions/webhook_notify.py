"""Extension: POST a JSON payload to a webhook after every successful provisioning.

Configuration (environment variables):

    VENDING_WEBHOOK_URL          Required. HTTPS endpoint to POST to.
    VENDING_WEBHOOK_SECRET       Optional. Sent as ``X-Webhook-Secret`` header.
    VENDING_WEBHOOK_TIMEOUT      Optional. Request timeout in seconds (default: 10).

Register this extension in main.py::

    import subscription_vending.extensions.webhook_notify  # noqa: F401
"""

from __future__ import annotations

import logging
import os

import httpx

from ..workflow import StepContext, register_step

logger = logging.getLogger(__name__)

_WEBHOOK_URL    = os.getenv("VENDING_WEBHOOK_URL", "")
_WEBHOOK_SECRET = os.getenv("VENDING_WEBHOOK_SECRET", "")
_TIMEOUT        = float(os.getenv("VENDING_WEBHOOK_TIMEOUT", "10"))


@register_step
async def webhook_notify(ctx: StepContext) -> None:
    """POST provisioning result to the configured webhook URL."""
    if not _WEBHOOK_URL:
        logger.debug("webhook_notify: VENDING_WEBHOOK_URL not set, skipping")
        return

    payload = {
        "subscription_id":   ctx.subscription_id,
        "subscription_name": ctx.subscription_name,
        "environment":       ctx.config.environment,
        "management_group":  ctx.result.management_group,
        "rbac_roles":        ctx.result.rbac_roles,
        "errors":            ctx.result.errors,
        "success":           len(ctx.result.errors) == 0,
    }

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if _WEBHOOK_SECRET:
        headers["X-Webhook-Secret"] = _WEBHOOK_SECRET

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(_WEBHOOK_URL, json=payload, headers=headers)
            response.raise_for_status()
            logger.info(
                "webhook_notify: POST %s → %s", _WEBHOOK_URL, response.status_code
            )
    except httpx.HTTPStatusError as exc:
        ctx.result.errors.append(
            f"webhook_notify: server returned {exc.response.status_code}"
        )
        logger.error("webhook_notify: HTTP error %s", exc)
    except httpx.RequestError as exc:
        ctx.result.errors.append(f"webhook_notify: request failed — {exc}")
        logger.error("webhook_notify: request error %s", exc)
