from __future__ import annotations

import importlib
import sys
from pathlib import Path

from fastapi import FastAPI

from src.core_storage import CoreStorage


def test_importing_ui_app_does_not_initialize_default_storage(monkeypatch) -> None:
    initialized_roots: list[Path] = []

    def observe_initialize(storage: CoreStorage) -> None:
        initialized_roots.append(storage.root)

    monkeypatch.setattr(CoreStorage, "initialize", observe_initialize)
    sys.modules.pop("ui.app", None)

    module = importlib.import_module("ui.app")

    assert initialized_roots == []
    assert not hasattr(module, "app")
    assert callable(module.create_app)


def test_factory_constructs_application_with_explicit_isolated_storage(
    tmp_path: Path,
) -> None:
    from ui.app import create_app

    storage_root = tmp_path / "state"
    app = create_app(storage_root)

    assert isinstance(app, FastAPI)
    assert app.state.market.storage.root == storage_root.resolve()
    assert (storage_root / "roles.json").is_file()


def test_python_module_entrypoint_uses_application_factory(monkeypatch) -> None:
    from ui import __main__ as entrypoint

    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def observe_run(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(entrypoint.uvicorn, "run", observe_run)

    entrypoint.main(["--port", "8765"])

    assert calls == [
        (
            ("ui.app:create_app",),
            {
                "host": "127.0.0.1",
                "port": 8765,
                "reload": False,
                "factory": True,
            },
        )
    ]


def test_windows_launcher_uses_application_factory_without_import_side_effects(
    monkeypatch,
) -> None:
    import uvicorn

    from ui import launcher

    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    class NoopThread:
        def start(self) -> None:
            pass

    monkeypatch.setattr(launcher, "missing_dependencies", lambda: ())
    monkeypatch.setattr(launcher, "port_available", lambda: True)
    monkeypatch.setattr(launcher, "validate_project", lambda: None)
    monkeypatch.setattr(launcher.threading, "Thread", lambda **_kwargs: NoopThread())
    monkeypatch.setattr(
        uvicorn,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert launcher.run() == 0
    assert calls == [
        (
            ("ui.app:create_app",),
            {
                "host": launcher.HOST,
                "port": launcher.PORT,
                "reload": False,
                "factory": True,
            },
        )
    ]
