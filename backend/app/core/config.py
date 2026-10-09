from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = ""
    migration_database_url: str | None = None
    secret_key: str = "dev-only-change-me"
    storage_dir: str = "/app/storage"
    default_region: str = "RU"  # для разбора номеров телефона
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    max_failed_logins: int = 5
    lock_minutes: int = 15

    access_token_minutes: int = 15
    refresh_token_days: int = 30

    superadmin_phone: str | None = None
    superadmin_password: str | None = None
    superadmin_name: str = "Администратор системы"

    # Мастер-пароль файла storage/credentials.vault; если задан — пароли из файла
    # загружаются в БД при каждом запуске сервера
    credentials_passphrase: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
