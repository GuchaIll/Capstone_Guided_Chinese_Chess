from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_SERVICES = [
    "engine",
    "state-bridge",
    "chromadb",
    "embedding",
    "go-coaching",
    "coaching",
]
STARTING_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"
BLACK_TO_MOVE_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR b - - 0 2"
SERVICE_HEALTHCHECKS = {
    "state_bridge": "http://127.0.0.1:5003/health",
    "chromadb": "http://127.0.0.1:8000/api/v1/heartbeat",
    "embedding": "http://127.0.0.1:8100/health",
    "go_coaching": "http://127.0.0.1:5002/health",
    "coaching": "http://127.0.0.1:5001/health",
}


def _is_environment_blocked(message: str) -> bool:
    lowered = message.lower()
    blocked_fragments = [
        "operation not permitted",
        "permission denied",
        "docker.sock",
        "failed to connect to the docker api",
    ]
    return any(fragment in lowered for fragment in blocked_fragments)


def _json_or_text(raw: bytes) -> Any:
    text = raw.decode("utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def http_request(
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> tuple[int, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, _json_or_text(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, _json_or_text(exc.read())


def get_json(url: str, *, timeout: float = 20.0) -> tuple[int, Any]:
    return http_request("GET", url, timeout=timeout)


def post_json(url: str, body: dict[str, Any], *, timeout: float = 20.0) -> tuple[int, Any]:
    return http_request("POST", url, body=body, timeout=timeout)


def get_text(url: str, *, timeout: float = 20.0) -> tuple[int, str]:
    status, body = http_request("GET", url, timeout=timeout)
    return status, body if isinstance(body, str) else json.dumps(body)


def docker_compose(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )


def wait_for_http_ok(url: str, *, timeout: float, description: str) -> None:
    deadline = time.time() + timeout
    last_error = "no response"
    while time.time() < deadline:
        try:
            status, _ = get_json(url, timeout=5.0)
            if status == 200:
                return
            last_error = f"HTTP {status}"
        except Exception as exc:  # pragma: no cover - defensive for flaky environments
            last_error = str(exc)
        time.sleep(2.0)
    raise AssertionError(f"Timed out waiting for {description}: {last_error}")


def wait_for_core_services(timeout: float) -> None:
    for name, url in SERVICE_HEALTHCHECKS.items():
        wait_for_http_ok(url, timeout=timeout, description=f"{name} health at {url}")


def read_sse_events(
    url: str,
    count: int,
    *,
    trigger: Callable[[], None] | None = None,
    timeout: float = 15.0,
) -> list[dict[str, Any]]:
    req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
    events: list[dict[str, Any]] = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if trigger is not None:
            trigger()
        deadline = time.time() + timeout
        data_lines: list[str] = []
        while len(events) < count and time.time() < deadline:
            line = resp.readline()
            if not line:
                continue
            text = line.decode("utf-8").strip()
            if not text:
                if data_lines:
                    payload = json.loads("\n".join(data_lines))
                    events.append(payload)
                    data_lines.clear()
                continue
            if text.startswith("data: "):
                data_lines.append(text[6:])
        if len(events) != count:
            raise AssertionError(f"Expected {count} SSE events, received {len(events)}")
    return events


def read_sse_events_for_duration(url: str, duration: float) -> list[dict[str, Any]]:
    """Read SSE events for a fixed `duration` seconds and return all that arrived."""
    collected: list[dict[str, Any]] = []
    stop = threading.Event()

    def _reader() -> None:
        req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
        data_lines: list[str] = []
        try:
            with urllib.request.urlopen(req, timeout=duration + 2.0) as resp:
                deadline = time.time() + duration
                while not stop.is_set() and time.time() < deadline:
                    try:
                        raw = resp.readline()
                    except Exception:
                        break
                    if not raw:
                        continue
                    text = raw.decode("utf-8").strip()
                    if not text:
                        if data_lines:
                            collected.append(json.loads("\n".join(data_lines)))
                            data_lines.clear()
                    elif text.startswith("data: "):
                        data_lines.append(text[6:])
        except Exception:
            pass

    t = threading.Thread(target=_reader, daemon=True)
    t.start()
    t.join(timeout=duration + 3.0)
    stop.set()
    return collected


@pytest.fixture(scope="session")
def core_stack() -> dict[str, bool]:
    startup_timeout = float(os.getenv("INTEGRATION_TEST_STARTUP_TIMEOUT", "900"))
    auto_start = os.getenv("INTEGRATION_TEST_AUTOSTART", "1") != "0"
    auto_teardown = os.getenv("INTEGRATION_TEST_DOWN", "0") == "1"
    started_here = False

    try:
        wait_for_core_services(timeout=5.0)
    except AssertionError as exc:
        if _is_environment_blocked(str(exc)):
            pytest.skip(
                "Compose-backed integration tests are blocked in this environment "
                "(local service or Docker access is not permitted)."
            )
        if not auto_start:
            pytest.fail("Core services are not healthy and auto-start is disabled.")
        try:
            docker_compose("up", "--build", "-d", *CORE_SERVICES)
        except subprocess.CalledProcessError as exc:
            if _is_environment_blocked(exc.stderr or exc.stdout or str(exc)):
                pytest.skip(
                    "Compose-backed integration tests are blocked in this environment "
                    "(Docker access is not permitted)."
                )
            pytest.fail(
                "docker compose up failed.\n"
                f"stdout:\n{exc.stdout}\n"
                f"stderr:\n{exc.stderr}"
            )
        started_here = True
        try:
            wait_for_core_services(timeout=startup_timeout)
        except AssertionError as exc:
            debug = ""
            try:
                ps = docker_compose("ps")
                debug += f"\n\ndocker compose ps:\n{ps.stdout}"
            except subprocess.CalledProcessError:
                pass
            try:
                logs = docker_compose("logs", "--tail", "200", *CORE_SERVICES)
                debug += f"\n\ndocker compose logs --tail 200:\n{logs.stdout}"
            except subprocess.CalledProcessError:
                pass
            pytest.fail(f"{exc}{debug}")

    yield {"started_here": started_here}

    if started_here and auto_teardown:
        try:
            docker_compose("down", "--remove-orphans")
        except subprocess.CalledProcessError:
            pass


@pytest.fixture()
def reset_bridge_state(core_stack: dict[str, bool]) -> dict[str, Any]:
    status, body = http_request("POST", "http://127.0.0.1:5003/engine/reset", timeout=20.0)
    assert status == 200, body

    status, body = post_json(
        "http://127.0.0.1:5003/state/fen",
        {"fen": STARTING_FEN, "source": "engine"},
        timeout=20.0,
    )
    assert status == 200, body

    status, body = post_json(
        "http://127.0.0.1:5003/state/led-command",
        {"command": "on"},
        timeout=20.0,
    )
    assert status == 200, body

    status, snapshot = get_json("http://127.0.0.1:5003/state", timeout=20.0)
    assert status == 200, snapshot
    return snapshot
