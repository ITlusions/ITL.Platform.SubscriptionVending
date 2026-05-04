"""Tests for the retry dispatcher, queue worker, and replay endpoint."""

from __future__ import annotations

import base64
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("VENDING_AZURE_TENANT_ID", "test-tenant-id")

from subscription_vending.core.config import Settings  # noqa: E402
from subscription_vending.core.enums import RetryStrategy  # noqa: E402
from subscription_vending.core.job import ProvisioningJob  # noqa: E402
from subscription_vending.workflow import ProvisioningResult  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(**kwargs) -> Settings:
    defaults = {
        "azure_tenant_id": "test-tenant-id",
        "retry_strategy": "none",
        "storage_account_name": "",
        "worker_secret": "",
    }
    defaults.update(kwargs)
    return Settings(**defaults)


def _make_result(errors: list[str] | None = None) -> ProvisioningResult:
    r = ProvisioningResult(subscription_id="sub-123")
    r.errors = errors or []
    return r


# ---------------------------------------------------------------------------
# ProvisioningJob serialisation
# ---------------------------------------------------------------------------

class TestProvisioningJob:
    def test_roundtrip(self):
        job = ProvisioningJob(
            subscription_id="sub-abc",
            subscription_name="my-sub",
            management_group_id="ITL-Dev",
            attempt=2,
        )
        restored = ProvisioningJob.from_json(job.to_json())
        assert restored.subscription_id == "sub-abc"
        assert restored.subscription_name == "my-sub"
        assert restored.management_group_id == "ITL-Dev"
        assert restored.attempt == 2
        assert restored.job_id == job.job_id

    def test_from_json_defaults(self):
        raw = json.dumps({"subscription_id": "sub-xyz"})
        job = ProvisioningJob.from_json(raw)
        assert job.subscription_id == "sub-xyz"
        assert job.subscription_name == ""
        assert job.attempt == 1


# ---------------------------------------------------------------------------
# Dispatcher — strategy: none
# ---------------------------------------------------------------------------

class TestDispatcherNone:
    @pytest.mark.asyncio
    async def test_none_runs_inline(self):
        settings = _make_settings(retry_strategy="none")
        result = _make_result()

        with patch(
            "subscription_vending.workflow.engine.WorkflowEngine.run",
            new=AsyncMock(return_value=result),
        ) as mock_run:
            from subscription_vending.infrastructure.queue.dispatcher import dispatch

            out_result, should_error = await dispatch(
                subscription_id="sub-123",
                subscription_name="test",
                management_group_id="",
                settings=settings,
            )
            mock_run.assert_awaited_once()
            assert should_error is False
            assert out_result is result

    @pytest.mark.asyncio
    async def test_none_does_not_error_on_failure(self):
        settings = _make_settings(retry_strategy="none")
        result = _make_result(errors=["something failed"])

        with patch(
            "subscription_vending.workflow.engine.WorkflowEngine.run",
            new=AsyncMock(return_value=result),
        ):
            from subscription_vending.infrastructure.queue.dispatcher import dispatch

            _, should_error = await dispatch("sub-123", "", "", settings)
            assert should_error is False


# ---------------------------------------------------------------------------
# Dispatcher — strategy: dead_letter
# ---------------------------------------------------------------------------

class TestDispatcherDeadLetter:
    @pytest.mark.asyncio
    async def test_dead_letter_returns_error_flag_on_failure(self):
        settings = _make_settings(retry_strategy="dead_letter")
        result = _make_result(errors=["rbac failed"])

        with patch(
            "subscription_vending.workflow.engine.WorkflowEngine.run",
            new=AsyncMock(return_value=result),
        ):
            from subscription_vending.infrastructure.queue.dispatcher import dispatch

            _, should_error = await dispatch("sub-123", "", "", settings)
            assert should_error is True

    @pytest.mark.asyncio
    async def test_dead_letter_no_error_flag_on_success(self):
        settings = _make_settings(retry_strategy="dead_letter")
        result = _make_result()

        with patch(
            "subscription_vending.workflow.engine.WorkflowEngine.run",
            new=AsyncMock(return_value=result),
        ):
            from subscription_vending.infrastructure.queue.dispatcher import dispatch

            _, should_error = await dispatch("sub-123", "", "", settings)
            assert should_error is False


# ---------------------------------------------------------------------------
# Dispatcher — strategy: queue
# ---------------------------------------------------------------------------

class TestDispatcherQueue:
    @pytest.mark.asyncio
    async def test_queue_enqueues_job(self):
        settings = _make_settings(
            retry_strategy="queue",
            storage_account_name="mysa",
            provisioning_queue_name="prov-jobs",
            provisioning_dlq_name="prov-jobs-dlq",
        )

        with patch("subscription_vending.infrastructure.queue.dispatcher.ensure_queues_exist") as mock_ensure, \
             patch("subscription_vending.infrastructure.queue.dispatcher.enqueue_job") as mock_enqueue, \
             patch("subscription_vending.infrastructure.queue.dispatcher._queues_ensured", False):

            from subscription_vending.infrastructure.queue import dispatcher as disp
            disp._queues_ensured = False

            out_result, should_error = await disp.dispatch("sub-123", "my-sub", "ITL-Dev", settings)

            mock_ensure.assert_called_once_with("mysa", "prov-jobs", "prov-jobs-dlq")
            mock_enqueue.assert_called_once()
            # Check the enqueued JSON contains the right subscription_id
            enqueued_json = mock_enqueue.call_args[0][2]
            data = json.loads(enqueued_json)
            assert data["subscription_id"] == "sub-123"
            assert data["subscription_name"] == "my-sub"
            assert out_result is None
            assert should_error is False

    @pytest.mark.asyncio
    async def test_queue_falls_back_when_no_storage_account(self):
        settings = _make_settings(retry_strategy="queue", storage_account_name="")
        result = _make_result()

        with patch(
            "subscription_vending.workflow.engine.WorkflowEngine.run",
            new=AsyncMock(return_value=result),
        ) as mock_run:
            from subscription_vending.infrastructure.queue.dispatcher import dispatch

            out_result, _ = await dispatch("sub-123", "", "", settings)
            mock_run.assert_awaited_once()
            assert out_result is result


# ---------------------------------------------------------------------------
# Worker handler
# ---------------------------------------------------------------------------

class TestWorkerHandler:
    def _encode(self, job: ProvisioningJob) -> str:
        return base64.b64encode(job.to_json().encode()).decode()

    @pytest.mark.asyncio
    async def test_worker_processes_job_successfully(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from subscription_vending.handlers.worker import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        job = ProvisioningJob(subscription_id="sub-worker-1")
        result = _make_result()

        with patch(
            "subscription_vending.workflow.engine.WorkflowEngine.run",
            new=AsyncMock(return_value=result),
        ), patch(
            "subscription_vending.handlers.worker.controller._settings",
            _make_settings(worker_secret=""),
        ):
            resp = client.post(
                "/worker/process-job",
                json={"message": self._encode(job), "delivery_count": 1},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_worker_returns_500_on_failure(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from subscription_vending.handlers.worker import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        job = ProvisioningJob(subscription_id="sub-worker-2")
        result = _make_result(errors=["step failed"])

        with patch(
            "subscription_vending.workflow.engine.WorkflowEngine.run",
            new=AsyncMock(return_value=result),
        ), patch(
            "subscription_vending.handlers.worker.controller._settings",
            _make_settings(worker_secret=""),
        ):
            resp = client.post(
                "/worker/process-job",
                json={"message": self._encode(job), "delivery_count": 1},
            )
        assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_worker_dead_letters_at_max_delivery(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from subscription_vending.handlers.worker import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        job = ProvisioningJob(subscription_id="sub-worker-3")

        with patch(
            "subscription_vending.handlers.worker.controller.move_to_dlq",
        ) as mock_dlq, patch(
            "subscription_vending.handlers.worker.controller._settings",
            _make_settings(
                worker_secret="",
                storage_account_name="mysa",
                provisioning_dlq_name="prov-dlq",
                queue_max_delivery_count=3,
            ),
        ):
            resp = client.post(
                "/worker/process-job",
                json={"message": self._encode(job), "delivery_count": 4},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "dead_lettered"
        mock_dlq.assert_called_once()


# ---------------------------------------------------------------------------
# Replay handler
# ---------------------------------------------------------------------------

class TestReplayHandler:
    @pytest.mark.asyncio
    async def test_replay_runs_workflow(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from subscription_vending.handlers.replay import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        result = _make_result()
        result.plan = ["[STEP_MG] would move to ITL-Dev"]

        with patch(
            "subscription_vending.workflow.engine.WorkflowEngine.run",
            new=AsyncMock(return_value=result),
        ), patch(
            "subscription_vending.handlers.replay.controller._settings",
            _make_settings(worker_secret=""),
        ):
            resp = client.post(
                "/webhook/replay",
                json={"subscription_id": "sub-replay-1", "dry_run": True},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["subscription_id"] == "sub-replay-1"

    @pytest.mark.asyncio
    async def test_replay_returns_error_status_on_failure(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from subscription_vending.handlers.replay import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        result = _make_result(errors=["rbac failed"])

        with patch(
            "subscription_vending.workflow.engine.WorkflowEngine.run",
            new=AsyncMock(return_value=result),
        ), patch(
            "subscription_vending.handlers.replay.controller._settings",
            _make_settings(worker_secret=""),
        ):
            resp = client.post(
                "/webhook/replay",
                json={"subscription_id": "sub-replay-2"},
            )
        assert resp.status_code == 200  # HTTP is 200; error is in body
        assert resp.json()["status"] == "error"
        assert "rbac failed" in resp.json()["errors"]

    @pytest.mark.asyncio
    async def test_replay_rejects_wrong_secret(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from subscription_vending.handlers.replay import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        with patch(
            "subscription_vending.handlers.replay.controller._settings",
            _make_settings(worker_secret="correct-secret"),
        ):
            resp = client.post(
                "/webhook/replay",
                json={"subscription_id": "sub-replay-3"},
                headers={"x-replay-secret": "wrong-secret"},
            )
        assert resp.status_code == 401
