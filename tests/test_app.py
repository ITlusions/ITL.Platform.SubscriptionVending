"""Basic smoke tests for the FastAPI application."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    """Return a TestClient with VENDING_AZURE_TENANT_ID set so Settings loads."""
    monkeypatch.setenv("VENDING_AZURE_TENANT_ID", "test-tenant-id")
    # Import app after env vars are set
    from subscription_vending.main import app  # noqa: PLC0415
    return TestClient(app)


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_webhook_validation_handshake(client):
    """Event Grid sends a validationCode on first delivery; we echo it back."""
    payload = [
        {
            "id": "abc123",
            "subject": "/subscriptions/test",
            "eventType": "Microsoft.EventGrid.SubscriptionValidationEvent",
            "dataVersion": "1.0",
            "eventTime": "2024-01-01T00:00:00Z",
            "data": {"validationCode": "my-validation-code"},
        }
    ]
    response = client.post(
        "/webhook/",
        headers={"aeg-event-type": "SubscriptionValidation"},
        json=payload,
    )
    assert response.status_code == 200
    assert response.json() == {"validationResponse": "my-validation-code"}


def test_webhook_empty_payload(client):
    response = client.post("/webhook/", json=[])
    assert response.status_code == 400


def test_mock_router_not_loaded_by_default(client):
    """POST /webhook/test must not exist when mock_mode is false."""
    response = client.post("/webhook/test", json={"subscription_id": "x"})
    assert response.status_code == 404


def test_mock_router_loaded_in_mock_mode(monkeypatch):
    """POST /webhook/test must be available when VENDING_MOCK_MODE=true."""
    monkeypatch.setenv("VENDING_AZURE_TENANT_ID", "test-tenant-id")
    monkeypatch.setenv("VENDING_MOCK_MODE", "true")

    # Re-import so settings are re-evaluated
    import importlib
    import subscription_vending.core.config as core_cfg_mod
    import subscription_vending.main as main_mod

    importlib.reload(core_cfg_mod)
    core_cfg_mod.get_settings.cache_clear()
    importlib.reload(main_mod)

    from fastapi.testclient import TestClient
    test_client = TestClient(main_mod.app)

    # The route exists; it will call the workflow which will fail because there
    # are no real Azure credentials — that's fine for a smoke test.
    routes = [route.path for route in main_mod.app.routes]
    assert "/webhook/test" in routes
