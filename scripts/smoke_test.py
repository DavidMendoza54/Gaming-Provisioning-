from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class SmokeConfig:
    base_url: str
    email: str
    password: str
    timeout_seconds: int


class SmokeFailure(RuntimeError):
    pass


def request_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
    expected_status: int | tuple[int, ...] = 200,
) -> dict[str, Any] | list[Any]:
    expected = (expected_status,) if isinstance(expected_status, int) else expected_status
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"

    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=10) as response:
            response_body = response.read().decode("utf-8")
            if response.status not in expected:
                raise SmokeFailure(f"{method} {url} returned {response.status}: {response_body}")
            if not response_body:
                return {}
            return json.loads(response_body)
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise SmokeFailure(f"{method} {url} returned {exc.code}: {error_body}") from exc
    except URLError as exc:
        raise SmokeFailure(f"Could not reach {url}: {exc.reason}") from exc


def poll_resource(
    config: SmokeConfig,
    *,
    token: str,
    resource_id: int,
    target_state: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + config.timeout_seconds
    while time.monotonic() < deadline:
        resource = request_json(
            "GET",
            f"{config.base_url}/resources/{resource_id}",
            token=token,
        )
        assert isinstance(resource, dict)
        state = resource["actual_state"]
        print(f"resource {resource_id} state={state}")
        if state == target_state:
            return resource
        if state == "failed":
            raise SmokeFailure(f"Resource {resource_id} failed: {resource}")
        time.sleep(2)

    raise SmokeFailure(f"Timed out waiting for resource {resource_id} to reach {target_state}")


def run_smoke(config: SmokeConfig) -> None:
    health = request_json("GET", f"{config.base_url}/health")
    print(f"health: {health}")

    token_response = request_json(
        "POST",
        f"{config.base_url}/auth/register",
        payload={"email": config.email, "password": config.password},
        expected_status=(201, 409),
    )
    if isinstance(token_response, dict) and "access_token" in token_response:
        token = token_response["access_token"]
    else:
        login_response = request_json(
            "POST",
            f"{config.base_url}/auth/login",
            payload={"email": config.email, "password": config.password},
        )
        assert isinstance(login_response, dict)
        token = login_response["access_token"]
    print("auth: token acquired")

    templates = request_json("GET", f"{config.base_url}/templates")
    if not isinstance(templates, list) or not templates:
        raise SmokeFailure("No enabled templates found. Did you run python -m app.seed?")
    template = templates[0]
    print(f"template: {template['name']} id={template['id']}")

    resource = request_json(
        "POST",
        f"{config.base_url}/resources",
        token=token,
        payload={"template_id": template["id"], "name": "Smoke Demo"},
        expected_status=202,
    )
    assert isinstance(resource, dict)
    resource_id = resource["id"]
    print(f"created resource: id={resource_id} state={resource['actual_state']}")

    running = poll_resource(config, token=token, resource_id=resource_id, target_state="running")
    print(f"running url: {running['url']}")

    logs = request_json("GET", f"{config.base_url}/resources/{resource_id}/logs", token=token)
    assert isinstance(logs, dict)
    print("logs:")
    print(logs["logs"])

    stopped_request = request_json(
        "POST",
        f"{config.base_url}/resources/{resource_id}/stop",
        token=token,
        expected_status=202,
    )
    assert isinstance(stopped_request, dict)
    print(f"stop queued: state={stopped_request['actual_state']}")
    poll_resource(config, token=token, resource_id=resource_id, target_state="stopped")

    start_request = request_json(
        "POST",
        f"{config.base_url}/resources/{resource_id}/start",
        token=token,
        expected_status=202,
    )
    assert isinstance(start_request, dict)
    print(f"start queued: state={start_request['actual_state']}")
    poll_resource(config, token=token, resource_id=resource_id, target_state="running")

    delete_request = request_json(
        "DELETE",
        f"{config.base_url}/resources/{resource_id}",
        token=token,
        expected_status=202,
    )
    assert isinstance(delete_request, dict)
    print(f"delete queued: state={delete_request['actual_state']}")
    poll_resource(config, token=token, resource_id=resource_id, target_state="deleted")

    events = request_json("GET", f"{config.base_url}/resources/{resource_id}/events", token=token)
    assert isinstance(events, list)
    print("events:")
    for event in events:
        print(f"- {event['event_type']}: {event['message']}")

    print("smoke test passed")


def parse_args() -> SmokeConfig:
    parser = argparse.ArgumentParser(description="Run a TinyProvisioner lifecycle smoke test.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--email", default=None)
    parser.add_argument("--password", default="correct-horse-battery")
    parser.add_argument("--timeout-seconds", type=int, default=60)
    args = parser.parse_args()

    email = args.email or f"smoke-{int(datetime.now(UTC).timestamp())}@example.local"
    return SmokeConfig(
        base_url=args.base_url.rstrip("/"),
        email=email,
        password=args.password,
        timeout_seconds=args.timeout_seconds,
    )


def main() -> int:
    try:
        run_smoke(parse_args())
    except SmokeFailure as exc:
        print(f"smoke test failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

