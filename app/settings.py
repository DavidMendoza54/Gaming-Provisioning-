from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "local"
    app_base_domain: str = "apps.localhost"
    app_public_scheme: str = "http"
    provisioner_backend: str = "fake"
    docker_network_name: str = "tiny-provisioner-apps"
    traefik_dynamic_config_path: str | None = None
    traefik_cert_resolver: str | None = None
    max_active_resources_per_user: int = 3
    default_resource_ttl_hours: int = 24
    database_url: str = "postgresql+psycopg://provisioner:provisioner@localhost:5432/provisioner"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = "change-me-in-real-deployments"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
