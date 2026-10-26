import os
from functools import lru_cache
from typing import Literal
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr, field_validator
from pathlib import Path

class Settings(BaseSettings):
    app_name: str = "MedMind Booking Backend"
    app_env: str = "development"
    diagnostic_storage_dir: Path = Path(
        "data/diagnostics"
    )

    diagnostic_max_upload_bytes: int = (
        10 * 1024 * 1024
    )

    db_server: str = "localhost"
    db_name: str = "MedMind_Booking_DB"
    db_driver: str = "ODBC Driver 18 for SQL Server"
    
    # Use Windows authentication by default.
    db_trusted_connection: bool = True
    db_user: str | None = None
    db_password: str | None = None

    db_encrypt: bool = True
    db_trust_server_certificate: bool = True
    national_id_hash_key: SecretStr | None = None
    national_id_encryption_key: SecretStr | None = None

    jwt_secret_key: SecretStr | None = None
    jwt_algorithm: str = "HS256"
    jwt_access_token_minutes: int = 15

    # Failed staff logins per email before POST /auth/login answers 429
    # (in memory, per backend worker).
    staff_login_max_failures: int = 5
    staff_login_window_minutes: int = 15

    # Trusted gateways allowed to call the AI chat API, as
    # "name=token;name2=token2" (e.g. voice_gateway=...). Unset means the
    # AI chat API rejects every request (fail closed).
    medmind_service_credentials: SecretStr | None = None
    # Rotation overlap only: one extra token per service already listed above,
    # same format and same tenants. Remove after the new token is promoted.
    medmind_service_credentials_next: SecretStr | None = None
    # The Agent -> MCP credential the in-process AI agent sends (and its
    # rotation value). Read here only so no backend service token may equal it.
    mcp_server_token: SecretStr | None = None
    mcp_server_token_next: SecretStr | None = None
    # A chat session expires after this many idle minutes.
    ai_chat_session_idle_minutes: int = 60

    # Caller check on the booking/patient routes the MCP server calls
    # (app/security/booking_auth.py). "audit" is transitional: a missing
    # service token is still accepted and logged. "enforce" rejects it. A
    # token that is present but invalid is rejected in both modes.
    booking_service_auth_mode: Literal["audit", "enforce"] = "audit"

    # Best-effort Groq warm-up at backend startup (app/main.py). "false"
    # skips only that call (no planner change); only "true"/"false" accepted.
    qwen_planner_warmup: bool = True

    # Doctor verification rollout gate (DOCTOR_VERIFICATION_ENFORCED). When
    # true, only verified (and active) doctors are listed, expose slots and
    # can be booked; false (the default) keeps the active-only behavior until
    # the doctor status review is approved. Only "true"/"false" accepted.
    doctor_verification_enforced: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",    
    )

    @field_validator("booking_service_auth_mode", mode="before")
    @classmethod
    def _normalize_auth_mode(cls, value: object) -> object:
        # Any other value fails settings loading (fail closed), never "off".
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("qwen_planner_warmup", "doctor_verification_enforced", mode="before")
    @classmethod
    def _strict_bool(cls, value: object) -> object:
        # Only true/false: "1", "yes", "on" or "" fail instead of guessing.
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in ("true", "false"):
            return value.strip().lower() == "true"
        raise ValueError("must be 'true' or 'false'")

    @property
    def database_url(self) -> str:
        connection_parts = [
            f"DRIVER={{{self.db_driver}}}",
            f"SERVER={self.db_server}",
            f"DATABASE={self.db_name}",
        ]

        if self.db_trusted_connection:
            connection_parts.append("Trusted_Connection=yes")
        else:
            if not self.db_user or not self.db_password:
                raise ValueError(
                    "DB_USER and DB_PASSWORD are required when "
                    "DB_TRUSTED_CONNECTION=false."
                )
            connection_parts.extend(
                [
                    f"UID={self.db_user}",
                    f"PWD={self.db_password}",
                ]
            )

        connection_parts.extend(
            [
                f"Encrypt={'yes' if self.db_encrypt else 'no'}",
                (
                    "TrustServerCertificate="
                    f"{'yes' if self.db_trust_server_certificate else 'no'}"
                ),
            ]
        )

        odbc_connection_string = ";".join(connection_parts)
        return (
            "mssql+pyodbc:///?odbc_connect="
            f"{quote_plus(odbc_connection_string)}"
        )


def staging_selected(environ=None) -> bool:
    """APP_ENV=staging in the PROCESS environment (trimmed, case-insensitive).

    Decided from the real environment only, never from a .env file: in
    staging no .env is loaded anywhere in the backend (run_backend.py, the
    app lifespan, these settings), so values set by the operator cannot be
    silently replaced or filled in from Backend/.env.
    """
    env = os.environ if environ is None else environ
    return (env.get("APP_ENV") or "").strip().lower() == "staging"


@lru_cache
def get_settings() -> Settings:
    if staging_selected():
        return Settings(_env_file=None)
    return Settings()
