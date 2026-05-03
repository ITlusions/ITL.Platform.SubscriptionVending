"""Built-in provisioning workflow extensions.

Import the ones you want to activate in ``main.py``.  Each module
self-registers on import via ``.register()``.

Available extensions:

    base            — BaseStep ABC; inherit to create custom steps.
    webhook_notify  — POST result to an HTTPS webhook (X-Webhook-Secret auth).
                      Requires VENDING_WEBHOOK_URL.
    api_notify      — POST result to a REST API (Bearer token auth).
                      Requires VENDING_API_NOTIFY_URL.
"""
