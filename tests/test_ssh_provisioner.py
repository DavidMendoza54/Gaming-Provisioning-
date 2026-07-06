import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.provisioners.factory import make_provisioner
from app.provisioners.ssh import SSHProvisioner
from app.settings import get_settings


def make_ssh_provisioner() -> SSHProvisioner:
    return SSHProvisioner(
        host="vps.example.test",
        user="provisioner",
        key_path="/keys/tiny-provisioner",
        base_domain="apps.example.test",
        public_scheme="https",
    )


def test_ssh_remote_command_is_controlled_and_quoted() -> None:
    provisioner = make_ssh_provisioner()

    command = provisioner.build_remote_command(
        "provision",
        resource_id="7",
        slug="demo app",
        image="tiny-python-http-app:local",
        exposed_port="8000",
        cpu_limit="1",
        memory_mb="128",
    )

    assert command == (
        "tiny-provisioner-remote provision --resource-id 7 --slug 'demo app' "
        "--image tiny-python-http-app:local --exposed-port 8000 --cpu-limit 1 --memory-mb 128"
    )


def test_ssh_command_uses_key_batch_mode_timeout_and_host_key_checking() -> None:
    provisioner = make_ssh_provisioner()

    command = provisioner.build_ssh_command("tiny-provisioner-remote logs --external-id demo")

    assert command == [
        "ssh",
        "-i",
        "/keys/tiny-provisioner",
        "-p",
        "22",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=30",
        "-o",
        "StrictHostKeyChecking=yes",
        "provisioner@vps.example.test",
        "tiny-provisioner-remote logs --external-id demo",
    ]


def test_ssh_provision_returns_remote_url_and_external_id() -> None:
    provisioner = make_ssh_provisioner()
    provisioner._run_remote_action = AsyncMock()  # type: ignore[method-assign]

    result = asyncio.run(
        provisioner.provision(
            resource_id=7,
            slug="demo",
            image="tiny-python-http-app:local",
            exposed_port=8000,
            cpu_limit=1,
            memory_mb=128,
        )
    )

    assert result.external_id == "ssh:vps.example.test:demo"
    assert result.url == "https://demo.apps.example.test"
    assert result.status == "running"
    provisioner._run_remote_action.assert_awaited_once_with(
        "provision",
        resource_id="7",
        slug="demo",
        image="tiny-python-http-app:local",
        exposed_port="8000",
        cpu_limit="1",
        memory_mb="128",
    )


def test_ssh_factory_builds_ssh_provisioner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVISIONER_BACKEND", "ssh")
    monkeypatch.setenv("SSH_HOST", "vps.example.test")
    monkeypatch.setenv("SSH_USER", "provisioner")
    monkeypatch.setenv("SSH_KEY_PATH", "/keys/tiny-provisioner")
    monkeypatch.setenv("APP_BASE_DOMAIN", "apps.example.test")
    monkeypatch.setenv("APP_PUBLIC_SCHEME", "https")
    get_settings.cache_clear()

    try:
        provisioner = make_provisioner()
    finally:
        get_settings.cache_clear()

    assert isinstance(provisioner, SSHProvisioner)


def test_ssh_action_failure_raises_runtime_error() -> None:
    provisioner = make_ssh_provisioner()

    async def scenario() -> None:
        process = AsyncMock()
        process.communicate.return_value = (b"", b"permission denied")
        process.returncode = 255
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
            with pytest.raises(RuntimeError, match="permission denied"):
                await provisioner.logs(external_id="ssh:vps.example.test:demo")

    asyncio.run(scenario())
