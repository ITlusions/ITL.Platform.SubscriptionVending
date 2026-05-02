"""Unit tests for tag-based provisioning configuration (azure/tags.py)."""

from __future__ import annotations

import logging
import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("VENDING_AZURE_TENANT_ID", "test-tenant-id")

from subscription_vending.azure.tags import (  # noqa: E402
    SubscriptionConfig,
    _resolve_management_group,
    read_subscription_config,
)
from subscription_vending.config import Settings  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(**kwargs) -> Settings:
    """Return a Settings instance with test defaults, overridden by kwargs."""
    defaults = {
        "azure_tenant_id": "test-tenant-id",
        "mg_production": "ITL-Production",
        "mg_staging": "ITL-Staging",
        "mg_development": "ITL-Development",
        "mg_sandbox": "ITL-Sandbox",
        "default_alert_email": "",
    }
    defaults.update(kwargs)
    return Settings.model_construct(**defaults)


def _fake_subscription(tags: dict[str, str] | None) -> MagicMock:
    """Return a mock subscription object with the given tags."""
    sub = MagicMock()
    sub.tags = tags
    return sub


# ---------------------------------------------------------------------------
# SubscriptionConfig defaults
# ---------------------------------------------------------------------------

def test_default_config_values():
    config = SubscriptionConfig()
    assert config.environment == "sandbox"
    assert config.aks_enabled is False
    assert config.budget_eur == 0
    assert config.owner_email == ""
    assert config.management_group_name == "ITL-Sandbox"


# ---------------------------------------------------------------------------
# enforcement_mode property
# ---------------------------------------------------------------------------

def test_enforcement_mode_production():
    config = SubscriptionConfig(environment="production")
    assert config.enforcement_mode == "Default"


@pytest.mark.parametrize("env", ["staging", "development", "sandbox"])
def test_enforcement_mode_non_production(env):
    config = SubscriptionConfig(environment=env)
    assert config.enforcement_mode == "DoNotEnforce"


# ---------------------------------------------------------------------------
# _resolve_management_group
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("env,expected_attr", [
    ("production",  "mg_production"),
    ("staging",     "mg_staging"),
    ("development", "mg_development"),
    ("sandbox",     "mg_sandbox"),
])
def test_resolve_management_group_known_environments(env, expected_attr):
    settings = _make_settings()
    result = _resolve_management_group(env, settings)
    assert result == getattr(settings, expected_attr)


def test_resolve_management_group_unknown_falls_back_to_sandbox():
    settings = _make_settings()
    assert _resolve_management_group("unknown-env", settings) == settings.mg_sandbox


def test_resolve_management_group_uses_custom_settings():
    settings = _make_settings(mg_production="CustomProdMG", mg_sandbox="CustomSandboxMG")
    assert _resolve_management_group("production", settings) == "CustomProdMG"
    assert _resolve_management_group("unknown", settings) == "CustomSandboxMG"


# ---------------------------------------------------------------------------
# read_subscription_config — tag parsing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_config_all_defaults_when_no_tags():
    settings = _make_settings()
    sub = _fake_subscription(tags=None)
    with patch("subscription_vending.azure.tags.SubscriptionClient") as MockClient:
        MockClient.return_value.subscriptions.get.return_value = sub
        config = await read_subscription_config(MagicMock(), "sub-000", settings)

    assert config.environment == "sandbox"
    assert config.management_group_name == "ITL-Sandbox"
    assert config.aks_enabled is False
    assert config.budget_eur == 0
    assert config.owner_email == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("env_tag,expected_env,expected_mg", [
    ("production",  "production",  "ITL-Production"),
    ("staging",     "staging",     "ITL-Staging"),
    ("development", "development", "ITL-Development"),
    ("sandbox",     "sandbox",     "ITL-Sandbox"),
    ("PRODUCTION",  "production",  "ITL-Production"),  # case-insensitive
])
async def test_read_config_itl_environment_tag(env_tag, expected_env, expected_mg):
    settings = _make_settings()
    sub = _fake_subscription(tags={"itl-environment": env_tag})
    with patch("subscription_vending.azure.tags.SubscriptionClient") as MockClient:
        MockClient.return_value.subscriptions.get.return_value = sub
        config = await read_subscription_config(MagicMock(), "sub-001", settings)

    assert config.environment == expected_env
    assert config.management_group_name == expected_mg


@pytest.mark.asyncio
async def test_read_config_invalid_environment_falls_back_to_sandbox():
    settings = _make_settings()
    sub = _fake_subscription(tags={"itl-environment": "not-a-real-env"})
    with patch("subscription_vending.azure.tags.SubscriptionClient") as MockClient:
        MockClient.return_value.subscriptions.get.return_value = sub
        config = await read_subscription_config(MagicMock(), "sub-002", settings)

    assert config.environment == "sandbox"
    assert config.management_group_name == "ITL-Sandbox"


@pytest.mark.asyncio
@pytest.mark.parametrize("tag_value,expected", [
    ("true",  True),
    ("True",  True),
    ("TRUE",  True),
    ("false", False),
    ("False", False),
])
async def test_read_config_itl_aks_tag(tag_value, expected):
    settings = _make_settings()
    sub = _fake_subscription(tags={"itl-aks": tag_value})
    with patch("subscription_vending.azure.tags.SubscriptionClient") as MockClient:
        MockClient.return_value.subscriptions.get.return_value = sub
        config = await read_subscription_config(MagicMock(), "sub-003", settings)

    assert config.aks_enabled is expected


@pytest.mark.asyncio
async def test_read_config_itl_budget_tag_valid():
    settings = _make_settings()
    sub = _fake_subscription(tags={"itl-budget": "500"})
    with patch("subscription_vending.azure.tags.SubscriptionClient") as MockClient:
        MockClient.return_value.subscriptions.get.return_value = sub
        config = await read_subscription_config(MagicMock(), "sub-004", settings)

    assert config.budget_eur == 500


@pytest.mark.asyncio
async def test_read_config_itl_budget_tag_invalid_logs_warning(caplog):
    settings = _make_settings()
    sub = _fake_subscription(tags={"itl-budget": "not-a-number"})
    with patch("subscription_vending.azure.tags.SubscriptionClient") as MockClient:
        MockClient.return_value.subscriptions.get.return_value = sub
        with caplog.at_level(logging.WARNING, logger="subscription_vending.azure.tags"):
            config = await read_subscription_config(MagicMock(), "sub-005", settings)

    assert config.budget_eur == 0
    assert "itl-budget" in caplog.text


@pytest.mark.asyncio
async def test_read_config_itl_owner_tag():
    settings = _make_settings()
    sub = _fake_subscription(tags={"itl-owner": "owner@example.com"})
    with patch("subscription_vending.azure.tags.SubscriptionClient") as MockClient:
        MockClient.return_value.subscriptions.get.return_value = sub
        config = await read_subscription_config(MagicMock(), "sub-006", settings)

    assert config.owner_email == "owner@example.com"


@pytest.mark.asyncio
async def test_read_config_all_tags_combined():
    settings = _make_settings()
    sub = _fake_subscription(tags={
        "itl-environment": "production",
        "itl-aks": "true",
        "itl-budget": "1000",
        "itl-owner": "team@itlusions.com",
    })
    with patch("subscription_vending.azure.tags.SubscriptionClient") as MockClient:
        MockClient.return_value.subscriptions.get.return_value = sub
        config = await read_subscription_config(MagicMock(), "sub-007", settings)

    assert config.environment == "production"
    assert config.management_group_name == "ITL-Production"
    assert config.aks_enabled is True
    assert config.budget_eur == 1000
    assert config.owner_email == "team@itlusions.com"
    assert config.enforcement_mode == "Default"


@pytest.mark.asyncio
async def test_read_config_tags_retrieval_failure_returns_defaults(caplog):
    """SDK error must not crash — defaults are returned instead."""
    settings = _make_settings()
    with patch("subscription_vending.azure.tags.SubscriptionClient") as MockClient:
        MockClient.return_value.subscriptions.get.side_effect = RuntimeError("Azure unavailable")
        with caplog.at_level(logging.WARNING, logger="subscription_vending.azure.tags"):
            config = await read_subscription_config(MagicMock(), "sub-008", settings)

    assert config.environment == "sandbox"
    assert config.management_group_name == "ITL-Sandbox"
    assert config.aks_enabled is False
    assert config.budget_eur == 0
    assert "Could not retrieve subscription tags" in caplog.text


@pytest.mark.asyncio
async def test_read_config_custom_mg_names_from_settings():
    """MG names are driven by Settings, not hardcoded."""
    settings = _make_settings(
        mg_production="MyOrg-Prod",
        mg_sandbox="MyOrg-Sandbox",
    )
    sub = _fake_subscription(tags={"itl-environment": "production"})
    with patch("subscription_vending.azure.tags.SubscriptionClient") as MockClient:
        MockClient.return_value.subscriptions.get.return_value = sub
        config = await read_subscription_config(MagicMock(), "sub-009", settings)

    assert config.management_group_name == "MyOrg-Prod"


@pytest.mark.asyncio
async def test_read_config_empty_tags_dict():
    settings = _make_settings()
    sub = _fake_subscription(tags={})
    with patch("subscription_vending.azure.tags.SubscriptionClient") as MockClient:
        MockClient.return_value.subscriptions.get.return_value = sub
        config = await read_subscription_config(MagicMock(), "sub-010", settings)

    assert config == SubscriptionConfig(management_group_name="ITL-Sandbox")
