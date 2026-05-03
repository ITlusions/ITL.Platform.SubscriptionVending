"""Built-in provisioning workflow extensions.

Every Python module placed in this package is auto-discovered and
imported at startup via :func:`autodiscover`.  A module registers
itself by calling ``.register()`` on a :class:`~subscription_vending.core.base.BaseStep`
instance at import time.

Available extensions:

    webhook_notify  — POST result to an HTTPS webhook (X-Webhook-Secret auth).
                      Requires VENDING_WEBHOOK_URL.
    api_notify      — POST result to a REST API (Bearer token auth).
                      Requires VENDING_API_NOTIFY_URL.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil

logger = logging.getLogger(__name__)


def autodiscover() -> None:
    """Import every module in this package so each one self-registers.

    Skips ``__init__`` and any module whose name starts with ``_``.
    Errors during import are logged and never abort startup.
    """
    for module_info in pkgutil.iter_modules(__path__, prefix=__name__ + "."):
        name = module_info.name
        short = name.rsplit(".", 1)[-1]
        if short.startswith("_"):
            continue
        try:
            importlib.import_module(name)
            logger.debug("autodiscover: loaded extension '%s'", short)
        except Exception:  # noqa: BLE001
            logger.exception("autodiscover: failed to load extension '%s'", short)
