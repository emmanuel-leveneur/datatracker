import os

from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_DB = f"sqlite:///{os.path.join(os.path.expanduser('~'), 'datatracker.db')}"


class Settings(BaseSettings):
    DATABASE_URL: str = _DEFAULT_DB
    SECRET_KEY: str = "change-me-in-production-use-env-var"

    # Chiffrement SQLCipher (AES-256). Laisser vide pour SQLite non chiffré.
    DB_ENCRYPTION_KEY: str = ""

    # URL publique de l'application (utilisée dans les liens des emails)
    APP_URL: str = "http://localhost:8000"

    # Identité de l'organisation (optionnel — utilisé dans le footer et les mentions RGPD)
    ORG_NAME: str = ""
    DPO_EMAIL: str = ""

    # SMTP (optionnel — si non configuré, les emails ne sont pas envoyés)
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_USE_TLS: bool = True

    # Pièces jointes
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE_MB: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()
