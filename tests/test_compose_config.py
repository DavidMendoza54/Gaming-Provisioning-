from pathlib import Path
import re


def test_docker_compose_override_defines_traefik_file_provider() -> None:
    compose = Path("docker-compose.docker.yml").read_text()

    assert "traefik:" in compose
    assert "image: traefik:v3.5" in compose
    assert "--providers.file.directory=/etc/traefik/dynamic" in compose
    assert "--providers.file.watch=true" in compose
    assert "--providers.docker" not in compose
    assert "traefik-dynamic:/etc/traefik/dynamic:ro" in compose
    assert "traefik-dynamic:/var/lib/tiny-provisioner/traefik" in compose
    assert "TRAEFIK_DYNAMIC_CONFIG_PATH: /var/lib/tiny-provisioner/traefik/apps.yml" in compose
    assert '"80:80"' in compose
    assert '"443:443"' in compose
    assert "name: tiny-provisioner-apps" in compose


def test_docker_backend_gives_socket_to_control_plane_only() -> None:
    default_compose = Path("docker-compose.yml").read_text()
    docker_override = Path("docker-compose.docker.yml").read_text()

    assert "/var/run/docker.sock" not in default_compose
    assert "/var/run/docker.sock:/var/run/docker.sock" in docker_override
    assert "api:" in docker_override
    assert "worker:" in docker_override
    assert "PROVISIONER_BACKEND: docker" in docker_override
    assert "tiny-python-http-app:" in docker_override


def test_dev_compose_api_does_not_use_reload_watcher() -> None:
    compose = Path("docker-compose.yml").read_text()

    assert "--reload" not in compose


def test_production_compose_does_not_publish_datastores_or_api_directly() -> None:
    compose = Path("docker-compose.prod.yml").read_text()

    assert '"5432:5432"' not in compose
    assert '"6379:6379"' not in compose
    assert '"8000:8000"' not in compose
    assert '"8080:8080"' not in compose
    assert "image: traefik:v3.5" in compose
    assert re.search(r"ports:\n\s+- \"80:80\"\n\s+- \"443:443\"", compose)
    assert "--api.insecure=true" not in compose
    assert "traefik.enable" not in compose
    assert "internal: true" in compose
    assert "--providers.file.directory=/etc/traefik/dynamic" in compose
    assert "--providers.file.watch=true" in compose
    assert "--providers.docker" not in compose
    assert "TRAEFIK_DYNAMIC_CONFIG_PATH: /var/lib/tiny-provisioner/traefik/apps.yml" in compose
    assert "TRAEFIK_CERT_RESOLVER: letsencrypt" in compose
    assert "traefik-dynamic:/etc/traefik/dynamic:ro" in compose
    assert "/var/run/docker.sock:/var/run/docker.sock" in compose


def test_production_env_example_uses_https_and_docker_backend() -> None:
    env = Path(".env.production.example").read_text()

    assert "APP_ENV=production" in env
    assert "APP_PUBLIC_SCHEME=https" in env
    assert "PROVISIONER_BACKEND=docker" in env
    assert "POSTGRES_PASSWORD=change-this-long-random-password" in env


def test_vps_runbook_uses_production_env_file_for_compose_interpolation() -> None:
    runbook = Path("docs/VPS_RUNBOOK.md").read_text()

    assert "docker compose --env-file .env.production -f docker-compose.prod.yml" in runbook
    assert "docker compose -f docker-compose.prod.yml up -d" not in runbook
