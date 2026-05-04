"""Built-in provisioning workflow extensions.

Every module in this package is auto-discovered and imported at startup via
:func:`autodiscover`.  A module self-registers by calling ``.register()`` on
a :class:`~subscription_vending.core.base.BaseStep` instance at import time.

Available extensions (all opt-in via environment variables):

    webhook_notify      -- POST result to an HTTPS webhook (``VENDING_WEBHOOK_URL``).
    api_notify          -- POST result to a REST API (``VENDING_API_NOTIFY_URL``).
    servicenow_check    -- Gate: require an approved SNow ticket (``VENDING_SNOW_INSTANCE``).
    servicenow_feedback -- Update the SNow ticket after provisioning (``VENDING_SNOW_INSTANCE``).

No manual wiring is required.  Set the relevant environment variables and
the extension activates automatically.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil

# Re-export everything an extension module needs so authors only write:
#   from . import BaseStep, StepContext, register_step, ...
from ..core.base import BaseStep as BaseStep  # noqa: F401
from ..core.context import StepContext as StepContext  # noqa: F401
from ..core.registry import register_gate as register_gate, register_step as register_step  # noqa: F401
from ..workflow import (  # noqa: F401
    STEP_BUDGET as STEP_BUDGET,
    STEP_INITIATIVE as STEP_INITIATIVE,
    STEP_MG as STEP_MG,
    STEP_NOTIFY as STEP_NOTIFY,
    STEP_POLICY as STEP_POLICY,
    STEP_RBAC as STEP_RBAC,
)

logger = logging.getLogger(__name__)


def autodiscover() -> None:
    """Import every module in this package so each one self-registers.

    Skips ``__init__`` and any module whose name starts with ``_``.
    Errors during import are logged and never abort startup.
    """
    for module_info in pkgutil.iter_modules(__path__, prefix=__name__ + "."):
        name = module_info.name
        short = name.rsplit(".", 1)[-1]
        if short.startswith("__"):
            continue
        try:
            importlib.import_module(name)
            logger.debug("autodiscover: loaded extension '%s'", short)
        except Exception:  # noqa: BLE001
            logger.exception("autodiscover: failed to load extension '%s'", short)
