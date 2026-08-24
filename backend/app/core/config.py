from functools import lru_cache
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr

class Settings(BaseSettings):
    app_name: str = "MedMind Booking Backend"
    app_env: str = "development"

    db_server: str = "localhost"
    db_name: str = "MedMind_Booking_DB"
    db_driver: str = "ODBC Driver 18 for SQL Server"
    telegram_bot_token: str = ""

    telegram_webhook_secret: str = ""

    telegram_webhook_url: str = ""
    # Use Windows authentication by default.
    db_trusted_connection: bool = True
    db_user: str | None = None
    db_password: str | None = None

    db_encrypt: bool = True
    db_trust_server_certificate: bool = True
    national_id_hash_key: SecretStr | None = None
    national_id_encryption_key: SecretStr | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
