import asyncio
from typing import Any

from app.provisioners.docker import DockerProvisioner


class NotFound(Exception):
    pass


class FakeNetwork:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeNetworks:
    def __init__(self) -> None:
        self.networks: dict[str, FakeNetwork] = {}
        self.created: list[dict[str, Any]] = []

    def get(self, name: str) -> FakeNetwork:
        try:
            return self.networks[name]
        except KeyError as exc:
            raise NotFound(name) from exc

    def create(self, name: str, **kwargs: Any) -> FakeNetwork:
        network = FakeNetwork(name)
        self.networks[name] = network
        self.created.append({"name": name, **kwargs})
        return network


class FakeContainer:
    def __init__(
        self,
        container_id: str,
        status: str = "running",
        name: str = "tp-demo-app",
        labels: dict[str, str] | None = None,
    ) -> None:
        self.id = container_id
        self.status = status
        self.name = name
        self.labels = labels or {}
        self.attrs = {"Config": {"Labels": self.labels}}
        self.started = False
        self.stopped = False
        self.removed = False

    def start(self) -> None:
        self.started = True
        self.status = "running"

    def stop(self, timeout: int) -> None:
        self.stopped = True
        self.status = "exited"
        self.stop_timeout = timeout

    def remove(self, force: bool) -> None:
        self.removed = True
        self.remove_force = force
        self.status = "removed"

    def logs(self, tail: int) -> bytes:
        return f"last {tail} log lines".encode()


class FakeContainers:
    def __init__(self) -> None:
        self.containers: dict[str, FakeContainer] = {}
        self.run_calls: list[dict[str, Any]] = []

    def get(self, key: str) -> FakeContainer:
        try:
            return self.containers[key]
        except KeyError as exc:
            raise NotFound(key) from exc

    def run(self, **kwargs: Any) -> FakeContainer:
        container = FakeContainer(
            container_id="container-1",
            name=kwargs["name"],
            labels=kwargs["labels"],
        )
        self.containers[kwargs["name"]] = container
        self.containers[container.id] = container
        self.run_calls.append(kwargs)
        return container

    def list(self, filters: dict[str, str] | None = None) -> list[FakeContainer]:
        label_filter = (filters or {}).get("label")
        seen: set[int] = set()
        containers = []
        for container in self.containers.values():
            identity = id(container)
            if identity in seen or container.status != "running":
                continue
            seen.add(identity)
            if label_filter is not None:
                key, _, value = label_filter.partition("=")
                if container.labels.get(key) != value:
                    continue
            containers.append(container)
        return containers


class FakeDockerClient:
    def __init__(self) -> None:
        self.containers = FakeContainers()
        self.networks = FakeNetworks()


def make_docker_provisioner(
    client: FakeDockerClient,
    *,
    dynamic_config_path: str | None = None,
    public_scheme: str = "http",
    cert_resolver: str | None = None,
) -> DockerProvisioner:
    return DockerProvisioner(
        base_domain="apps.example.test",
        public_scheme=public_scheme,
        network_name="tiny-provisioner-apps",
        traefik_dynamic_config_path=dynamic_config_path,
        traefik_cert_resolver=cert_resolver,
        client=client,
    )


def test_docker_provisioner_creates_container_without_publishing_host_ports() -> None:
    client = FakeDockerClient()
    provisioner = make_docker_provisioner(client)

    result = asyncio.run(
        provisioner.provision(
            resource_id=42,
            slug="demo-app",
            image="tiny-python-http-app:local",
            exposed_port=8000,
            cpu_limit=2,
            memory_mb=256,
        )
    )

    run_call = client.containers.run_calls[0]

    assert result.external_id == "container-1"
    assert result.url == "http://demo-app.apps.example.test"
    assert client.networks.created[0]["name"] == "tiny-provisioner-apps"
    assert run_call["name"] == "tp-demo-app"
    assert run_call["network"] == "tiny-provisioner-apps"
    assert run_call["ports"] == {}
    assert run_call["publish_all_ports"] is False
    assert run_call["mem_limit"] == "256m"
    assert run_call["nano_cpus"] == 2_000_000_000
    assert run_call["cap_drop"] == ["ALL"]
    assert run_call["security_opt"] == ["no-new-privileges:true"]
    assert run_call["read_only"] is True
    assert run_call["labels"]["tiny-provisioner.resource-id"] == "42"
    assert run_call["labels"]["tiny-provisioner.slug"] == "demo-app"
    assert run_call["labels"]["tiny-provisioner.route-host"] == "demo-app.apps.example.test"
    assert run_call["labels"]["tiny-provisioner.exposed-port"] == "8000"
    assert "traefik.enable" not in run_call["labels"]


def test_docker_provisioner_writes_traefik_file_config(tmp_path) -> None:
    client = FakeDockerClient()
    dynamic_config_path = tmp_path / "apps.yml"
    provisioner = make_docker_provisioner(
        client,
        dynamic_config_path=str(dynamic_config_path),
    )

    asyncio.run(
        provisioner.provision(
            resource_id=42,
            slug="demo-app",
            image="tiny-python-http-app:local",
            exposed_port=8000,
            cpu_limit=2,
            memory_mb=256,
        )
    )

    content = dynamic_config_path.read_text()

    assert 'rule: "Host(`demo-app.apps.example.test`)"' in content
    assert "        - web" in content
    assert "      service: tp-42" in content
    assert '          - url: "http://tp-demo-app:8000"' in content


def test_docker_provisioner_writes_https_route_with_cert_resolver(tmp_path) -> None:
    client = FakeDockerClient()
    dynamic_config_path = tmp_path / "apps.yml"
    provisioner = make_docker_provisioner(
        client,
        dynamic_config_path=str(dynamic_config_path),
        public_scheme="https",
        cert_resolver="letsencrypt",
    )

    asyncio.run(
        provisioner.provision(
            resource_id=42,
            slug="demo-app",
            image="tiny-python-http-app:local",
            exposed_port=8000,
            cpu_limit=2,
            memory_mb=256,
        )
    )

    content = dynamic_config_path.read_text()

    assert "        - websecure" in content
    assert "      tls:" in content
    assert "        certResolver: letsencrypt" in content


def test_docker_provisioner_writes_empty_config_after_delete(tmp_path) -> None:
    client = FakeDockerClient()
    dynamic_config_path = tmp_path / "apps.yml"
    provisioner = make_docker_provisioner(
        client,
        dynamic_config_path=str(dynamic_config_path),
    )

    asyncio.run(
        provisioner.provision(
            resource_id=42,
            slug="demo-app",
            image="tiny-python-http-app:local",
            exposed_port=8000,
            cpu_limit=2,
            memory_mb=256,
        )
    )
    asyncio.run(provisioner.delete(external_id="container-1"))

    assert dynamic_config_path.read_text() == "{}\n"


def test_docker_provisioner_is_idempotent_for_existing_container() -> None:
    client = FakeDockerClient()
    existing = FakeContainer(container_id="existing-container", status="exited")
    client.containers.containers["tp-demo-app"] = existing
    provisioner = make_docker_provisioner(client)

    result = asyncio.run(
        provisioner.provision(
            resource_id=42,
            slug="demo-app",
            image="tiny-python-http-app:local",
            exposed_port=8000,
            cpu_limit=1,
            memory_mb=128,
        )
    )

    assert result.external_id == "existing-container"
    assert existing.started is True
    assert client.containers.run_calls == []


def test_docker_delete_is_safe_when_container_is_already_gone() -> None:
    client = FakeDockerClient()
    provisioner = make_docker_provisioner(client)

    asyncio.run(provisioner.delete(external_id="missing-container"))


def test_docker_lifecycle_methods_call_container_operations() -> None:
    client = FakeDockerClient()
    container = FakeContainer(container_id="container-1", status="running")
    client.containers.containers["container-1"] = container
    provisioner = make_docker_provisioner(client)

    asyncio.run(provisioner.stop(external_id="container-1"))
    asyncio.run(provisioner.start(external_id="container-1"))
    logs = asyncio.run(provisioner.logs(external_id="container-1", tail=25))

    assert container.stopped is True
    assert container.stop_timeout == 10
    assert container.started is True
    assert logs == "last 25 log lines"
