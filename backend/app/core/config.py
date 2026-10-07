from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    migration_database_url: str | None = None
    secret_key: str = "dev-only-change-me"
    storage_dir: str = "/app/storage"
    default_region: str = "RU"  # для разбора номеров телефона

    access_token_minutes: int = 15
    refresh_token_days: int = 30

    superadmin_phone: str | None = None
    superadmin_password: str | None = None
    superadmin_name: str = "Администратор системы"


@lru_cache
def get_settings() -> Settings:
    return Settings()
