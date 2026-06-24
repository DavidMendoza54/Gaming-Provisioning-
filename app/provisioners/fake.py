from app.provisioners.base import ProvisionedResource


class FakeProvisioner:
    """Safe provisioner used while learning lifecycle and job behavior."""

    def __init__(self, base_domain: str = "apps.localhost") -> None:
        self.base_domain = base_domain
        self._resources: dict[int, ProvisionedResource] = {}
        self._logs: dict[str, list[str]] = {}

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
        if resource_id in self._resources:
            return self._resources[resource_id]

        external_id = f"fake-{resource_id}"
        result = ProvisionedResource(
            external_id=external_id,
            url=f"http://{slug}.{self.base_domain}",
        )
        self._resources[resource_id] = result
        self._logs[external_id] = [
            f"created fake resource {external_id}",
            f"image={image} port={exposed_port} cpu={cpu_limit} memory_mb={memory_mb}",
        ]
        return result

    async def start(self, *, external_id: str) -> None:
        self._logs.setdefault(external_id, []).append("started fake resource")

    async def stop(self, *, external_id: str) -> None:
        self._logs.setdefault(external_id, []).append("stopped fake resource")

    async def delete(self, *, external_id: str) -> None:
        self._logs.setdefault(external_id, []).append("deleted fake resource")

    async def logs(self, *, external_id: str, tail: int = 100) -> str:
        lines = self._logs.get(external_id, [f"no logs for {external_id}"])
        return "\n".join(lines[-tail:])
