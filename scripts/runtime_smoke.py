"""Verify runtime-only imports and the formal local application entry point."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((HOST, 0))
        return int(probe.getsockname()[1])


def _wait_for_response(url: str, timeout: float = 15.0) -> tuple[int, bytes]:
    deadline = time.monotonic() + timeout
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                return response.status, response.read()
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
            time.sleep(0.1)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def _verify_factory() -> None:
    import ui.app
    from ui.app import create_app

    if hasattr(ui.app, "app"):
        raise RuntimeError("ui.app constructed a module-level application")
    with tempfile.TemporaryDirectory(prefix="job-learning-planner-") as temp_dir:
        application = create_app(Path(temp_dir) / "state")
        if application.title != "Job Learning Planner":
            raise RuntimeError("application factory returned an unexpected app")


def _verify_formal_entrypoint() -> None:
    port = _available_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "ui", "--port", str(port)],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        root_status, _ = _wait_for_response(f"http://{HOST}:{port}/")
        health_status, health_body = _wait_for_response(
            f"http://{HOST}:{port}/health"
        )
        if root_status != 200 or health_status != 200:
            raise RuntimeError(
                f"unexpected HTTP status: root={root_status}, health={health_status}"
            )
        health_payload = json.loads(health_body)
        if not isinstance(health_payload, dict) or health_payload.get("status") != "ok":
            raise RuntimeError("health response payload was unexpected")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        if process.returncode not in (0, 1, -15):
            output = process.stdout.read() if process.stdout is not None else ""
            raise RuntimeError(
                f"application process exited with {process.returncode}: {output}"
            )


def main() -> int:
    _verify_factory()
    _verify_formal_entrypoint()
    print("Runtime smoke passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
