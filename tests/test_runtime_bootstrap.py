from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

import runtime_bootstrap as bootstrap
from ui import launcher


def completed(args: tuple[str, ...], returncode: int = 0, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(args, returncode, stdout, stderr)


def discovery_runner(versions: dict[tuple[str, ...], tuple[tuple[int, ...], str]]):
    def run(command, **_kwargs):
        args = tuple(str(part) for part in command)
        prefix = args[:-2]
        if prefix not in versions:
            raise FileNotFoundError(prefix[0])
        version, executable = versions[prefix]
        payload = json.dumps({"version": list(version), "executable": executable})
        return completed(args, stdout=payload + "\n")

    return run


def test_discovery_does_not_blindly_prefer_py_3_over_compatible_python() -> None:
    candidates = (("py -3", ("py", "-3")), ("python", ("python",)))
    selected, attempts = bootstrap.discover_bootstrap_python(
        candidates,
        runner=discovery_runner(
            {
                ("py", "-3"): ((3, 7, 4), r"C:\Program Files\Python37\python.exe"),
                ("python",): ((3, 12, 4), r"D:\anaconda\python.exe"),
            }
        ),
    )

    assert selected is not None
    assert selected["label"] == "python"
    assert selected["version"] == "3.12.4"
    assert attempts[0]["status"] == "incompatible"


def test_discovery_rejects_only_incompatible_python() -> None:
    selected, attempts = bootstrap.discover_bootstrap_python(
        (("py -3", ("py", "-3")),),
        runner=discovery_runner({("py", "-3"): ((3, 7, 4), "python37.exe")}),
    )

    assert selected is None
    assert attempts == [
        {
            "label": "py -3",
            "status": "incompatible",
            "version": "3.7.4",
            "executable": "python37.exe",
            "command": ("py", "-3"),
        }
    ]
    assert "Python 3.11 or newer" in bootstrap._missing_python_message(attempts)


def test_discovery_uses_first_of_multiple_compatible_candidates() -> None:
    candidates = (("python", ("python",)), ("py -3.12", ("py", "-3.12")))
    selected, _ = bootstrap.discover_bootstrap_python(
        candidates,
        runner=discovery_runner(
            {
                ("python",): ((3, 11, 9), "python311.exe"),
                ("py", "-3.12"): ((3, 12, 4), "python312.exe"),
            }
        ),
    )

    assert selected is not None
    assert selected["executable"] == "python311.exe"


def test_discovery_records_unavailable_candidates() -> None:
    selected, attempts = bootstrap.discover_bootstrap_python(
        (("python", ("python",)),), runner=discovery_runner({})
    )

    assert selected is None
    assert attempts == [{"label": "python", "status": "unavailable"}]


def test_default_candidates_resolve_windows_commands_before_probing(monkeypatch) -> None:
    paths = {
        "python": r"D:\anaconda\python.exe",
        "py": r"C:\Windows\py.exe",
    }
    monkeypatch.setattr(bootstrap.shutil, "which", lambda name: paths[name])

    candidates = bootstrap.default_bootstrap_candidates("python37.exe")

    assert candidates[1] == ("python", (r"D:\anaconda\python.exe",))
    assert candidates[-1] == ("py -3", (r"C:\Windows\py.exe", "-3"))


class RuntimeRunner:
    def __init__(
        self,
        root: Path,
        *,
        runtime_version: tuple[int, ...] = (3, 12, 4),
        dependencies: bool = True,
        install_returncode: int = 0,
    ) -> None:
        self.root = root
        self.runtime = root / ".venv" / "Scripts" / "python.exe"
        self.runtime_version = runtime_version
        self.dependencies = dependencies
        self.install_returncode = install_returncode
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, command, **_kwargs):
        args = tuple(str(part) for part in command)
        self.commands.append(args)
        if len(args) >= 3 and args[-2] == "-c" and "json.dumps" in args[-1]:
            executable = args[0]
            version = (
                self.runtime_version if Path(executable) == self.runtime else (3, 12, 4)
            )
            return completed(
                args,
                stdout=json.dumps(
                    {"version": list(version), "executable": executable}
                )
                + "\n",
            )
        if "-m" in args and "venv" in args:
            self.runtime.parent.mkdir(parents=True, exist_ok=True)
            self.runtime.touch()
            return completed(args)
        if "-m" in args and "pip" in args:
            if self.install_returncode == 0:
                self.dependencies = True
            return completed(
                args,
                returncode=self.install_returncode,
                stderr="simulated package failure" if self.install_returncode else "",
            )
        if len(args) >= 3 and args[1] == "-c":
            return completed(args, returncode=0 if self.dependencies else 1)
        if args[-2:] == ("-m", "ui.launcher"):
            return completed(args)
        raise AssertionError(f"Unexpected command: {args}")


def workspace(tmp_path: Path) -> Path:
    (tmp_path / "requirements.txt").write_text("fastapi>=0.115,<1.0\n", encoding="utf-8")
    return tmp_path


def test_runtime_dependency_contract_excludes_dev_and_legacy_packages() -> None:
    requirements = {
        line.split(">=", 1)[0].casefold()
        for line in Path("requirements.txt").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("-")
    }
    dev_requirements = Path("requirements-dev.txt").read_text(encoding="utf-8")

    assert requirements == {
        "fastapi",
        "jinja2",
        "openpyxl",
        "pydantic",
        "python-multipart",
        "uvicorn",
    }
    assert set(bootstrap.REQUIRED_IMPORTS) == set(launcher.REQUIRED_MODULES)
    assert not {"pandas", "yaml", "httpx", "httpx2", "pytest"} & set(
        bootstrap.REQUIRED_IMPORTS
    )
    assert dev_requirements.splitlines()[0] == "-r requirements.txt"
    assert "httpx" in dev_requirements
    assert "pytest" in dev_requirements


def mark_dependencies_current(root: Path) -> None:
    requirements = root / "requirements.txt"
    stamp = root / ".venv" / bootstrap.REQUIREMENTS_STAMP_NAME
    stamp.write_text(hashlib.sha256(requirements.read_bytes()).hexdigest() + "\n", encoding="ascii")


def test_missing_venv_is_created_and_dependencies_use_project_python(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    runner = RuntimeRunner(root, dependencies=False)

    runtime = bootstrap.ensure_project_runtime(root, runner=runner)

    assert runtime == root / ".venv" / "Scripts" / "python.exe"
    create = next(command for command in runner.commands if "venv" in command)
    install = next(command for command in runner.commands if "pip" in command)
    assert create[0] == sys.executable
    assert install[0] == str(runtime)


def test_valid_venv_is_used_without_creation_or_install(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    runner = RuntimeRunner(root)
    runner.runtime.parent.mkdir(parents=True)
    runner.runtime.touch()
    mark_dependencies_current(root)

    assert bootstrap.ensure_project_runtime(root, runner=runner) == runner.runtime
    assert not any("venv" in command for command in runner.commands)
    assert not any("pip" in command for command in runner.commands)


def test_existing_venv_with_missing_python_fails_with_rebuild_path(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    (root / ".venv").mkdir()

    with pytest.raises(bootstrap.RuntimeBootstrapError, match="Runtime Environment invalid") as error:
        bootstrap.ensure_project_runtime(root, runner=RuntimeRunner(root))

    assert "rebuild_job_learning_planner_runtime.bat" in str(error.value)


def test_unsupported_venv_python_is_invalid(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    runner = RuntimeRunner(root, runtime_version=(3, 10, 14))
    runner.runtime.parent.mkdir(parents=True)
    runner.runtime.touch()

    with pytest.raises(bootstrap.RuntimeBootstrapError, match="3.10.14"):
        bootstrap.ensure_project_runtime(root, runner=runner)


def test_unexecutable_venv_python_fails_with_rebuild_path(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    runtime = root / ".venv" / "Scripts" / "python.exe"
    runtime.parent.mkdir(parents=True)
    runtime.touch()

    def unavailable(_command, **_kwargs):
        raise OSError("damaged executable")

    with pytest.raises(bootstrap.RuntimeBootstrapError, match="could not be executed") as error:
        bootstrap.ensure_project_runtime(root, runner=unavailable)

    assert "rebuild_job_learning_planner_runtime.bat" in str(error.value)


def test_system_packages_do_not_satisfy_project_runtime_dependencies(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    runner = RuntimeRunner(root, dependencies=False)
    runner.runtime.parent.mkdir(parents=True)
    runner.runtime.touch()

    bootstrap.ensure_project_runtime(root, runner=runner)

    dependency_checks = [
        command
        for command in runner.commands
        if len(command) >= 3 and command[1] == "-c" and "json.dumps" not in command[-1]
    ]
    assert dependency_checks
    assert all(command[0] == str(runner.runtime) for command in dependency_checks)
    assert any(command[0] == str(runner.runtime) and "pip" in command for command in runner.commands)


def test_dependency_install_failure_names_project_interpreter(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    runner = RuntimeRunner(root, dependencies=False, install_returncode=1)
    runner.runtime.parent.mkdir(parents=True)
    runner.runtime.touch()

    with pytest.raises(bootstrap.RuntimeBootstrapError, match="Dependency installation failed") as error:
        bootstrap.ensure_project_runtime(root, runner=runner)

    message = str(error.value)
    assert str(runner.runtime) in message
    assert "python -m pip" not in message
    assert "Runtime Environment Rebuild" in message


def test_install_and_launch_use_the_same_project_interpreter(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    runner = RuntimeRunner(root, dependencies=False)
    runner.runtime.parent.mkdir(parents=True)
    runner.runtime.touch()

    assert bootstrap.run(root, runner=runner) == 0

    install = next(command for command in runner.commands if "pip" in command)
    launch = next(command for command in runner.commands if command[-2:] == ("-m", "ui.launcher"))
    assert install[0] == launch[0] == str(runner.runtime)


def test_runtime_rebuild_removes_only_venv(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    protected = [
        root / "state" / "roles.json",
        root / "state" / "knowledge" / "capability.json",
        root / "state" / "roles" / "role" / "roadmaps" / "roadmap.json",
        root / "examples" / "jobs.example.xlsx",
    ]
    for path in protected:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("preserve", encoding="utf-8")
    runtime_file = root / ".venv" / "marker.txt"
    runtime_file.parent.mkdir()
    runtime_file.write_text("remove", encoding="utf-8")

    bootstrap.remove_runtime_environment(root)

    assert not (root / ".venv").exists()
    assert all(path.read_text(encoding="utf-8") == "preserve" for path in protected)


def test_confirmed_runtime_rebuild_recreates_only_venv(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    user_data = root / "state" / "practices.json"
    user_data.parent.mkdir(parents=True)
    user_data.write_text("preserve", encoding="utf-8")
    damaged = root / ".venv" / "damaged.txt"
    damaged.parent.mkdir()
    damaged.write_text("replace", encoding="utf-8")
    runner = RuntimeRunner(root, dependencies=False)

    runtime = bootstrap.ensure_project_runtime(root, rebuild=True, runner=runner)

    assert runtime.is_file()
    assert not damaged.exists()
    assert user_data.read_text(encoding="utf-8") == "preserve"
    assert any("venv" in command for command in runner.commands)
    assert any("pip" in command for command in runner.commands)


def test_runtime_rebuild_entry_requires_explicit_confirmation() -> None:
    content = Path("rebuild_job_learning_planner_runtime.bat").read_text(encoding="utf-8")

    assert "Type REBUILD to continue" in content
    assert "--rebuild" in content
    assert "does not modify" in content


def test_runtime_is_repository_local_and_ignored() -> None:
    ignore = Path(".gitignore").read_text(encoding="utf-8")
    start = Path("start_job_learning_planner.bat").read_text(encoding="utf-8")

    assert ".venv/" in ignore
    assert '.venv\\Scripts\\python.exe' in start
    assert "could not be executed" in start
    assert "activate" not in start.casefold()
