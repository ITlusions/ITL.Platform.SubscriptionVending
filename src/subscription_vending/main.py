from contextlib import asynccontextmanager
from fastapi import FastAPI
from .config import Settings
from .handlers.event_grid import router as event_grid_router
from .handlers.mock import router as mock_router
from .handlers.preflight import router as preflight_router
from .extensions import autodiscover

settings = Settings()
autodiscover()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="ITL Subscription Vending",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(event_grid_router)
app.include_router(preflight_router)
if settings.mock_mode:
    app.include_router(mock_router)


@app.get("/health")
async def health():
    """Return service liveness status."""
    return {"status": "ok"}
