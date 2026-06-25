from pathlib import Path
import re


def test_docker_compose_override_defines_traefik_proxy() -> None:
    compose = Path("docker-compose.docker.yml").read_text()

    assert "traefik:" in compose
    assert "--providers.docker.exposedbydefault=false" in compose
    assert "--providers.docker.network=tiny-provisioner-apps" in compose
    assert '"80:80"' in compose
    assert '"443:443"' in compose
    assert "/var/run/docker.sock:/var/run/docker.sock:ro" in compose
    assert "name: tiny-provisioner-apps" in compose


def test_worker_gets_docker_socket_only_in_docker_override() -> None:
    default_compose = Path("docker-compose.yml").read_text()
    docker_override = Path("docker-compose.docker.yml").read_text()

    assert "/var/run/docker.sock" not in default_compose
    assert "/var/run/docker.sock:/var/run/docker.sock" in docker_override


def test_dev_compose_api_does_not_use_reload_watcher() -> None:
    compose = Path("docker-compose.yml").read_text()

    assert "--reload" not in compose


def test_production_compose_does_not_publish_datastores_or_api_directly() -> None:
    compose = Path("docker-compose.prod.yml").read_text()

    assert '"5432:5432"' not in compose
    assert '"6379:6379"' not in compose
    assert '"8000:8000"' not in compose
    assert '"8080:8080"' not in compose
    assert re.search(r"ports:\n\s+- \"80:80\"\n\s+- \"443:443\"", compose)
    assert "--api.insecure=true" not in compose
    assert "internal: true" in compose


def test_production_env_example_uses_https_and_docker_backend() -> None:
    env = Path(".env.production.example").read_text()

    assert "APP_ENV=production" in env
    assert "APP_PUBLIC_SCHEME=https" in env
    assert "PROVISIONER_BACKEND=docker" in env
    assert "POSTGRES_PASSWORD=change-this-long-random-password" in env
