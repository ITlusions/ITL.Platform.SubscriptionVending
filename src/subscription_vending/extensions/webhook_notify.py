"""Extension: POST a JSON payload to a webhook after every successful provisioning.

Configuration (environment variables)::

    VENDING_WEBHOOK_URL          Required. HTTPS endpoint to POST to.
    VENDING_WEBHOOK_SECRET       Optional. Sent as ``X-Webhook-Secret`` header.
    VENDING_WEBHOOK_TIMEOUT      Optional. Request timeout in seconds (default: 10).

This extension is auto-discovered and self-registers at startup.
It is a no-op when ``VENDING_WEBHOOK_URL`` is not set.
"""

from __future__ import annotations

import os

from . import BaseStep, StepContext


class WebhookNotifyStep(BaseStep):
    """POST the provisioning result payload to a plain HTTPS webhook.

    Authentication is via a shared secret sent in ``X-Webhook-Secret``.
    """

    def __init__(self, url: str, secret: str = "", timeout: float = 10.0) -> None:
        self.url     = url
        self.secret  = secret
        self.timeout = timeout

    async def execute(self, ctx: StepContext) -> None:
        headers = {"X-Webhook-Secret": self.secret} if self.secret else {}
        await self._http_post(ctx, self.url, headers=headers, timeout=self.timeout)


# Auto-register when this module is imported.
WebhookNotifyStep(
    url=os.getenv("VENDING_WEBHOOK_URL", ""),
    secret=os.getenv("VENDING_WEBHOOK_SECRET", ""),
    timeout=float(os.getenv("VENDING_WEBHOOK_TIMEOUT", "10")),
).register()
