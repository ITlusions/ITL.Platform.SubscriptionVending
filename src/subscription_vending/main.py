from contextlib import asynccontextmanager
from fastapi import FastAPI
from .config import Settings
from .handlers.event_grid import router as event_grid_router
from .handlers.mock import router as mock_router
from .extensions import webhook_notify  # noqa: F401  — registers WebhookNotifyStep
from .extensions import api_notify      # noqa: F401  — registers ApiNotifyStep

settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="ITL Subscription Vending",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(event_grid_router)
if settings.mock_mode:
    app.include_router(mock_router)


@app.get("/health")
async def health():
    """Return service liveness status."""
    return {"status": "ok"}
