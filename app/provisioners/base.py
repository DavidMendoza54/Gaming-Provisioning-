from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProvisionedResource:
    external_id: str
    url: str
    status: str = "running"


class Provisioner(Protocol):
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
        raise NotImplementedError

    async def start(self, *, external_id: str) -> None:
        raise NotImplementedError

    async def stop(self, *, external_id: str) -> None:
        raise NotImplementedError

    async def delete(self, *, external_id: str) -> None:
        raise NotImplementedError

    async def logs(self, *, external_id: str, tail: int = 100) -> str:
        raise NotImplementedError
