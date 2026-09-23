from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, sourced from environment variables."""

    app_name: str = "MOSIP Conformance Center"
    app_version: str = "0.1.0"
    environment: str = "development"
    cors_origins: str = "http://localhost:3000"

    # OpenID Foundation Conformance Suite integration (Milestone 4).
    # These use their exact upstream names (no MCC_ prefix) via
    # validation_alias, since they mirror env vars the OIDF ecosystem's own
    # tooling already uses. There is deliberately no default base URL —
    # point this at a local/staging conformance-suite instance you control,
    # never at the public certification environment by default.
    openid_conformance_base_url: Optional[str] = Field(
        default=None, validation_alias="OPENID_CONFORMANCE_BASE_URL"
    )
    openid_conformance_api_token: Optional[str] = Field(
        default=None, validation_alias="OPENID_CONFORMANCE_API_TOKEN"
    )
    openid_conformance_verify_ssl: bool = Field(
        default=True, validation_alias="OPENID_CONFORMANCE_VERIFY_SSL"
    )
    openid_conformance_timeout: float = Field(
        default=30.0, validation_alias="OPENID_CONFORMANCE_TIMEOUT"
    )
    openid_conformance_wait_timeout: float = Field(
        default=60.0, validation_alias="OPENID_CONFORMANCE_WAIT_TIMEOUT"
    )

    model_config = SettingsConfigDict(env_prefix="MCC_", env_file=".env", extra="ignore")


settings = Settings()
