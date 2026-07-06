from __future__ import annotations

import asyncio
import shlex
from dataclasses import dataclass

from app.provisioners.base import ProvisionedResource


@dataclass(frozen=True)
class SSHCommandResult:
    stdout: str
    stderr: str


class SSHProvisioner:
    """SSH-backed provisioner for running controlled commands on a remote host."""

    def __init__(
        self,
        *,
        host: str,
        user: str,
        key_path: str,
        base_domain: str,
        public_scheme: str = "http",
        port: int = 22,
        remote_command: str = "tiny-provisioner-remote",
        timeout_seconds: int = 60,
        strict_host_key_checking: bool = True,
    ) -> None:
        if not host:
            raise ValueError("SSH host is required")
        if not user:
            raise ValueError("SSH user is required")
        if not key_path:
            raise ValueError("SSH key path is required")

        self.host = host
        self.user = user
        self.key_path = key_path
        self.base_domain = base_domain
        self.public_scheme = public_scheme
        self.port = port
        self.remote_command = remote_command
        self.timeout_seconds = timeout_seconds
        self.strict_host_key_checking = strict_host_key_checking

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
        external_id = self._external_id(slug)
        await self._run_remote_action(
            "provision",
            resource_id=str(resource_id),
            slug=slug,
            image=image,
            exposed_port=str(exposed_port),
            cpu_limit=str(cpu_limit),
            memory_mb=str(memory_mb),
        )
        return ProvisionedResource(
            external_id=external_id,
            url=self._url(slug),
            status="running",
        )

    async def start(self, *, external_id: str) -> None:
        await self._run_remote_action("start", external_id=external_id)

    async def stop(self, *, external_id: str) -> None:
        await self._run_remote_action("stop", external_id=external_id)

    async def delete(self, *, external_id: str) -> None:
        await self._run_remote_action("delete", external_id=external_id)

    async def logs(self, *, external_id: str, tail: int = 100) -> str:
        result = await self._run_remote_action("logs", external_id=external_id, tail=str(tail))
        return result.stdout

    def build_ssh_command(self, remote_command: str) -> list[str]:
        command = [
            "ssh",
            "-i",
            self.key_path,
            "-p",
            str(self.port),
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={min(self.timeout_seconds, 30)}",
            "-o",
            f"StrictHostKeyChecking={'yes' if self.strict_host_key_checking else 'accept-new'}",
            f"{self.user}@{self.host}",
            remote_command,
        ]
        return command

    def build_remote_command(self, action: str, **kwargs: str) -> str:
        parts = [self.remote_command, action]
        for key, value in kwargs.items():
            parts.append(f"--{key.replace('_', '-')}")
            parts.append(value)
        return " ".join(shlex.quote(part) for part in parts)

    async def _run_remote_action(self, action: str, **kwargs: str) -> SSHCommandResult:
        remote_command = self.build_remote_command(action, **kwargs)
        command = self.build_ssh_command(remote_command)

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout_seconds,
            )
        except TimeoutError:
            process.kill()
            await process.communicate()
            raise TimeoutError(f"SSH action timed out after {self.timeout_seconds} seconds")

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        if process.returncode != 0:
            detail = stderr.strip() or stdout.strip() or f"exit code {process.returncode}"
            raise RuntimeError(f"SSH action failed: {detail}")

        return SSHCommandResult(stdout=stdout, stderr=stderr)

    def _external_id(self, slug: str) -> str:
        return f"ssh:{self.host}:{slug}"

    def _url(self, slug: str) -> str:
        return f"{self.public_scheme}://{slug}.{self.base_domain}"
