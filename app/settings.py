from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "local"
    app_base_domain: str = "apps.localhost"
    app_public_scheme: str = "http"
    provisioner_backend: str = "fake"
    docker_network_name: str = "tiny-provisioner-apps"
    traefik_dynamic_config_path: str | None = None
    traefik_cert_resolver: str | None = None
    ssh_host: str = ""
    ssh_user: str = ""
    ssh_key_path: str = ""
    ssh_port: int = 22
    ssh_remote_command: str = "tiny-provisioner-remote"
    ssh_timeout_seconds: int = 60
    ssh_strict_host_key_checking: bool = True
    max_active_resources_per_user: int = 3
    default_resource_ttl_hours: int = 24
    job_max_attempts: int = Field(default=3, ge=1)
    job_retry_base_seconds: int = Field(default=5, ge=1)
    job_retry_max_seconds: int = Field(default=300, ge=1)
    job_lease_seconds: int = Field(default=90, ge=2)
    worker_heartbeat_interval_seconds: int = Field(default=10, ge=1)
    worker_stale_after_seconds: int = Field(default=30, ge=2)
    worker_metrics_port: int = Field(default=9101, ge=1, le=65535)
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://provisioner:provisioner@localhost:5432/provisioner"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = "change-me-in-real-deployments"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @model_validator(mode="after")
    def validate_worker_timing(self) -> "Settings":
        if self.job_retry_max_seconds < self.job_retry_base_seconds:
            raise ValueError("JOB_RETRY_MAX_SECONDS must be at least JOB_RETRY_BASE_SECONDS")
        if self.job_lease_seconds <= self.worker_heartbeat_interval_seconds:
            raise ValueError("JOB_LEASE_SECONDS must be longer than the worker heartbeat interval")
        if self.worker_stale_after_seconds <= self.worker_heartbeat_interval_seconds:
            raise ValueError(
                "WORKER_STALE_AFTER_SECONDS must be longer than the worker heartbeat interval"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
