"""Built-in provisioning workflow extensions.

Import the ones you want to activate in ``main.py``.  Each module
self-registers via ``@register_step`` on import.

Available extensions:

    webhook_notify   — POST provisioning result to an HTTPS webhook.
                       Requires VENDING_WEBHOOK_URL env var.
"""
