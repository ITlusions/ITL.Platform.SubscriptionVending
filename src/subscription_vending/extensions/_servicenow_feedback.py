"""Extension: Update the ServiceNow ticket after provisioning completes.

Runs as the last provisioning step (after :data:`STEP_NOTIFY`).  It adds
``work_notes`` to the ticket with the provisioning outcome and, optionally,
transitions the ticket to a new state.

Configuration (environment variables)::

    VENDING_SNOW_INSTANCE          Required.  ServiceNow instance hostname,
                                   e.g. ``mycompany.service-now.com``.
                                   Shared with ``_servicenow_check``.
    VENDING_SNOW_USER              Required.  ServiceNow username (basic auth).
                                   Shared with ``_servicenow_check``.
    VENDING_SNOW_PASSWORD          Required.  ServiceNow password (basic auth).
                                   Shared with ``_servicenow_check``.
    VENDING_SNOW_TABLE             Optional.  Table the ticket lives in.
                                   Default: ``sc_req_item``.
                                   Shared with ``_servicenow_check``.
    VENDING_SNOW_TIMEOUT           Optional.  HTTP timeout in seconds.
                                   Default: ``10``.  Shared with check.
    VENDING_SNOW_SUCCESS_STATE     Optional.  ``state`` value to set when
                                   provisioning succeeds.
                                   Default: ``""`` (do not change state).
                                   Example: ``3`` (= Closed Complete in ITSM).
    VENDING_SNOW_FAILURE_STATE     Optional.  ``state`` value to set when
                                   provisioning fails.
                                   Default: ``""`` (do not change state).
                                   Example: ``4`` (= Closed Incomplete).

The ticket number is read from ``ctx.config.snow_ticket`` (populated from
the ``itl-snow-ticket`` subscription tag, key configurable via
``VENDING_TAG_SNOW_TICKET``).

Register this extension explicitly in ``main.py`` (the ``_`` prefix means it
is **not** auto-discovered)::

    import subscription_vending.extensions._servicenow_feedback  # noqa: F401

When ``VENDING_SNOW_INSTANCE`` is not set the step is a no-op so the
integration is purely opt-in.
"""

from __future__ import annotations

import logging
import os

import httpx

from ..workflow import STEP_NOTIFY, StepContext, register_step

logger = logging.getLogger(__name__)


class ServiceNowFeedbackStep:
    """Post the provisioning outcome back to the ServiceNow ticket.

    The step:

    1. Looks up the ticket's ``sys_id`` via the Table API (same query as the
       check gate, so only one extra round-trip if the check was skipped).
    2. PATCHes the record with a ``work_notes`` entry and, optionally, a new
       ``state`` value.

    Instantiate and register::

        ServiceNowFeedbackStep(
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
        success_state: str = "",
        failure_state: str = "",
        timeout: float = 10.0,
    ) -> None:
        self.instance = instance
        self.user = user
        self.password = password
        self.table = table
        self.success_state = success_state
        self.failure_state = failure_state
        self.timeout = timeout

    async def __call__(self, ctx: StepContext) -> None:
        # Skip if not configured (opt-in)
        if not self.instance:
            return

        ticket = ctx.config.snow_ticket
        if not ticket:
            logger.debug(
                "[%s] ServiceNow feedback skipped: no ticket on subscription.",
                ctx.subscription_id,
            )
            return

        succeeded = ctx.result.success

        if ctx.dry_run:
            logger.info(
                "[dry_run] Would update ServiceNow ticket %r: success=%s",
                ticket,
                succeeded,
            )
            if succeeded:
                ctx.result.plan.append(
                    f"[SNOW feedback] Would post 'Provisioning completed successfully' "
                    f"to ticket {ticket!r}"
                    + (f" and set state to '{self.success_state}'" if self.success_state else "")
                )
            else:
                ctx.result.plan.append(
                    f"[SNOW feedback] Would post error summary to ticket {ticket!r}"
                    + (f" and set state to '{self.failure_state}'" if self.failure_state else "")
                )
            return

        # Build work_notes message
        if succeeded:
            notes = (
                f"[ITL Subscription Vending] Provisioning completed successfully.\n"
                f"Subscription: {ctx.subscription_name} ({ctx.subscription_id})\n"
                f"Management Group: {ctx.result.management_group}"
            )
            new_state = self.success_state
        else:
            error_summary = "\n".join(f"  - {e}" for e in ctx.result.errors)
            notes = (
                f"[ITL Subscription Vending] Provisioning completed with errors.\n"
                f"Subscription: {ctx.subscription_name} ({ctx.subscription_id})\n"
                f"Errors:\n{error_summary}"
            )
            new_state = self.failure_state

        sys_id = await self._get_sys_id(ticket)
        if not sys_id:
            logger.warning(
                "[%s] ServiceNow feedback: ticket %r not found in table '%s' — skipping update.",
                ctx.subscription_id,
                ticket,
                self.table,
            )
            return

        await self._patch_ticket(ctx.subscription_id, ticket, sys_id, notes, new_state)

    async def _get_sys_id(self, ticket_number: str) -> str:
        """Return the sys_id for *ticket_number*, or an empty string if not found."""
        url = f"https://{self.instance}/api/now/table/{self.table}"
        params = {
            "sysparm_query": f"number={ticket_number}",
            "sysparm_fields": "sys_id,number",
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
            return records[0]["sys_id"] if records else ""
        except Exception as exc:  # noqa: BLE001
            logger.warning("ServiceNow sys_id lookup for %r failed: %s", ticket_number, exc)
            return ""

    async def _patch_ticket(
        self,
        subscription_id: str,
        ticket_number: str,
        sys_id: str,
        work_notes: str,
        new_state: str,
    ) -> None:
        """PATCH the ticket record with work_notes and optional state transition."""
        url = f"https://{self.instance}/api/now/table/{self.table}/{sys_id}"
        payload: dict[str, str] = {"work_notes": work_notes}
        if new_state:
            payload["state"] = new_state

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.patch(
                    url,
                    json=payload,
                    auth=(self.user, self.password),
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                )
            resp.raise_for_status()
            logger.info(
                "[%s] ServiceNow ticket %r updated (sys_id=%s, state=%r).",
                subscription_id,
                ticket_number,
                sys_id,
                new_state or "unchanged",
            )
        except Exception as exc:  # noqa: BLE001
            # Feedback failure is non-fatal — log only, do not append to errors
            logger.warning(
                "[%s] ServiceNow feedback update for ticket %r failed: %s",
                subscription_id,
                ticket_number,
                exc,
            )

    def register(self) -> "ServiceNowFeedbackStep":
        """Register this step with the provisioning workflow and return self."""
        register_step(self, depends_on=[STEP_NOTIFY])
        return self


# ── Auto-register when this module is imported ───────────────────────────────
_instance = os.getenv("VENDING_SNOW_INSTANCE", "")
if _instance:
    ServiceNowFeedbackStep(
        instance=_instance,
        user=os.getenv("VENDING_SNOW_USER", ""),
        password=os.getenv("VENDING_SNOW_PASSWORD", ""),
        table=os.getenv("VENDING_SNOW_TABLE", "sc_req_item"),
        success_state=os.getenv("VENDING_SNOW_SUCCESS_STATE", ""),
        failure_state=os.getenv("VENDING_SNOW_FAILURE_STATE", ""),
        timeout=float(os.getenv("VENDING_SNOW_TIMEOUT", "10")),
    ).register()
