"""Extension: POST provisioning result to a REST API endpoint with Bearer token auth.

Configuration (environment variables)::

    VENDING_API_NOTIFY_URL       Required. API endpoint to POST to.
    VENDING_API_NOTIFY_TOKEN     Optional. Sent as ``Authorization: Bearer <token>`` header.
    VENDING_API_NOTIFY_TIMEOUT   Optional. Request timeout in seconds (default: 10).

Register this extension in main.py::

    import subscription_vending.extensions.api_notify  # noqa: F401
"""

from __future__ import annotations

import os

from ..workflow import StepContext
from ..core.base import BaseStep


class ApiNotifyStep(BaseStep):
    """POST the provisioning result payload to a REST API with Bearer token auth."""

    def __init__(self, url: str, bearer_token: str = "", timeout: float = 10.0) -> None:
        self.url          = url
        self.bearer_token = bearer_token
        self.timeout      = timeout

    async def execute(self, ctx: StepContext) -> None:
        headers = {"Authorization": f"Bearer {self.bearer_token}"} if self.bearer_token else {}
        await self._http_post(ctx, self.url, headers=headers, timeout=self.timeout)


# Auto-register when this module is imported.
ApiNotifyStep(
    url=os.getenv("VENDING_API_NOTIFY_URL", ""),
    bearer_token=os.getenv("VENDING_API_NOTIFY_TOKEN", ""),
    timeout=float(os.getenv("VENDING_API_NOTIFY_TIMEOUT", "10")),
).register()
