from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .core.config import get_settings
from .extensions import autodiscover
from .handlers.event_grid import router as event_grid_router
from .handlers.jobs import router as jobs_router
from .handlers.mock import router as mock_router
from .handlers.preflight import router as preflight_router
from .handlers.replay import router as replay_router
from .handlers.worker import router as worker_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    autodiscover()
    yield


app = FastAPI(
    title="ITL Subscription Vending",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(event_grid_router)
app.include_router(preflight_router)
app.include_router(replay_router)
app.include_router(jobs_router)

# Worker endpoint — only active when queue strategy is selected
if settings.retry_strategy == "queue":
    app.include_router(worker_router)

if settings.mock_mode:
    app.include_router(mock_router)


@app.get("/health")
async def health():
    """Return service liveness status."""
    return {"status": "ok"}


_REDACTED = "***"
_SECRET_FIELDS = {"azure_client_secret", "worker_secret", "event_grid_sas_key"}


@app.get("/config")
async def config_endpoint():
    """Return active configuration with secrets replaced by '***'."""
    data = settings.model_dump()
    for field in _SECRET_FIELDS:
        if data.get(field):
            data[field] = _REDACTED
    # Stringify enum values for JSON-friendliness
    for key, val in data.items():
        if hasattr(val, "value"):
            data[key] = val.value
    return data
