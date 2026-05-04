import json
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from .enums import RetryStrategy


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="VENDING_")

    # Azure
    azure_tenant_id:        str
    azure_client_id:        str = ""          # Empty = ManagedIdentityCredential
    azure_client_secret:    str = ""
    root_management_group:  str = "ITL"       # MG name

    # Authorization service
    authorization_service_url: str = "http://itl-authorization:8004"

    # Keycloak
    keycloak_url:           str = "http://keycloak:8080"
    keycloak_realm:         str = "ITL"

    # RBAC — object IDs for default role assignments on new subscriptions
    platform_spn_object_id:   str = ""
    ops_group_object_id:      str = ""
    security_group_object_id: str = ""
    finops_group_object_id:   str = ""

    # Tag-based management group mapping (JSON string: {"env-name": "MG-Name", ...})
    # Set VENDING_ENVIRONMENT_MG_MAPPING to a JSON object to define unlimited custom environments.
    environment_mg_mapping: str = """{
        "production": "ITL-Production",
        "staging": "ITL-Staging",
        "development": "ITL-Development",
        "sandbox": "ITL-Sandbox"
    }"""

    @property
    def mg_mapping(self) -> dict[str, str]:
        """Parse the JSON mapping and return as dict."""
        try:
            return json.loads(self.environment_mg_mapping)
        except json.JSONDecodeError:
            # Fallback to safe default
            return {"sandbox": "ITL-Sandbox"}

    @property
    def default_mg(self) -> str:
        """Fallback MG when environment is not in mapping."""
        return self.mg_mapping.get("sandbox", "ITL-Sandbox")

    # Configurable tag key names (override to match your own tagging convention)
    tag_environment:        str = "itl-environment"
    tag_aks:                str = "itl-aks"
    tag_budget:             str = "itl-budget"
    tag_owner:              str = "itl-owner"
    tag_snow_ticket:        str = "itl-snow-ticket"

    # Default recipient for budget alerts when itl-owner tag is absent
    default_alert_email:    str = ""

    # Mode
    mock_mode:              bool = False

    # Event Grid
    event_grid_sas_key:          str = ""
    event_grid_topic_endpoint:   str = ""   # Outbound notification topic endpoint

    # Retry strategy — choose one: "queue" | "dead_letter" | "none"
    # queue:        Enqueue to Azure Storage Queue; a worker retries on failure.
    # dead_letter:  Return non-200 to Event Grid on failure so it retries and dead-letters.
    # none:         No retry. Fire-and-forget (current default behaviour).
    retry_strategy:              RetryStrategy = RetryStrategy.NONE

    # Storage Queue (used when retry_strategy = "queue")
    # Uses Managed Identity by default when storage_account_name is set.
    storage_account_name:        str = ""   # e.g. itlvendingsa
    provisioning_queue_name:     str = "provisioning-jobs"
    provisioning_dlq_name:       str = "provisioning-jobs-deadletter"
    queue_max_delivery_count:    int = 5    # Move to DLQ after this many failures
    queue_visibility_timeout:    int = 30   # Seconds before a failed message reappears

    # Shared secret for /worker/process-job and /webhook/replay (leave empty to disable auth)
    worker_secret:               str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton :class:`Settings` instance.

    The instance is constructed once and cached for the lifetime of the
    process.  Use this function instead of calling ``Settings()`` directly to
    avoid creating multiple instances that each read environment variables.

    In tests, call ``get_settings.cache_clear()`` before patching env vars::

        get_settings.cache_clear()
        monkeypatch.setenv("VENDING_AZURE_TENANT_ID", "test-tenant")
        settings = get_settings()
    """
    return Settings()  # type: ignore[call-arg]
