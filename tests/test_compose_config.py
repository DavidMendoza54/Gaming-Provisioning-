from pathlib import Path


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
