import os

from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_DB = f"sqlite:///{os.path.join(os.path.expanduser('~'), 'datatracker.db')}"


class Settings(BaseSettings):
    DATABASE_URL: str = _DEFAULT_DB
    SECRET_KEY: str = "change-me-in-production-use-env-var"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()
