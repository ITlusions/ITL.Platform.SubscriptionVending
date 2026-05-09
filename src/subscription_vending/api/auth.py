"""Entra ID Bearer token validation dependency for the Vending API.

Usage
-----
The dependency is registered globally in main.py.  All endpoints require a
valid Bearer token when ``VENDING_API_ENTRA_TENANT_ID`` is set.

When the setting is absent the dependency is a no-op (returns empty claims
dict) so the service can run without auth during local development.

Required settings
-----------------
VENDING_API_ENTRA_TENANT_ID   Entra ID tenant ID — enables auth when set
VENDING_API_ENTRA_AUDIENCE    App URI, e.g. ``api://<client-id>``
VENDING_API_ENTRA_REQUIRED_ROLE  (optional) App role value every caller must hold

Required extras
---------------
pip install 'itl-subscription-vending[auth]'   (installs PyJWT[crypto])
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..core.config import get_settings

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache(maxsize=8)
def _jwks_client(jwks_url: str) -> Any:
    """Return a cached ``PyJWKClient`` for *jwks_url*.

    The client itself caches keys internally (``cache_keys=True``), so JWKS
    is only re-fetched when a token arrives with an unknown ``kid``.
    """
    try:
        from jwt import PyJWKClient  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "PyJWT[crypto] is required for API auth.  "
            "Run: pip install 'itl-subscription-vending[auth]'"
        ) from exc
    return PyJWKClient(jwks_url, cache_keys=True)


async def require_bearer(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """FastAPI dependency — validate a Bearer token issued by Entra ID.

    Returns the decoded JWT claims as a ``dict``.

    * When ``VENDING_API_ENTRA_TENANT_ID`` is not configured, returns ``{}``
      (auth disabled — all requests pass through).
    * Returns ``HTTP 401`` when no / invalid token is supplied.
    * Returns ``HTTP 403`` when the token is valid but the caller lacks the
      required app role (``VENDING_API_ENTRA_REQUIRED_ROLE``).
    """
    settings = get_settings()
    tenant_id = settings.api_entra_tenant_id
    if not tenant_id:
        return {}  # auth disabled

    if not settings.api_entra_audience:
        logger.error(
            "VENDING_API_ENTRA_TENANT_ID is set but VENDING_API_ENTRA_AUDIENCE is missing. "
            "Set it to the app URI, e.g. api://<client-id>."
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API auth is misconfigured — contact the administrator.",
        )

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        import jwt  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "PyJWT[crypto] is required for API auth.  "
            "Run: pip install 'itl-subscription-vending[auth]'"
        ) from exc

    jwks_url = (
        f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
    )
    client = _jwks_client(jwks_url)

    try:
        signing_key = client.get_signing_key_from_jwt(credentials.credentials)
    except Exception as exc:
        logger.warning("JWKS key lookup failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
    try:
        claims: dict[str, Any] = jwt.decode(
            credentials.credentials,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.api_entra_audience,
            issuer=issuer,
            options={"verify_exp": True},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except jwt.InvalidTokenError as exc:
        logger.warning("JWT validation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    # ── Role check ────────────────────────────────────────────────────────────
    required_role = settings.api_entra_required_role
    if required_role:
        # 'roles' claim contains app role values assigned to the caller.
        # Define app roles on the app registration and assign users / service
        # principals under Enterprise applications → Users and groups.
        caller_roles: list[str] = claims.get("roles") or []
        if required_role not in caller_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Caller does not have the required role '{required_role}'. "
                    "Contact your administrator to request access."
                ),
            )

    return claims
