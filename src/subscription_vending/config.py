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

    # Mode
    mock_mode:              bool = False

    # Event Grid
    event_grid_sas_key:     str = ""
