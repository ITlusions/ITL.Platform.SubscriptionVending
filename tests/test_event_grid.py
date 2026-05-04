import logging
import os

import pytest

os.environ.setdefault("VENDING_AZURE_TENANT_ID", "test-tenant-id")

from subscription_vending.handlers import event_grid
from subscription_vending.schemas.event_grid import EventGridEvent


@pytest.fixture()
def client():
    from subscription_vending.main import app  # noqa: PLC0415
    from fastapi.testclient import TestClient  # noqa: PLC0415

    return TestClient(app)


def _subscription_created_event(*, subscription_id: str = "sub-1") -> dict:
    return {
        "id": "evt-1",
        "eventType": "Microsoft.Resources.ResourceActionSuccess",
        "subject": f"/subscriptions/{subscription_id}/resourceGroups/rg",
        "dataVersion": "1.0",
        "data": {
            "operationName": "Microsoft.Subscription/aliases/write",
            "resourceUri": f"/subscriptions/{subscription_id}",
        },
    }


def test_webhook_requires_sas_key_when_configured(client, monkeypatch):
    monkeypatch.setattr(event_grid._settings, "event_grid_sas_key", "expected-sas")

    response = client.post("/webhook/", json=[_subscription_created_event()])

    assert response.status_code == 401


def test_is_subscription_created_filters_relevant_events():
    relevant = EventGridEvent.model_validate(_subscription_created_event())
    irrelevant = EventGridEvent.model_validate(
        {
            "id": "evt-2",
            "eventType": "Microsoft.Resources.ResourceActionSuccess",
            "subject": "/subscriptions/sub-2/resourceGroups/rg",
            "dataVersion": "1.0",
            "data": {"operationName": "Microsoft.Compute/virtualMachines/write"},
        }
    )

    assert event_grid._is_subscription_created(relevant) is True
    assert event_grid._is_subscription_created(irrelevant) is False


def test_extract_subscription_id_from_resource_uri_and_subject():
    from_resource_uri = EventGridEvent.model_validate(_subscription_created_event(subscription_id="from-uri"))
    from_subject = EventGridEvent.model_validate(
        {
            "id": "evt-3",
            "eventType": "Microsoft.Resources.ResourceActionSuccess",
            "subject": "/subscriptions/from-subject/resourceGroups/rg",
            "dataVersion": "1.0",
            "data": {"operationName": "Microsoft.Subscription/aliases/write"},
        }
    )

    assert event_grid._extract_subscription_id(from_resource_uri) == "from-uri"
    assert event_grid._extract_subscription_id(from_subject) == "from-subject"


def test_workflow_error_is_logged_and_not_reraised(client, monkeypatch, caplog):
    monkeypatch.setattr(event_grid._settings, "event_grid_sas_key", "")

    async def _failing_dispatch(**kwargs):  # noqa: ARG001
        raise RuntimeError("boom")

    monkeypatch.setattr(event_grid.controller, "dispatch", _failing_dispatch)

    with caplog.at_level(logging.ERROR):
        response = client.post("/webhook/", json=[_subscription_created_event()])

    assert response.status_code == 200
    assert "Error dispatching sub-1" in caplog.text


def test_batch_of_events_is_processed(client, monkeypatch):
    monkeypatch.setattr(event_grid._settings, "event_grid_sas_key", "")
    processed: list[str] = []

    from subscription_vending.workflow import ProvisioningResult

    async def _fake_dispatch(subscription_id, **kwargs):
        processed.append(subscription_id)
        r = ProvisioningResult(subscription_id=subscription_id)
        return r, False

    monkeypatch.setattr(event_grid.controller, "dispatch", _fake_dispatch)

    response = client.post(
        "/webhook/",
        json=[
            _subscription_created_event(subscription_id="sub-a"),
            {
                "id": "evt-skip",
                "eventType": "Microsoft.Resources.ResourceActionSuccess",
                "subject": "/subscriptions/sub-skip/resourceGroups/rg",
                "dataVersion": "1.0",
                "data": {"operationName": "Microsoft.Compute/virtualMachines/write"},
            },
            _subscription_created_event(subscription_id="sub-b"),
        ],
    )

    assert response.status_code == 200
    assert processed == ["sub-a", "sub-b"]
