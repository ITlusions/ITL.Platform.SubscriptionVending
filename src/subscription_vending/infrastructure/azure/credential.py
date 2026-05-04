"""Azure credential factory — shared across all infrastructure.azure adapters."""

from __future__ import annotations

from azure.identity import ClientSecretCredential, ManagedIdentityCredential

from ...core.config import Settings


def get_credential(settings: Settings):
    """Return the appropriate Azure credential based on configuration.

    Uses a Service Principal (ClientSecretCredential) when both
    ``azure_client_id`` and ``azure_client_secret`` are set; falls back
    to Managed Identity for production / container deployments.
    """
    if settings.azure_client_id and settings.azure_client_secret:
        return ClientSecretCredential(
            tenant_id=settings.azure_tenant_id,
            client_id=settings.azure_client_id,
            client_secret=settings.azure_client_secret,
        )
    return ManagedIdentityCredential()
