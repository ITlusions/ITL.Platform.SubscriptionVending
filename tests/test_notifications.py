"""Unit tests for the outbound Event Grid notification publisher."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("VENDING_AZURE_TENANT_ID", "test-tenant-id")

from subscription_vending.core.config import Settings  # noqa: E402
from subscription_vending.workflow import ProvisioningResult  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(**kwargs) -> Settings:
    defaults = {
        "azure_tenant_id": "test-tenant-id",
        "azure_client_id": "test-client-id",
        "azure_client_secret": "test-secret",
    }
    defaults.update(kwargs)
    return Settings.model_construct(**defaults)


def _make_result(**kwargs) -> ProvisioningResult:
    defaults = {
        "subscription_id": "sub-1",
        "management_group": "ITL-Development",
        "initiative_id": "init-abc",
        "rbac_roles": ["role-1"],
        "errors": [],
    }
    defaults.update(kwargs)
    return ProvisioningResult(**defaults)


# ---------------------------------------------------------------------------
# publish_provisioned_event — no-op when endpoint not configured
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_publish_skipped_when_endpoint_not_configured():
    """No SDK client is created when event_grid_topic_endpoint is empty."""
    from subscription_vending.infrastructure.azure.notifications import publish_provisioned_event  # noqa: PLC0415

    settings = _make_settings(event_grid_topic_endpoint="")
    result = _make_result()

    with patch("subscription_vending.infrastructure.azure.notifications._get_publisher_client") as mock_client_factory:
        await publish_provisioned_event(result=result, subscription_name="Test Sub", settings=settings)

    mock_client_factory.assert_not_called()


# ---------------------------------------------------------------------------
# publish_provisioned_event — publishes correct payload
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_publish_sends_event_with_correct_type_and_subject():
    from subscription_vending.infrastructure.azure.notifications import publish_provisioned_event, _EVENT_TYPE  # noqa: PLC0415

    settings = _make_settings(event_grid_topic_endpoint="https://topic.example.eventgrid.azure.net/api/events")
    result = _make_result()

    sent_events: list = []

    mock_client = MagicMock()
    mock_client.send = lambda events: sent_events.extend(events)

    with (
        patch("subscription_vending.infrastructure.azure.notifications._get_publisher_client", return_value=mock_client),
    ):
        await publish_provisioned_event(result=result, subscription_name="Test Sub", settings=settings)

    assert len(sent_events) == 1
    event = sent_events[0]
    assert event.event_type == _EVENT_TYPE
    assert event.subject == f"/subscriptions/{result.subscription_id}"
    assert event.data["subscription_id"] == result.subscription_id
    assert event.data["subscription_name"] == "Test Sub"
    assert event.data["management_group"] == result.management_group
    assert event.data["success"] is True


@pytest.mark.asyncio
async def test_publish_includes_errors_in_payload():
    from subscription_vending.infrastructure.azure.notifications import publish_provisioned_event  # noqa: PLC0415

    settings = _make_settings(event_grid_topic_endpoint="https://topic.example.eventgrid.azure.net/api/events")
    result = _make_result(errors=["MG assignment failed: boom"], rbac_roles=[])

    sent_events: list = []

    mock_client = MagicMock()
    mock_client.send = lambda events: sent_events.extend(events)

    with (
        patch("subscription_vending.infrastructure.azure.notifications._get_publisher_client", return_value=mock_client),
    ):
        await publish_provisioned_event(result=result, subscription_name="Test Sub", settings=settings)

    assert sent_events[0].data["success"] is False
    assert "MG assignment failed: boom" in sent_events[0].data["errors"]


# ---------------------------------------------------------------------------
# publish_provisioned_event — publishing errors are non-fatal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_publish_error_is_logged_not_raised(caplog):
    import logging  # noqa: PLC0415
    from subscription_vending.infrastructure.azure.notifications import publish_provisioned_event  # noqa: PLC0415

    settings = _make_settings(event_grid_topic_endpoint="https://topic.example.eventgrid.azure.net/api/events")
    result = _make_result()

    mock_client = MagicMock()
    mock_client.send.side_effect = RuntimeError("connection refused")

    with (
        patch("subscription_vending.infrastructure.azure.notifications._get_publisher_client", return_value=mock_client),
        caplog.at_level(logging.WARNING),
    ):
        # Must not raise
        await publish_provisioned_event(result=result, subscription_name="Test Sub", settings=settings)

    assert any("Failed to publish notification event" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# workflow integration — notification step is called
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_workflow_calls_publish_notification():
    """publish_provisioned_event is invoked as part of run_provisioning_workflow."""
    from subscription_vending.workflow import run_provisioning_workflow  # noqa: PLC0415

    settings = _make_settings(
        root_management_group="ITL",
        authorization_service_url="http://auth:8004",
        event_grid_topic_endpoint="https://topic.example.eventgrid.azure.net/api/events",
    )

    config = MagicMock()
    config.management_group_name = ""
    config.budget_eur = 0
    config.owner_email = ""
    config.environment = "development"
    config.aks_enabled = False

    notification_calls: list = []

    async def _fake_notify(result, subscription_name, settings):  # noqa: ARG001
        notification_calls.append((result.subscription_id, subscription_name))

    with (
        patch("subscription_vending.workflow.engine.read_subscription_config", AsyncMock(return_value=config)),
        patch("subscription_vending.workflow.steps.move_subscription_to_management_group", AsyncMock()),
        patch("subscription_vending.workflow.steps.attach_foundation_initiative", AsyncMock(return_value="")),
        patch("subscription_vending.workflow.steps.create_initial_rbac", AsyncMock(return_value=[])),
        patch("subscription_vending.workflow.steps.assign_default_policies", AsyncMock()),
        patch("subscription_vending.workflow.steps.publish_provisioned_event", _fake_notify),
        patch("subscription_vending.workflow.engine._get_credential", return_value=MagicMock()),
    ):
        await run_provisioning_workflow(
            subscription_id="sub-1",
            subscription_name="Test Sub",
            management_group_id="ITL",
            settings=settings,
        )

    assert notification_calls == [("sub-1", "Test Sub")]
