"""Unit tests for WorkflowEngine and ProvisioningResult."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("VENDING_AZURE_TENANT_ID", "test-tenant-id")

from subscription_vending.workflow import ProvisioningResult, WorkflowEngine  # noqa: E402
from subscription_vending.core.config import Settings  # noqa: E402


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


def _make_subscription_config(
    management_group_name: str = "",
    budget_eur: int = 0,
    owner_email: str = "",
):
    cfg = MagicMock()
    cfg.management_group_name = management_group_name
    cfg.budget_eur = budget_eur
    cfg.owner_email = owner_email
    cfg.environment = "development"
    cfg.aks_enabled = False
    return cfg


# ---------------------------------------------------------------------------
# ProvisioningResult
# ---------------------------------------------------------------------------

def test_provisioning_result_success_true_when_no_errors():
    result = ProvisioningResult(subscription_id="sub-1")
    assert result.success is True


def test_provisioning_result_success_false_when_errors_present():
    result = ProvisioningResult(subscription_id="sub-1", errors=["MG assignment failed: boom"])
    assert result.success is False


def test_provisioning_result_defaults():
    result = ProvisioningResult(subscription_id="sub-1")
    assert result.management_group == ""
    assert result.initiative_id == ""
    assert result.rbac_roles == []
    assert result.errors == []


# ---------------------------------------------------------------------------
# attach_foundation_initiative (via httpx mock)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_attach_foundation_initiative_returns_initiative_id():
    from subscription_vending.infrastructure.azure.policy import attach_foundation_initiative  # noqa: PLC0415

    mock_response = MagicMock()
    mock_response.json.return_value = {"initiative_id": "init-abc"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("subscription_vending.infrastructure.azure.policy.httpx.AsyncClient", return_value=mock_client):
        result = await attach_foundation_initiative(
            authorization_url="http://auth-service:8004",
            subscription_id="sub-1",
        )

    assert result == "init-abc"
    mock_client.post.assert_awaited_once_with(
        "http://auth-service:8004/sync/foundation",
        params={"subscription_id": "sub-1"},
    )


@pytest.mark.asyncio
async def test_attach_foundation_initiative_returns_empty_when_no_initiative_id():
    from subscription_vending.infrastructure.azure.policy import attach_foundation_initiative  # noqa: PLC0415

    mock_response = MagicMock()
    mock_response.json.return_value = {}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("subscription_vending.infrastructure.azure.policy.httpx.AsyncClient", return_value=mock_client):
        result = await attach_foundation_initiative(
            authorization_url="http://auth-service:8004",
            subscription_id="sub-1",
        )

    assert result == ""


@pytest.mark.asyncio
async def test_attach_foundation_initiative_raises_on_http_error():
    import httpx  # noqa: PLC0415
    from subscription_vending.infrastructure.azure.policy import attach_foundation_initiative  # noqa: PLC0415

    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500 Internal Server Error",
        request=MagicMock(),
        response=MagicMock(),
    )

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("subscription_vending.infrastructure.azure.policy.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(httpx.HTTPStatusError):
            await attach_foundation_initiative(
                authorization_url="http://auth-service:8004",
                subscription_id="sub-1",
            )


# ---------------------------------------------------------------------------
# WorkflowEngine
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_workflow_returns_provisioning_result():
    settings = _make_settings()
    config = _make_subscription_config()

    with (
        patch("subscription_vending.workflow.engine.read_subscription_config", AsyncMock(return_value=config)),
        patch("subscription_vending.workflow.steps.move_subscription_to_management_group", AsyncMock()),
        patch("subscription_vending.workflow.steps.attach_foundation_initiative", AsyncMock(return_value="init-xyz")),
        patch("subscription_vending.workflow.steps.create_initial_rbac", AsyncMock(return_value=["role-1"])),
        patch("subscription_vending.workflow.steps.assign_default_policies", AsyncMock()),
        patch("subscription_vending.workflow.engine._get_credential", return_value=MagicMock()),
    ):
        result = await WorkflowEngine(settings).run(
            subscription_id="sub-1",
            subscription_name="Test Sub",
            management_group_id="ITL",
        )

    assert isinstance(result, ProvisioningResult)
    assert result.subscription_id == "sub-1"
    assert result.initiative_id == "init-xyz"
    assert result.rbac_roles == ["role-1"]
    assert result.success is True
    assert result.errors == []


@pytest.mark.asyncio
async def test_workflow_mg_step_error_collected_without_stopping():
    settings = _make_settings()
    config = _make_subscription_config()

    with (
        patch("subscription_vending.workflow.engine.read_subscription_config", AsyncMock(return_value=config)),
        patch(
            "subscription_vending.workflow.steps.move_subscription_to_management_group",
            AsyncMock(side_effect=RuntimeError("mg boom")),
        ),
        patch("subscription_vending.workflow.steps.attach_foundation_initiative", AsyncMock(return_value="init-xyz")),
        patch("subscription_vending.workflow.steps.create_initial_rbac", AsyncMock(return_value=[])),
        patch("subscription_vending.workflow.steps.assign_default_policies", AsyncMock()),
        patch("subscription_vending.workflow.engine._get_credential", return_value=MagicMock()),
    ):
        result = await WorkflowEngine(settings).run(
            subscription_id="sub-1",
            subscription_name="Test Sub",
            management_group_id="ITL",
        )

    assert result.success is False
    assert any("MG assignment failed" in e for e in result.errors)
    # Foundation initiative and RBAC should still have run
    assert result.initiative_id == "init-xyz"


@pytest.mark.asyncio
async def test_workflow_foundation_initiative_error_collected_without_stopping():
    settings = _make_settings()
    config = _make_subscription_config()

    with (
        patch("subscription_vending.workflow.engine.read_subscription_config", AsyncMock(return_value=config)),
        patch("subscription_vending.workflow.steps.move_subscription_to_management_group", AsyncMock()),
        patch(
            "subscription_vending.workflow.steps.attach_foundation_initiative",
            AsyncMock(side_effect=RuntimeError("initiative boom")),
        ),
        patch("subscription_vending.workflow.steps.create_initial_rbac", AsyncMock(return_value=["role-1"])),
        patch("subscription_vending.workflow.steps.assign_default_policies", AsyncMock()),
        patch("subscription_vending.workflow.engine._get_credential", return_value=MagicMock()),
    ):
        result = await WorkflowEngine(settings).run(
            subscription_id="sub-1",
            subscription_name="Test Sub",
            management_group_id="ITL",
        )

    assert result.success is False
    assert any("Foundation initiative failed" in e for e in result.errors)
    # RBAC should still have run
    assert result.rbac_roles == ["role-1"]


@pytest.mark.asyncio
async def test_workflow_rbac_error_collected_without_stopping():
    settings = _make_settings()
    config = _make_subscription_config()

    with (
        patch("subscription_vending.workflow.engine.read_subscription_config", AsyncMock(return_value=config)),
        patch("subscription_vending.workflow.steps.move_subscription_to_management_group", AsyncMock()),
        patch("subscription_vending.workflow.steps.attach_foundation_initiative", AsyncMock(return_value="")),
        patch(
            "subscription_vending.workflow.steps.create_initial_rbac",
            AsyncMock(side_effect=RuntimeError("rbac boom")),
        ),
        patch("subscription_vending.workflow.steps.assign_default_policies", AsyncMock()),
        patch("subscription_vending.workflow.engine._get_credential", return_value=MagicMock()),
    ):
        result = await WorkflowEngine(settings).run(
            subscription_id="sub-1",
            subscription_name="Test Sub",
            management_group_id="ITL",
        )

    assert result.success is False
    assert any("RBAC creation failed" in e for e in result.errors)


@pytest.mark.asyncio
async def test_workflow_management_group_set_from_settings_root():
    settings = _make_settings(root_management_group="ITL-Root")
    config = _make_subscription_config(management_group_name="")

    captured_mg: list[str] = []

    async def _capture_mg(**kwargs):
        captured_mg.append(kwargs["management_group_id"])

    with (
        patch("subscription_vending.workflow.engine.read_subscription_config", AsyncMock(return_value=config)),
        patch("subscription_vending.workflow.steps.move_subscription_to_management_group", _capture_mg),
        patch("subscription_vending.workflow.steps.attach_foundation_initiative", AsyncMock(return_value="")),
        patch("subscription_vending.workflow.steps.create_initial_rbac", AsyncMock(return_value=[])),
        patch("subscription_vending.workflow.steps.assign_default_policies", AsyncMock()),
        patch("subscription_vending.workflow.engine._get_credential", return_value=MagicMock()),
    ):
        result = await WorkflowEngine(settings).run(
            subscription_id="sub-1",
            subscription_name="Test Sub",
            management_group_id="",
        )

    assert result.management_group == "ITL-Root"
    assert captured_mg == ["ITL-Root"]
