"""Unit tests for create_initial_rbac and helpers in azure/rbac.py."""

from __future__ import annotations

import os
import types
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("VENDING_AZURE_TENANT_ID", "test-tenant-id")

from subscription_vending.infrastructure.azure.rbac import (  # noqa: E402
    ROLE_DEFINITIONS,
    RoleAssignmentSpec,
    _get_default_role_assignments,
    create_initial_rbac,
)
from subscription_vending.core.config import Settings  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(**kwargs) -> Settings:
    """Return a Settings instance with test defaults, overridden by kwargs."""
    defaults = {
        "azure_tenant_id": "test-tenant-id",
        "azure_client_id": "test-client-id",
        "azure_client_secret": "test-secret",
        "platform_spn_object_id": "",
        "ops_group_object_id": "",
        "security_group_object_id": "",
        "finops_group_object_id": "",
    }
    defaults.update(kwargs)
    return Settings.model_construct(**defaults)


def _fake_assignment(assignment_id: str):
    obj = MagicMock()
    obj.id = assignment_id
    return obj


# ---------------------------------------------------------------------------
# ROLE_DEFINITIONS
# ---------------------------------------------------------------------------

def test_role_definition_ids_match_azure_builtin_roles():
    assert ROLE_DEFINITIONS["Owner"] == "8e3af657-a8ff-443c-a75c-2fe8c4bcb635"
    assert ROLE_DEFINITIONS["Contributor"] == "b24988ac-6180-42a0-ab88-20f7382dd24c"
    assert ROLE_DEFINITIONS["SecurityReader"] == "39bc4728-0917-49c7-9d2c-d95423bc2eb4"
    assert ROLE_DEFINITIONS["CostManagementReader"] == "72fafb9e-0641-4937-9268-a91bfd8191a3"


# ---------------------------------------------------------------------------
# _get_default_role_assignments
# ---------------------------------------------------------------------------

def test_no_assignments_when_all_object_ids_empty():
    settings = _make_settings()
    assert _get_default_role_assignments(settings) == []


def test_only_configured_principals_are_returned():
    settings = _make_settings(
        platform_spn_object_id="spn-oid",
        ops_group_object_id="ops-oid",
    )
    specs = _get_default_role_assignments(settings)
    assert len(specs) == 2
    assert specs[0] == RoleAssignmentSpec("spn-oid", "Owner", "ITL Platform Service Principal")
    assert specs[1] == RoleAssignmentSpec("ops-oid", "Contributor", "ITL Operations group")


def test_all_four_principals_returned_when_fully_configured():
    settings = _make_settings(
        platform_spn_object_id="spn-oid",
        ops_group_object_id="ops-oid",
        security_group_object_id="sec-oid",
        finops_group_object_id="finops-oid",
    )
    specs = _get_default_role_assignments(settings)
    assert len(specs) == 4
    role_names = [s.role_definition_name for s in specs]
    assert role_names == ["Owner", "Contributor", "SecurityReader", "CostManagementReader"]


# ---------------------------------------------------------------------------
# create_initial_rbac
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_initial_rbac_returns_empty_when_no_object_ids():
    settings = _make_settings()
    with patch("subscription_vending.infrastructure.azure.rbac._get_credential"):
        with patch("subscription_vending.infrastructure.azure.rbac.AuthorizationManagementClient"):
            result = await create_initial_rbac(
                subscription_id="sub-123",
                settings=settings,
            )
    assert result == []


@pytest.mark.asyncio
async def test_create_initial_rbac_calls_sdk_for_each_principal():
    settings = _make_settings(
        platform_spn_object_id="spn-oid",
        ops_group_object_id="ops-oid",
        security_group_object_id="sec-oid",
        finops_group_object_id="finops-oid",
    )

    mock_client = MagicMock()
    mock_client.role_assignments.create.side_effect = [
        _fake_assignment("/assignments/1"),
        _fake_assignment("/assignments/2"),
        _fake_assignment("/assignments/3"),
        _fake_assignment("/assignments/4"),
    ]

    with patch("subscription_vending.infrastructure.azure.rbac._get_credential"):
        with patch(
            "subscription_vending.infrastructure.azure.rbac.AuthorizationManagementClient",
            return_value=mock_client,
        ):
            result = await create_initial_rbac(
                subscription_id="sub-123",
                settings=settings,
            )

    assert mock_client.role_assignments.create.call_count == 4
    assert result == [
        "/assignments/1",
        "/assignments/2",
        "/assignments/3",
        "/assignments/4",
    ]


@pytest.mark.asyncio
async def test_create_initial_rbac_uses_correct_role_definition_ids():
    settings = _make_settings(
        platform_spn_object_id="spn-oid",
        security_group_object_id="sec-oid",
    )

    mock_client = MagicMock()
    mock_client.role_assignments.create.side_effect = [
        _fake_assignment("/assignments/owner"),
        _fake_assignment("/assignments/secreader"),
    ]

    captured_params = []

    def _capture_create(scope, name, params):
        captured_params.append(params)
        return mock_client.role_assignments.create.side_effect.pop(0)  # type: ignore[attr-defined]

    mock_client.role_assignments.create.side_effect = None
    mock_client.role_assignments.create.side_effect = [
        _fake_assignment("/assignments/owner"),
        _fake_assignment("/assignments/secreader"),
    ]

    with patch("subscription_vending.infrastructure.azure.rbac._get_credential"):
        with patch(
            "subscription_vending.infrastructure.azure.rbac.AuthorizationManagementClient",
            return_value=mock_client,
        ):
            await create_initial_rbac(subscription_id="sub-123", settings=settings)

    calls = mock_client.role_assignments.create.call_args_list
    # First call — Owner
    owner_params = calls[0].args[2]
    assert ROLE_DEFINITIONS["Owner"] in owner_params.role_definition_id
    assert owner_params.principal_id == "spn-oid"

    # Second call — SecurityReader
    sec_params = calls[1].args[2]
    assert ROLE_DEFINITIONS["SecurityReader"] in sec_params.role_definition_id
    assert sec_params.principal_id == "sec-oid"


@pytest.mark.asyncio
async def test_create_initial_rbac_logs_warning_on_error_and_continues(caplog):
    """An SDK error for one principal must not stop processing of remaining ones."""
    settings = _make_settings(
        platform_spn_object_id="spn-oid",
        ops_group_object_id="ops-oid",
    )

    mock_client = MagicMock()
    # First call raises, second succeeds
    mock_client.role_assignments.create.side_effect = [
        RuntimeError("Azure error"),
        _fake_assignment("/assignments/ops"),
    ]

    import logging

    with patch("subscription_vending.infrastructure.azure.rbac._get_credential"):
        with patch(
            "subscription_vending.infrastructure.azure.rbac.AuthorizationManagementClient",
            return_value=mock_client,
        ):
            with caplog.at_level(logging.WARNING, logger="subscription_vending.infrastructure.azure.rbac"):
                result = await create_initial_rbac(
                    subscription_id="sub-123",
                    settings=settings,
                )

    # Second assignment succeeded despite first failing
    assert result == ["/assignments/ops"]
    assert mock_client.role_assignments.create.call_count == 2
    assert "Could not create role assignment" in caplog.text


@pytest.mark.asyncio
async def test_create_initial_rbac_returns_only_successful_ids():
    settings = _make_settings(
        platform_spn_object_id="spn-oid",
        ops_group_object_id="ops-oid",
        security_group_object_id="sec-oid",
    )

    mock_client = MagicMock()
    mock_client.role_assignments.create.side_effect = [
        _fake_assignment("/assignments/spn"),
        RuntimeError("transient error"),
        _fake_assignment("/assignments/sec"),
    ]

    with patch("subscription_vending.infrastructure.azure.rbac._get_credential"):
        with patch(
            "subscription_vending.infrastructure.azure.rbac.AuthorizationManagementClient",
            return_value=mock_client,
        ):
            result = await create_initial_rbac(
                subscription_id="sub-123",
                settings=settings,
            )

    assert result == ["/assignments/spn", "/assignments/sec"]
