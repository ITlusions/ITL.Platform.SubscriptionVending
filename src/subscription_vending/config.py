import json
from typing import Dict

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    def mg_mapping(self) -> Dict[str, str]:
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

    # Default recipient for budget alerts when itl-owner tag is absent
    default_alert_email:    str = ""

    # Mode
    mock_mode:              bool = False

    # Event Grid
    event_grid_sas_key:          str = ""
    event_grid_topic_endpoint:   str = ""   # Outbound notification topic endpoint
