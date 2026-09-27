from __future__ import annotations

import importlib.util
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path


HOST = "127.0.0.1"
PORT = 8080
PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = PROJECT_ROOT / "state"
URL = f"http://{HOST}:{PORT}/"
REQUIRED_MODULES = {
    "fastapi": "fastapi",
    "jinja2": "Jinja2",
    "multipart": "python-multipart",
    "openpyxl": "openpyxl",
    "pydantic": "pydantic",
    "uvicorn": "uvicorn",
}


class StartupError(RuntimeError):
    """A concise startup failure intended for the local console."""


def missing_dependencies() -> tuple[str, ...]:
    return tuple(
        package
        for module, package in REQUIRED_MODULES.items()
        if importlib.util.find_spec(module) is None
    )


def port_available(host: str = HOST, port: int = PORT) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((host, port))
    except OSError:
        return False
    return True


def validate_project(state_root: Path = STATE_ROOT) -> None:
    try:
        from src.core_storage import CoreStorage

        storage = CoreStorage(state_root)
        storage.initialize()
        storage.load_roles()
        storage.load_catalog()
        storage.load_personal_states()
        storage.load_practices()
    except Exception as exc:
        raise StartupError(
            f"Project validation could not complete ({type(exc).__name__}: {exc})."
        ) from exc


def open_browser_when_ready(url: str = URL) -> None:
    for _ in range(40):
        try:
            with urllib.request.urlopen(f"{url}health", timeout=0.25) as response:
                if response.status == 200:
                    try:
                        webbrowser.get().open_new_tab(url)
                    except webbrowser.Error:
                        # The URL is already printed; a missing default browser
                        # must not terminate an otherwise healthy local server.
                        pass
                    return
        except OSError:
            time.sleep(0.25)


def run() -> int:
    missing = missing_dependencies()
    if missing:
        print("\nJob Learning Planner could not start.")
        print("Missing dependencies: " + ", ".join(missing))
        print(
            "The project runtime is incomplete. Close this window and run "
            "rebuild_job_learning_planner_runtime.bat."
        )
        return 1
    if not port_available():
        print("\nJob Learning Planner could not start.")
        print(f"Local port {PORT} is already in use.")
        print("Next step: close the other app or existing Planner window, then start again.")
        return 1
    try:
        validate_project()
    except StartupError as exc:
        print("\nJob Learning Planner could not start safely.")
        print(str(exc))
        print("Next step: review the project state or use the documented recovery workflow.")
        return 1

    import uvicorn

    print("\nJob Learning Planner")
    print(f"Opening {URL}")
    print("Keep this window open while using the app. Press Ctrl+C to stop.")
    opener = threading.Thread(target=open_browser_when_ready, daemon=True)
    opener.start()
    try:
        uvicorn.run(
            "ui.app:create_app",
            host=HOST,
            port=PORT,
            reload=False,
            factory=True,
        )
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f"Server startup failed ({type(exc).__name__}: {exc}).")
        print("Next step: close this window and start the Planner again.")
        return 1
    print("Job Learning Planner stopped.")
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
