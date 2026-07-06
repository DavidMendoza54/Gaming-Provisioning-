from __future__ import annotations

from scripts.tiny_provisioner_remote import CommandResult, RemoteScriptError, run


class FakeRunner:
    def __init__(
        self,
        *,
        containers: dict[str, str] | None = None,
        networks: set[str] | None = None,
        logs: dict[str, str] | None = None,
    ) -> None:
        self.containers = containers or {}
        self.networks = networks or set()
        self.logs = logs or {}
        self.commands: list[list[str]] = []

    def run(self, command: list[str], *, check: bool = True) -> CommandResult:
        self.commands.append(command)

        if command[:3] == ["docker", "container", "inspect"]:
            name = command[-1]
            if name not in self.containers:
                return CommandResult(returncode=1, stdout="", stderr="No such container")
            return CommandResult(returncode=0, stdout=f"{self.containers[name]}\n", stderr="")

        if command[:3] == ["docker", "network", "inspect"]:
            network_name = command[-1]
            if network_name not in self.networks:
                return CommandResult(returncode=1, stdout="", stderr="No such network")
            return CommandResult(returncode=0, stdout="{}\n", stderr="")

        if command[:3] == ["docker", "network", "create"]:
            self.networks.add(command[-1])
            return CommandResult(returncode=0, stdout="network-id\n", stderr="")

        if command[:2] == ["docker", "run"]:
            name = command[command.index("--name") + 1]
            self.containers[name] = "running"
            return CommandResult(returncode=0, stdout="container-id\n", stderr="")

        if command[:2] == ["docker", "start"]:
            self.containers[command[-1]] = "running"
            return CommandResult(returncode=0, stdout=command[-1], stderr="")

        if command[:2] == ["docker", "stop"]:
            self.containers[command[-1]] = "exited"
            return CommandResult(returncode=0, stdout=command[-1], stderr="")

        if command[:3] == ["docker", "rm", "-f"]:
            self.containers.pop(command[-1], None)
            return CommandResult(returncode=0, stdout=command[-1], stderr="")

        if command[:2] == ["docker", "logs"]:
            return CommandResult(returncode=0, stdout=self.logs.get(command[-1], ""), stderr="")

        if check:
            raise RemoteScriptError(f"unexpected command: {command}")
        return CommandResult(returncode=1, stdout="", stderr="unexpected command")


def provision_args(slug: str = "demo") -> list[str]:
    return [
        "provision",
        "--resource-id",
        "7",
        "--slug",
        slug,
        "--image",
        "tiny-python-http-app:local",
        "--exposed-port",
        "8000",
        "--cpu-limit",
        "1",
        "--memory-mb",
        "128",
    ]


def test_provision_creates_network_and_container_when_missing() -> None:
    runner = FakeRunner()

    result = run(provision_args(), runner)

    assert result == 0
    assert "tiny-provisioner-apps" in runner.networks
    assert runner.containers["tp-demo"] == "running"
    assert any(command[:2] == ["docker", "run"] for command in runner.commands)


def test_provision_is_idempotent_when_container_is_already_running() -> None:
    runner = FakeRunner(containers={"tp-demo": "running"}, networks={"tiny-provisioner-apps"})

    result = run(provision_args(), runner)

    assert result == 0
    assert not any(command[:2] == ["docker", "run"] for command in runner.commands)
    assert not any(command[:2] == ["docker", "start"] for command in runner.commands)


def test_provision_starts_existing_stopped_container() -> None:
    runner = FakeRunner(containers={"tp-demo": "exited"}, networks={"tiny-provisioner-apps"})

    result = run(provision_args(), runner)

    assert result == 0
    assert runner.containers["tp-demo"] == "running"
    assert ["docker", "start", "tp-demo"] in runner.commands


def test_delete_is_idempotent_when_container_is_missing() -> None:
    runner = FakeRunner()

    result = run(["delete", "--external-id", "ssh:vps.example.test:demo"], runner)

    assert result == 0
    assert not any(command[:3] == ["docker", "rm", "-f"] for command in runner.commands)


def test_delete_removes_existing_container() -> None:
    runner = FakeRunner(containers={"tp-demo": "running"})

    result = run(["delete", "--external-id", "ssh:vps.example.test:demo"], runner)

    assert result == 0
    assert "tp-demo" not in runner.containers
    assert ["docker", "rm", "-f", "tp-demo"] in runner.commands


def test_logs_for_missing_container_are_friendly(capsys) -> None:
    runner = FakeRunner()

    result = run(["logs", "--external-id", "ssh:vps.example.test:demo"], runner)

    assert result == 0
    assert "container no longer exists" in capsys.readouterr().out


def test_invalid_slug_is_rejected() -> None:
    runner = FakeRunner()

    try:
        run(provision_args("bad;rm-rf"), runner)
    except RemoteScriptError as exc:
        assert "slug must be lowercase" in str(exc)
    else:
        raise AssertionError("invalid slug was not rejected")
