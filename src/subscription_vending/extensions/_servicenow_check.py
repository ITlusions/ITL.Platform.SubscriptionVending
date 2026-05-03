"""Extension: Verify an approved ServiceNow ticket exists before provisioning.

The check runs as a *gate* — it executes before any Azure mutation step.  If
the ticket is missing or not approved the workflow is aborted immediately.

Configuration (environment variables)::

    VENDING_SNOW_INSTANCE        Required.  ServiceNow instance hostname,
                                 e.g. ``mycompany.service-now.com``.
    VENDING_SNOW_USER            Required.  ServiceNow username (basic auth).
    VENDING_SNOW_PASSWORD        Required.  ServiceNow password (basic auth).
    VENDING_SNOW_TABLE           Optional.  Table to query.
                                 Default: ``sc_req_item`` (Request Items).
                                 Use ``change_request`` for CHG tickets.
    VENDING_SNOW_REQUIRE_STATE   Optional.  Required value of the ``approval``
                                 or ``state`` field on the found record.
                                 Default: ``approved``.
                                 Set to ``""`` to skip state validation
                                 (existence-only check).
    VENDING_SNOW_TIMEOUT         Optional.  HTTP timeout in seconds.
                                 Default: ``10``.

The ticket number is read from the tag configured by ``VENDING_TAG_SNOW_TICKET``
(default key: ``itl-snow-ticket``) on the subscription.

Register this extension explicitly in ``main.py`` (the ``_`` prefix means it
is **not** auto-discovered)::

    import subscription_vending.extensions._servicenow_check  # noqa: F401

When ``VENDING_SNOW_INSTANCE`` is not set the gate is skipped silently so the
integration is purely opt-in.
"""

from __future__ import annotations

import os

import httpx

from ..workflow import StepContext, register_gate


class ServiceNowCheckGate:
    """Gate: verify that an approved ServiceNow ticket exists for the subscription.

    Instantiate and register via :func:`register_gate`::

        ServiceNowCheckGate(
            instance="myco.service-now.com",
            user="svc_vending",
            password="...",
        ).register()
    """

    def __init__(
        self,
        instance: str,
        user: str,
        password: str,
        table: str = "sc_req_item",
        require_state: str = "approved",
        timeout: float = 10.0,
    ) -> None:
        self.instance = instance
        self.user = user
        self.password = password
        self.table = table
        self.require_state = require_state
        self.timeout = timeout

    async def __call__(self, ctx: StepContext) -> None:
        # Skip if no instance configured (opt-in feature)
        if not self.instance:
            return

        ticket = ctx.config.snow_ticket
        if not ticket:
            ctx.result.errors.append(
                f"ServiceNow gate failed: no ticket number on subscription "
                f"(expected tag '{ctx.settings.tag_snow_ticket}')."
            )
            return

        if ctx.dry_run:
            import logging  # noqa: PLC0415
            logging.getLogger(__name__).info(
                "[dry_run] Would validate ServiceNow ticket %r against %s/%s",
                ticket,
                self.instance,
                self.table,
            )
            return

        url = f"https://{self.instance}/api/now/table/{self.table}"
        params = {
            "sysparm_query": f"number={ticket}",
            "sysparm_fields": "number,state,approval,short_description",
            "sysparm_limit": "1",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    url,
                    params=params,
                    auth=(self.user, self.password),
                    headers={"Accept": "application/json"},
                )
            resp.raise_for_status()
            records = resp.json().get("result", [])
        except Exception as exc:  # noqa: BLE001
            ctx.result.errors.append(
                f"ServiceNow lookup for ticket {ticket!r} failed: {exc}"
            )
            return

        if not records:
            ctx.result.errors.append(
                f"ServiceNow ticket {ticket!r} not found in table '{self.table}'."
            )
            return

        record = records[0]

        if self.require_state:
            approval = record.get("approval", "")
            state = str(record.get("state", ""))
            if approval != self.require_state and state != self.require_state:
                ctx.result.errors.append(
                    f"ServiceNow ticket {ticket!r} is not in required state "
                    f"'{self.require_state}' "
                    f"(approval={approval!r}, state={state!r})."
                )
                return

        import logging  # noqa: PLC0415
        logging.getLogger(__name__).info(
            "[%s] ServiceNow gate passed: ticket %r OK (table=%s, approval=%s).",
            ctx.subscription_id,
            ticket,
            self.table,
            record.get("approval", ""),
        )

    def register(self) -> "ServiceNowCheckGate":
        """Register this gate with the provisioning workflow and return self."""
        register_gate(self)
        return self


# ── Auto-register when this module is imported ───────────────────────────────
_instance = os.getenv("VENDING_SNOW_INSTANCE", "")
if _instance:
    ServiceNowCheckGate(
        instance=_instance,
        user=os.getenv("VENDING_SNOW_USER", ""),
        password=os.getenv("VENDING_SNOW_PASSWORD", ""),
        table=os.getenv("VENDING_SNOW_TABLE", "sc_req_item"),
        require_state=os.getenv("VENDING_SNOW_REQUIRE_STATE", "approved"),
        timeout=float(os.getenv("VENDING_SNOW_TIMEOUT", "10")),
    ).register()
