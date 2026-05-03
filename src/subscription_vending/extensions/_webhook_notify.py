"""Extension: POST a JSON payload to a webhook after every successful provisioning.

Configuration (environment variables)::

    VENDING_WEBHOOK_URL          Required. HTTPS endpoint to POST to.
    VENDING_WEBHOOK_SECRET       Optional. Sent as ``X-Webhook-Secret`` header.
    VENDING_WEBHOOK_TIMEOUT      Optional. Request timeout in seconds (default: 10).

Register this extension in main.py::

    import subscription_vending.extensions.webhook_notify  # noqa: F401
"""

from __future__ import annotations

import os

import httpx

from ..workflow import StepContext
from ..core.base import BaseStep


class WebhookNotifyStep(BaseStep):
    """POST the provisioning result payload to a plain HTTPS webhook.

    Authentication is via a shared secret sent in ``X-Webhook-Secret``.
    """

    def __init__(self, url: str, secret: str = "", timeout: float = 10.0) -> None:
        self.url     = url
        self.secret  = secret
        self.timeout = timeout

    async def execute(self, ctx: StepContext) -> None:
        if not self.url:
            logger.debug("WebhookNotifyStep: URL not configured, skipping")
            return

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.secret:
            headers["X-Webhook-Secret"] = self.secret

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.url, json=self._build_payload(ctx), headers=headers
                )
                response.raise_for_status()
                self.logger.info("WebhookNotifyStep: POST %s -> %s", self.url, response.status_code)
        except httpx.HTTPStatusError as exc:
            ctx.result.errors.append(
                f"WebhookNotifyStep: server returned {exc.response.status_code}"
            )
            self.logger.error("WebhookNotifyStep: HTTP error %s", exc)
        except httpx.RequestError as exc:
            ctx.result.errors.append(f"WebhookNotifyStep: request failed - {exc}")
            self.logger.error("WebhookNotifyStep: request error %s", exc)


# Auto-register when this module is imported.
WebhookNotifyStep(
    url=os.getenv("VENDING_WEBHOOK_URL", ""),
    secret=os.getenv("VENDING_WEBHOOK_SECRET", ""),
    timeout=float(os.getenv("VENDING_WEBHOOK_TIMEOUT", "10")),
).register()
