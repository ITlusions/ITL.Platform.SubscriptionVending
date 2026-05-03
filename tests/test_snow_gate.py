"""Tests for the gate mechanism, ServiceNow check gate, and ServiceNow feedback step."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("VENDING_AZURE_TENANT_ID", "test-tenant-id")

from subscription_vending.workflow import (  # noqa: E402
    ProvisioningResult,
    StepContext,
    _GATE_STEPS,
    register_gate,
    run_provisioning_workflow,
)
from subscription_vending.config import Settings  # noqa: E402
from subscription_vending.azure.tags import SubscriptionConfig  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(**kwargs) -> Settings:
    defaults = {
        "azure_tenant_id": "test-tenant-id",
        "azure_client_id": "test-client-id",
        "azure_client_secret": "test-secret",
        "root_management_group": "ITL",
        "authorization_service_url": "http://auth-service:8004",
    }
    defaults.update(kwargs)
    return Settings.model_construct(**defaults)


def _make_config(snow_ticket: str = "") -> SubscriptionConfig:
    cfg = MagicMock(spec=SubscriptionConfig)
    cfg.management_group_name = "ITL-Sandbox"
    cfg.budget_eur = 0
    cfg.owner_email = ""
    cfg.environment = "sandbox"
    cfg.aks_enabled = False
    cfg.snow_ticket = snow_ticket
    return cfg


def _make_ctx(snow_ticket: str = "", dry_run: bool = False) -> StepContext:
    settings = _make_settings()
    settings.tag_snow_ticket = "itl-snow-ticket"
    return StepContext(
        subscription_id="sub-test",
        subscription_name="Test Subscription",
        config=_make_config(snow_ticket=snow_ticket),
        settings=settings,
        result=ProvisioningResult(subscription_id="sub-test"),
        dry_run=dry_run,
    )


_PATCH_ALL = dict(
    read_sub=patch(
        "subscription_vending.workflow.read_subscription_config",
        AsyncMock(return_value=_make_config()),
    ),
    move_mg=patch("subscription_vending.workflow.move_subscription_to_management_group", AsyncMock()),
    initiative=patch(
        "subscription_vending.workflow.attach_foundation_initiative", AsyncMock(return_value="")
    ),
    rbac=patch("subscription_vending.workflow.create_initial_rbac", AsyncMock(return_value=[])),
    policy=patch("subscription_vending.workflow.assign_default_policies", AsyncMock()),
    cred=patch(
        "subscription_vending.azure.management_groups._get_credential", return_value=MagicMock()
    ),
)


# ---------------------------------------------------------------------------
# SubscriptionConfig — snow_ticket field
# ---------------------------------------------------------------------------

def test_subscription_config_snow_ticket_defaults_empty():
    cfg = SubscriptionConfig()
    assert cfg.snow_ticket == ""


def test_subscription_config_snow_ticket_set():
    cfg = SubscriptionConfig(snow_ticket="RITM0001234")
    assert cfg.snow_ticket == "RITM0001234"


# ---------------------------------------------------------------------------
# register_gate — registration
# ---------------------------------------------------------------------------

def test_register_gate_adds_to_gate_steps_list():
    initial_count = len(_GATE_STEPS)

    @register_gate
    async def _dummy_gate(ctx: StepContext) -> None:
        pass

    assert len(_GATE_STEPS) == initial_count + 1
    # Clean up
    _GATE_STEPS.pop()


def test_register_gate_stop_on_error_defaults_true():
    @register_gate
    async def _dummy_gate2(ctx: StepContext) -> None:
        pass

    entry = _GATE_STEPS[-1]
    assert entry.stop_on_error is True
    _GATE_STEPS.pop()


def test_register_gate_stop_on_error_can_be_false():
    @register_gate(stop_on_error=False)
    async def _dummy_gate3(ctx: StepContext) -> None:
        pass

    entry = _GATE_STEPS[-1]
    assert entry.stop_on_error is False
    _GATE_STEPS.pop()


# ---------------------------------------------------------------------------
# Gate execution in run_provisioning_workflow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gate_runs_before_workflow_steps():
    """A registered gate is called before any provisioning step."""
    call_order: list[str] = []

    @register_gate
    async def _order_gate(ctx: StepContext) -> None:
        call_order.append("gate")

    with (
        patch("subscription_vending.workflow.read_subscription_config", AsyncMock(return_value=_make_config())),
        patch(
            "subscription_vending.workflow.move_subscription_to_management_group",
            AsyncMock(side_effect=lambda **kw: call_order.append("step")),
        ),
        patch("subscription_vending.workflow.attach_foundation_initiative", AsyncMock(return_value="")),
        patch("subscription_vending.workflow.create_initial_rbac", AsyncMock(return_value=[])),
        patch("subscription_vending.workflow.assign_default_policies", AsyncMock()),
        patch("subscription_vending.azure.management_groups._get_credential", return_value=MagicMock()),
    ):
        await run_provisioning_workflow(
            subscription_id="sub-1",
            subscription_name="Test",
            management_group_id="ITL",
            settings=_make_settings(),
        )

    assert call_order[0] == "gate"
    _GATE_STEPS.pop()


@pytest.mark.asyncio
async def test_gate_failure_with_stop_on_error_skips_all_steps():
    """A failing gate with stop_on_error=True prevents any step from running."""
    step_called = False

    @register_gate(stop_on_error=True)
    async def _blocking_gate(ctx: StepContext) -> None:
        ctx.result.errors.append("No valid ticket")

    async def _should_not_run(**kw):
        nonlocal step_called
        step_called = True

    with (
        patch("subscription_vending.workflow.read_subscription_config", AsyncMock(return_value=_make_config())),
        patch("subscription_vending.workflow.move_subscription_to_management_group", AsyncMock(side_effect=_should_not_run)),
        patch("subscription_vending.workflow.attach_foundation_initiative", AsyncMock(return_value="")),
        patch("subscription_vending.workflow.create_initial_rbac", AsyncMock(return_value=[])),
        patch("subscription_vending.workflow.assign_default_policies", AsyncMock()),
        patch("subscription_vending.azure.management_groups._get_credential", return_value=MagicMock()),
    ):
        result = await run_provisioning_workflow(
            subscription_id="sub-1",
            subscription_name="Test",
            management_group_id="ITL",
            settings=_make_settings(),
        )

    assert result.success is False
    assert any("No valid ticket" in e for e in result.errors)
    assert step_called is False
    _GATE_STEPS.pop()


@pytest.mark.asyncio
async def test_gate_failure_without_stop_on_error_continues_steps():
    """A failing gate with stop_on_error=False still runs workflow steps."""
    @register_gate(stop_on_error=False)
    async def _soft_gate(ctx: StepContext) -> None:
        ctx.result.errors.append("Soft gate warning")

    with (
        patch("subscription_vending.workflow.read_subscription_config", AsyncMock(return_value=_make_config())),
        patch("subscription_vending.workflow.move_subscription_to_management_group", AsyncMock()),
        patch("subscription_vending.workflow.attach_foundation_initiative", AsyncMock(return_value="init-1")),
        patch("subscription_vending.workflow.create_initial_rbac", AsyncMock(return_value=["r1"])),
        patch("subscription_vending.workflow.assign_default_policies", AsyncMock()),
        patch("subscription_vending.azure.management_groups._get_credential", return_value=MagicMock()),
    ):
        result = await run_provisioning_workflow(
            subscription_id="sub-1",
            subscription_name="Test",
            management_group_id="ITL",
            settings=_make_settings(),
        )

    assert any("Soft gate warning" in e for e in result.errors)
    # Workflow steps still ran
    assert result.initiative_id == "init-1"
    assert result.rbac_roles == ["r1"]
    _GATE_STEPS.pop()


# ---------------------------------------------------------------------------
# ServiceNowCheckGate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_snow_gate_skips_when_no_instance():
    """When instance is empty, gate is a no-op (integration not configured)."""
    from subscription_vending.extensions._servicenow_check import ServiceNowCheckGate  # noqa: PLC0415

    gate = ServiceNowCheckGate(instance="", user="u", password="p")
    ctx = _make_ctx(snow_ticket="RITM0001234")
    await gate(ctx)

    assert ctx.result.errors == []


@pytest.mark.asyncio
async def test_snow_gate_fails_when_no_ticket_on_subscription():
    """When SNOW is configured but no ticket tag on subscription, gate fails."""
    from subscription_vending.extensions._servicenow_check import ServiceNowCheckGate  # noqa: PLC0415

    gate = ServiceNowCheckGate(instance="myco.service-now.com", user="u", password="p")
    ctx = _make_ctx(snow_ticket="")
    await gate(ctx)

    assert len(ctx.result.errors) == 1
    assert "itl-snow-ticket" in ctx.result.errors[0]


@pytest.mark.asyncio
async def test_snow_gate_dry_run_still_validates_ticket():
    """In dry_run mode the gate still calls ServiceNow (read-only check).

    The gate is a validation step, not a mutation — it should always run so
    that preflight dry-runs give accurate feedback about whether the ticket
    is present and approved.
    """
    from subscription_vending.extensions._servicenow_check import ServiceNowCheckGate  # noqa: PLC0415

    gate = ServiceNowCheckGate(instance="myco.service-now.com", user="u", password="p")
    ctx = _make_ctx(snow_ticket="RITM0001234", dry_run=True)

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "result": [{"number": "RITM0001234", "approval": "approved", "short_description": "Phoenix prod"}]
    }
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        await gate(ctx)

    # HTTP call was made even in dry_run
    mock_client.get.assert_awaited_once()
    # No errors — ticket was approved
    assert ctx.result.errors == []
    # Plan entry written
    assert any("RITM0001234" in p for p in ctx.result.plan)


@pytest.mark.asyncio
async def test_snow_gate_passes_when_ticket_approved():
    """Gate passes when ServiceNow returns an approved ticket."""
    import httpx  # noqa: PLC0415
    from subscription_vending.extensions._servicenow_check import ServiceNowCheckGate  # noqa: PLC0415

    gate = ServiceNowCheckGate(instance="myco.service-now.com", user="u", password="p")
    ctx = _make_ctx(snow_ticket="RITM0001234")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "result": [{"number": "RITM0001234", "approval": "approved", "state": "1"}]
    }
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        await gate(ctx)

    assert ctx.result.errors == []


@pytest.mark.asyncio
async def test_snow_gate_fails_when_ticket_not_found():
    """Gate fails when ServiceNow returns an empty result set."""
    from subscription_vending.extensions._servicenow_check import ServiceNowCheckGate  # noqa: PLC0415

    gate = ServiceNowCheckGate(instance="myco.service-now.com", user="u", password="p")
    ctx = _make_ctx(snow_ticket="RITM9999999")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"result": []}
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        await gate(ctx)

    assert len(ctx.result.errors) == 1
    assert "not found" in ctx.result.errors[0]


@pytest.mark.asyncio
async def test_snow_gate_fails_when_ticket_not_approved():
    """Gate fails when ticket exists but is not in the required state."""
    from subscription_vending.extensions._servicenow_check import ServiceNowCheckGate  # noqa: PLC0415

    gate = ServiceNowCheckGate(
        instance="myco.service-now.com", user="u", password="p", require_state="approved"
    )
    ctx = _make_ctx(snow_ticket="RITM0001234")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "result": [{"number": "RITM0001234", "approval": "requested", "state": "1"}]
    }
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        await gate(ctx)

    assert len(ctx.result.errors) == 1
    assert "not in required state" in ctx.result.errors[0]
    assert "approved" in ctx.result.errors[0]


@pytest.mark.asyncio
async def test_snow_gate_skips_state_check_when_require_state_empty():
    """When require_state is empty, existence check only — state is not validated."""
    from subscription_vending.extensions._servicenow_check import ServiceNowCheckGate  # noqa: PLC0415

    gate = ServiceNowCheckGate(
        instance="myco.service-now.com", user="u", password="p", require_state=""
    )
    ctx = _make_ctx(snow_ticket="RITM0001234")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "result": [{"number": "RITM0001234", "approval": "requested", "state": "1"}]
    }
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        await gate(ctx)

    assert ctx.result.errors == []


@pytest.mark.asyncio
async def test_snow_gate_records_error_on_http_failure():
    """Network/HTTP errors are caught and recorded in result.errors."""
    import httpx  # noqa: PLC0415
    from subscription_vending.extensions._servicenow_check import ServiceNowCheckGate  # noqa: PLC0415

    gate = ServiceNowCheckGate(instance="myco.service-now.com", user="u", password="p")
    ctx = _make_ctx(snow_ticket="RITM0001234")

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

    with patch("httpx.AsyncClient", return_value=mock_client):
        await gate(ctx)

    assert len(ctx.result.errors) == 1
    assert "RITM0001234" in ctx.result.errors[0]
    assert "failed" in ctx.result.errors[0]


# ---------------------------------------------------------------------------
# ServiceNowFeedbackStep
# ---------------------------------------------------------------------------

def _make_feedback_client(sys_id: str = "abc123", patch_status: int = 200):
    """Return a mock httpx.AsyncClient that handles GET (sys_id lookup) + PATCH."""
    get_resp = MagicMock()
    get_resp.raise_for_status = MagicMock()
    get_resp.json.return_value = {"result": [{"sys_id": sys_id, "number": "RITM0001234"}]}

    patch_resp = MagicMock()
    patch_resp.raise_for_status = MagicMock()
    patch_resp.json.return_value = {"result": {}}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=get_resp)
    mock_client.patch = AsyncMock(return_value=patch_resp)
    return mock_client


@pytest.mark.asyncio
async def test_feedback_skips_when_no_instance():
    """When instance is empty the step is a no-op."""
    from subscription_vending.extensions._servicenow_feedback import ServiceNowFeedbackStep  # noqa: PLC0415

    step = ServiceNowFeedbackStep(instance="", user="u", password="p")
    ctx = _make_ctx(snow_ticket="RITM0001234")

    with patch("httpx.AsyncClient") as mock_client:
        await step(ctx)
        mock_client.assert_not_called()

    assert ctx.result.errors == []


@pytest.mark.asyncio
async def test_feedback_skips_when_no_ticket():
    """When subscription has no ticket tag the step logs and returns."""
    from subscription_vending.extensions._servicenow_feedback import ServiceNowFeedbackStep  # noqa: PLC0415

    step = ServiceNowFeedbackStep(instance="myco.service-now.com", user="u", password="p")
    ctx = _make_ctx(snow_ticket="")

    with patch("httpx.AsyncClient") as mock_client:
        await step(ctx)
        mock_client.assert_not_called()

    assert ctx.result.errors == []


@pytest.mark.asyncio
async def test_feedback_dry_run_skips_http():
    """In dry-run mode the step logs what it would do without making HTTP calls."""
    from subscription_vending.extensions._servicenow_feedback import ServiceNowFeedbackStep  # noqa: PLC0415

    step = ServiceNowFeedbackStep(instance="myco.service-now.com", user="u", password="p")
    ctx = _make_ctx(snow_ticket="RITM0001234", dry_run=True)

    with patch("httpx.AsyncClient") as mock_client:
        await step(ctx)
        mock_client.assert_not_called()

    assert ctx.result.errors == []


@pytest.mark.asyncio
async def test_feedback_patches_ticket_on_success():
    """On success the step PATCHes the ticket with work_notes."""
    from subscription_vending.extensions._servicenow_feedback import ServiceNowFeedbackStep  # noqa: PLC0415

    step = ServiceNowFeedbackStep(
        instance="myco.service-now.com", user="u", password="p", success_state="3"
    )
    ctx = _make_ctx(snow_ticket="RITM0001234")  # result.success == True (no errors)

    mock_client = _make_feedback_client(sys_id="abc123")
    with patch("httpx.AsyncClient", return_value=mock_client):
        await step(ctx)

    mock_client.patch.assert_awaited_once()
    _, patch_kwargs = mock_client.patch.call_args
    body = patch_kwargs.get("json", {})
    assert "work_notes" in body
    assert "successfully" in body["work_notes"].lower()
    assert body["state"] == "3"
    assert ctx.result.errors == []


@pytest.mark.asyncio
async def test_feedback_patches_ticket_on_failure():
    """On failure the step PATCHes with error summary in work_notes."""
    from subscription_vending.extensions._servicenow_feedback import ServiceNowFeedbackStep  # noqa: PLC0415

    step = ServiceNowFeedbackStep(
        instance="myco.service-now.com", user="u", password="p", failure_state="4"
    )
    ctx = _make_ctx(snow_ticket="RITM0001234")
    ctx.result.errors.append("MG assignment failed: timeout")

    mock_client = _make_feedback_client(sys_id="abc123")
    with patch("httpx.AsyncClient", return_value=mock_client):
        await step(ctx)

    mock_client.patch.assert_awaited_once()
    _, patch_kwargs = mock_client.patch.call_args
    body = patch_kwargs.get("json", {})
    assert "errors" in body["work_notes"].lower()
    assert "MG assignment failed" in body["work_notes"]
    assert body["state"] == "4"


@pytest.mark.asyncio
async def test_feedback_omits_state_when_not_configured():
    """When success_state is empty, the PATCH payload does not contain 'state'."""
    from subscription_vending.extensions._servicenow_feedback import ServiceNowFeedbackStep  # noqa: PLC0415

    step = ServiceNowFeedbackStep(
        instance="myco.service-now.com", user="u", password="p",
        success_state="",  # do not change state
    )
    ctx = _make_ctx(snow_ticket="RITM0001234")

    mock_client = _make_feedback_client()
    with patch("httpx.AsyncClient", return_value=mock_client):
        await step(ctx)

    _, patch_kwargs = mock_client.patch.call_args
    assert "state" not in patch_kwargs.get("json", {})


@pytest.mark.asyncio
async def test_feedback_skips_update_when_ticket_not_found():
    """When sys_id lookup returns empty, no PATCH is made."""
    from subscription_vending.extensions._servicenow_feedback import ServiceNowFeedbackStep  # noqa: PLC0415

    step = ServiceNowFeedbackStep(instance="myco.service-now.com", user="u", password="p")
    ctx = _make_ctx(snow_ticket="RITM9999999")

    get_resp = MagicMock()
    get_resp.raise_for_status = MagicMock()
    get_resp.json.return_value = {"result": []}  # not found

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=get_resp)
    mock_client.patch = AsyncMock()

    with patch("httpx.AsyncClient", return_value=mock_client):
        await step(ctx)

    mock_client.patch.assert_not_awaited()
    # Not finding the ticket is non-fatal — no error appended
    assert ctx.result.errors == []


@pytest.mark.asyncio
async def test_feedback_patch_failure_is_non_fatal():
    """HTTP error during PATCH is logged but does not append to result.errors."""
    import httpx  # noqa: PLC0415
    from subscription_vending.extensions._servicenow_feedback import ServiceNowFeedbackStep  # noqa: PLC0415

    step = ServiceNowFeedbackStep(instance="myco.service-now.com", user="u", password="p")
    ctx = _make_ctx(snow_ticket="RITM0001234")

    get_resp = MagicMock()
    get_resp.raise_for_status = MagicMock()
    get_resp.json.return_value = {"result": [{"sys_id": "abc123", "number": "RITM0001234"}]}

    patch_resp = MagicMock()
    patch_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500", request=MagicMock(), response=MagicMock()
    )

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=get_resp)
    mock_client.patch = AsyncMock(return_value=patch_resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        await step(ctx)

    # Failure is non-fatal — result.errors stays clean
    assert ctx.result.errors == []

