from __future__ import annotations

from pathlib import Path
from typing import Any

from app.provisioners.base import ProvisionedResource


class DockerProvisioner:
    """Docker-backed provisioner for the first real compute substrate."""

    def __init__(
        self,
        *,
        base_domain: str,
        public_scheme: str = "https",
        network_name: str,
        traefik_dynamic_config_path: str | None = None,
        traefik_cert_resolver: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.base_domain = base_domain
        self.public_scheme = public_scheme
        self.network_name = network_name
        self.traefik_dynamic_config_path = (
            Path(traefik_dynamic_config_path) if traefik_dynamic_config_path else None
        )
        self.traefik_cert_resolver = traefik_cert_resolver
        self.client = client or self._client_from_environment()

    async def provision(
        self,
        *,
        resource_id: int,
        slug: str,
        image: str,
        exposed_port: int,
        cpu_limit: int,
        memory_mb: int,
    ) -> ProvisionedResource:
        container_name = self._container_name(slug)
        existing = self._get_container_or_none(container_name)
        if existing is not None:
            self._start_if_needed(existing)
            self._refresh_traefik_routes()
            return ProvisionedResource(
                external_id=existing.id,
                url=self._url(slug),
                status="running",
            )

        network = self._get_or_create_network()
        container = self.client.containers.run(
            image=image,
            name=container_name,
            detach=True,
            network=self._network_identifier(network),
            ports={},
            publish_all_ports=False,
            mem_limit=f"{memory_mb}m",
            nano_cpus=int(cpu_limit * 1_000_000_000),
            labels=self._labels(resource_id=resource_id, slug=slug, exposed_port=exposed_port),
            environment={"PORT": str(exposed_port)},
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            read_only=True,
            tmpfs={"/tmp": "rw,noexec,nosuid,size=64m"},
        )
        self._refresh_traefik_routes()
        return ProvisionedResource(
            external_id=container.id,
            url=self._url(slug),
            status="running",
        )

    async def start(self, *, external_id: str) -> None:
        container = self.client.containers.get(external_id)
        self._start_if_needed(container)
        self._refresh_traefik_routes()

    async def stop(self, *, external_id: str) -> None:
        container = self.client.containers.get(external_id)
        if getattr(container, "status", None) != "exited":
            container.stop(timeout=10)
        self._refresh_traefik_routes()

    async def delete(self, *, external_id: str) -> None:
        try:
            container = self.client.containers.get(external_id)
        except Exception as exc:
            if self._is_not_found(exc):
                self._refresh_traefik_routes()
                return
            raise

        container.remove(force=True)
        self._refresh_traefik_routes()

    async def logs(self, *, external_id: str, tail: int = 100) -> str:
        try:
            container = self.client.containers.get(external_id)
        except Exception as exc:
            if self._is_not_found(exc):
                return "Container logs are unavailable because the container no longer exists."
            raise

        raw_logs = container.logs(tail=tail)
        if isinstance(raw_logs, bytes):
            return raw_logs.decode("utf-8", errors="replace")
        return str(raw_logs)

    def _client_from_environment(self) -> Any:
        try:
            import docker
        except ImportError as exc:
            raise RuntimeError("Docker backend requires the docker Python package") from exc
        return docker.from_env()

    def _get_or_create_network(self) -> Any:
        try:
            return self.client.networks.get(self.network_name)
        except Exception as exc:
            if not self._is_not_found(exc):
                raise

        return self.client.networks.create(
            self.network_name,
            driver="bridge",
            labels={"tiny-provisioner.managed": "true"},
        )

    def _get_container_or_none(self, container_name: str) -> Any | None:
        try:
            return self.client.containers.get(container_name)
        except Exception as exc:
            if self._is_not_found(exc):
                return None
            raise

    def _start_if_needed(self, container: Any) -> None:
        if getattr(container, "status", None) != "running":
            container.start()

    def _labels(self, *, resource_id: int, slug: str, exposed_port: int) -> dict[str, str]:
        return {
            "tiny-provisioner.managed": "true",
            "tiny-provisioner.resource-id": str(resource_id),
            "tiny-provisioner.slug": slug,
            "tiny-provisioner.route-host": f"{slug}.{self.base_domain}",
            "tiny-provisioner.exposed-port": str(exposed_port),
        }

    def _container_name(self, slug: str) -> str:
        return f"tp-{slug}"

    def _url(self, slug: str) -> str:
        return f"{self.public_scheme}://{slug}.{self.base_domain}"

    def _network_identifier(self, network: Any) -> str:
        return getattr(network, "name", self.network_name)

    def _is_not_found(self, exc: Exception) -> bool:
        return exc.__class__.__name__ == "NotFound"

    def _refresh_traefik_routes(self) -> None:
        if self.traefik_dynamic_config_path is None:
            return

        routes = []
        containers = self.client.containers.list(filters={"label": "tiny-provisioner.managed=true"})
        for container in containers:
            labels = getattr(container, "labels", None) or container.attrs.get("Config", {}).get("Labels", {})
            resource_id = labels.get("tiny-provisioner.resource-id")
            host = labels.get("tiny-provisioner.route-host")
            port = labels.get("tiny-provisioner.exposed-port")
            container_name = getattr(container, "name", None)
            if not resource_id or not host or not port or not container_name:
                continue
            routes.append(
                {
                    "service": f"tp-{resource_id}",
                    "host": host,
                    "port": port,
                    "container_name": container_name,
                }
            )

        self._write_traefik_dynamic_config(routes)

    def _write_traefik_dynamic_config(self, routes: list[dict[str, str]]) -> None:
        assert self.traefik_dynamic_config_path is not None

        path = self.traefik_dynamic_config_path
        path.parent.mkdir(parents=True, exist_ok=True)
        content = self._render_traefik_dynamic_config(routes)
        temp_path = path.with_suffix(f"{path.suffix}.tmp")
        temp_path.write_text(content, encoding="utf-8")
        temp_path.replace(path)

    def _render_traefik_dynamic_config(self, routes: list[dict[str, str]]) -> str:
        if not routes:
            return "{}\n"

        entrypoint = "websecure" if self.public_scheme == "https" else "web"
        lines = ["http:", "  routers:"]
        for route in sorted(routes, key=lambda item: item["service"]):
            lines.extend(
                [
                    f"    {route['service']}:",
                    f"      rule: \"Host(`{route['host']}`)\"",
                    "      entryPoints:",
                    f"        - {entrypoint}",
                    f"      service: {route['service']}",
                ]
            )
            if self.public_scheme == "https":
                if self.traefik_cert_resolver:
                    lines.append("      tls:")
                    lines.append(f"        certResolver: {self.traefik_cert_resolver}")
                else:
                    lines.append("      tls: {}")

        lines.append("  services:")
        for route in sorted(routes, key=lambda item: item["service"]):
            lines.extend(
                [
                    f"    {route['service']}:",
                    "      loadBalancer:",
                    "        servers:",
                    f"          - url: \"http://{route['container_name']}:{route['port']}\"",
                ]
            )

        return "\n".join(lines) + "\n"
