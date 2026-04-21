# syntax=docker/dockerfile:1

# ── Builder stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build tools
RUN pip install --no-cache-dir hatchling

# Copy project descriptor first so layer is cached when only source changes
COPY pyproject.toml ./
COPY src/ ./src/

# Build a wheel
RUN pip wheel --no-deps --wheel-dir /build/dist .

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install runtime dependencies then the wheel built above
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
      fastapi \
      "uvicorn[standard]" \
      pydantic \
      pydantic-settings \
      azure-identity \
      azure-mgmt-managementgroups \
      azure-mgmt-authorization \
      azure-mgmt-resource \
      azure-mgmt-subscription \
      httpx

COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

COPY src/ ./src/

EXPOSE 8000

CMD ["uvicorn", "subscription_vending.main:app", "--host", "0.0.0.0", "--port", "8000"]
