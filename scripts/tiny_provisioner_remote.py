#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass


SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class RemoteScriptError(RuntimeError):
    pass


class DockerRunner:
    def run(self, command: list[str], *, check: bool = True) -> CommandResult:
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError as exc:
            raise RemoteScriptError("docker command was not found on the remote host") from exc
        except subprocess.TimeoutExpired as exc:
            raise RemoteScriptError(f"command timed out: {' '.join(command)}") from exc

        result = CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        if check and result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
            raise RemoteScriptError(f"command failed: {detail}")
        return result


def validate_slug(slug: str) -> str:
    if not SLUG_PATTERN.fullmatch(slug):
        raise RemoteScriptError(
            "slug must be lowercase letters, numbers, or hyphens and start with a letter or number"
        )
    return slug


def container_name(slug: str) -> str:
    return f"tp-{validate_slug(slug)}"


def slug_from_external_id(external_id: str) -> str:
    slug = external_id.rsplit(":", 1)[-1]
    return validate_slug(slug)


def inspect_container(runner: DockerRunner, name: str) -> str | None:
    result = runner.run(
        ["docker", "container", "inspect", "--format", "{{.State.Status}}", name],
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or "unknown"


def ensure_network(runner: DockerRunner, network_name: str) -> None:
    result = runner.run(["docker", "network", "inspect", network_name], check=False)
    if result.returncode == 0:
        return

    runner.run(
        [
            "docker",
            "network",
            "create",
            "--driver",
            "bridge",
            "--label",
            "tiny-provisioner.managed=true",
            network_name,
        ]
    )


def provision(args: argparse.Namespace, runner: DockerRunner) -> int:
    name = container_name(args.slug)
    ensure_network(runner, args.network_name)

    status = inspect_container(runner, name)
    if status == "running":
        print(f"{name} already running")
        return 0
    if status is not None:
        runner.run(["docker", "start", name])
        print(f"{name} started")
        return 0

    runner.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--network",
            args.network_name,
            "--label",
            "tiny-provisioner.managed=true",
            "--label",
            f"tiny-provisioner.resource-id={args.resource_id}",
            "--label",
            f"tiny-provisioner.slug={args.slug}",
            "--memory",
            f"{args.memory_mb}m",
            "--cpus",
            str(args.cpu_limit),
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "-e",
            f"PORT={args.exposed_port}",
            args.image,
        ]
    )
    print(f"{name} provisioned")
    return 0


def start(args: argparse.Namespace, runner: DockerRunner) -> int:
    name = container_name(slug_from_external_id(args.external_id))
    status = inspect_container(runner, name)
    if status == "running":
        print(f"{name} already running")
        return 0
    if status is None:
        raise RemoteScriptError(f"{name} does not exist")

    runner.run(["docker", "start", name])
    print(f"{name} started")
    return 0


def stop(args: argparse.Namespace, runner: DockerRunner) -> int:
    name = container_name(slug_from_external_id(args.external_id))
    status = inspect_container(runner, name)
    if status is None:
        raise RemoteScriptError(f"{name} does not exist")
    if status != "running":
        print(f"{name} already stopped")
        return 0

    runner.run(["docker", "stop", "--time", "10", name])
    print(f"{name} stopped")
    return 0


def delete(args: argparse.Namespace, runner: DockerRunner) -> int:
    name = container_name(slug_from_external_id(args.external_id))
    status = inspect_container(runner, name)
    if status is None:
        print(f"{name} already deleted")
        return 0

    runner.run(["docker", "rm", "-f", name])
    print(f"{name} deleted")
    return 0


def logs(args: argparse.Namespace, runner: DockerRunner) -> int:
    name = container_name(slug_from_external_id(args.external_id))
    status = inspect_container(runner, name)
    if status is None:
        print("Container logs are unavailable because the container no longer exists.")
        return 0

    result = runner.run(["docker", "logs", "--tail", str(args.tail), name])
    print(result.stdout, end="")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TinyProvisioner remote Docker command runner.")
    parser.add_argument(
        "--network-name",
        default=os.environ.get("TINY_PROVISIONER_NETWORK", "tiny-provisioner-apps"),
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    provision_parser = subparsers.add_parser("provision")
    provision_parser.add_argument("--resource-id", required=True)
    provision_parser.add_argument("--slug", required=True)
    provision_parser.add_argument("--image", required=True)
    provision_parser.add_argument("--exposed-port", type=int, required=True)
    provision_parser.add_argument("--cpu-limit", type=float, required=True)
    provision_parser.add_argument("--memory-mb", type=int, required=True)
    provision_parser.set_defaults(handler=provision)

    for action, handler in [
        ("start", start),
        ("stop", stop),
        ("delete", delete),
    ]:
        action_parser = subparsers.add_parser(action)
        action_parser.add_argument("--external-id", required=True)
        action_parser.set_defaults(handler=handler)

    logs_parser = subparsers.add_parser("logs")
    logs_parser.add_argument("--external-id", required=True)
    logs_parser.add_argument("--tail", type=int, default=100)
    logs_parser.set_defaults(handler=logs)

    return parser


def run(argv: list[str] | None = None, runner: DockerRunner | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    selected_runner = runner or DockerRunner()
    return args.handler(args, selected_runner)


def main() -> int:
    try:
        return run()
    except RemoteScriptError as exc:
        print(f"tiny-provisioner-remote failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
