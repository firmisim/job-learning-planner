"""Build and run the project-local Windows runtime.

This module intentionally uses syntax supported by Python 3.7.  An older Python
may host interpreter discovery, but only a discovered Python 3.11+ interpreter
is allowed to create the project runtime.
"""

from __future__ import annotations, print_function

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence, Tuple


Runner = Callable[..., subprocess.CompletedProcess]
Candidate = Tuple[str, Tuple[str, ...]]
Probe = Dict[str, Any]


MINIMUM_PYTHON = (3, 11)
PROJECT_ROOT = Path(__file__).resolve().parent
VENV_DIRECTORY_NAME = ".venv"
VENV_PYTHON_RELATIVE = Path("Scripts") / "python.exe"
REQUIREMENTS_FILE_NAME = "requirements.txt"
REQUIREMENTS_STAMP_NAME = ".job-learning-planner-requirements.sha256"
REQUIRED_IMPORTS = (
    "fastapi",
    "jinja2",
    "multipart",
    "openpyxl",
    "pydantic",
    "uvicorn",
)


class RuntimeBootstrapError(RuntimeError):
    """An actionable project-runtime failure."""


def version_supported(version: Sequence[int]) -> bool:
    return tuple(version[:2]) >= MINIMUM_PYTHON


def default_bootstrap_candidates(
    current_executable: Optional[str] = None,
) -> Tuple[Candidate, ...]:
    """Return the small, ordered Windows interpreter candidate set."""
    current = str(current_executable or sys.executable)
    python_command = shutil.which("python") or "python"
    py_command = shutil.which("py") or "py"
    return (
        ("current startup Python", (current,)),
        ("python", (python_command,)),
        ("py -3.13", (py_command, "-3.13")),
        ("py -3.12", (py_command, "-3.12")),
        ("py -3.11", (py_command, "-3.11")),
        ("py -3", (py_command, "-3")),
    )


def _run(command: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess:
    return subprocess.run(list(command), **kwargs)


def probe_python(
    command: Sequence[str], runner: Runner = _run
) -> Optional[Probe]:
    """Return actual version/executable facts for one command, or ``None``."""
    probe = (
        "import json,sys; "
        "print(json.dumps({'version': list(sys.version_info[:3]), "
        "'executable': sys.executable}))"
    )
    try:
        result = runner(
            tuple(command) + ("-c", probe),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        version = tuple(int(part) for part in payload["version"])
        executable = str(payload["executable"])
    except (KeyError, TypeError, ValueError, IndexError, json.JSONDecodeError):
        return None
    return {"version": version, "executable": executable}


def discover_bootstrap_python(
    candidates: Optional[Sequence[Candidate]] = None, runner: Runner = _run
) -> Tuple[Optional[Probe], list[Probe]]:
    """Select the first candidate whose *executed* version is Python 3.11+."""
    attempts = []
    seen_executables = set()
    for label, command in candidates or default_bootstrap_candidates():
        info = probe_python(command, runner=runner)
        if info is None:
            attempts.append({"label": label, "status": "unavailable"})
            continue
        actual_key = str(info["executable"]).casefold()
        version_text = ".".join(str(part) for part in info["version"])
        if actual_key in seen_executables:
            continue
        seen_executables.add(actual_key)
        attempt = {
            "label": label,
            "status": "compatible" if version_supported(info["version"]) else "incompatible",
            "version": version_text,
            "executable": info["executable"],
            "command": tuple(command),
        }
        attempts.append(attempt)
        if attempt["status"] == "compatible":
            return attempt, attempts
    return None, attempts


def runtime_paths(
    project_root: Path = PROJECT_ROOT,
) -> Tuple[Path, Path, Path]:
    root = Path(project_root).resolve()
    venv_directory = root / VENV_DIRECTORY_NAME
    return root, venv_directory, venv_directory / VENV_PYTHON_RELATIVE


def _requirements_digest(requirements_path: Path) -> str:
    return hashlib.sha256(Path(requirements_path).read_bytes()).hexdigest()


def dependencies_available(runtime_python: Path, runner: Runner = _run) -> bool:
    imports = "; ".join("import " + name for name in REQUIRED_IMPORTS)
    try:
        result = runner(
            (str(runtime_python), "-c", imports),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def validate_runtime(runtime_python: Path, runner: Runner = _run) -> Probe:
    info = probe_python((str(runtime_python),), runner=runner)
    if info is None:
        raise RuntimeBootstrapError(
            "Runtime Environment invalid: the project Python could not be executed. "
            "Run rebuild_job_learning_planner_runtime.bat."
        )
    if not version_supported(info["version"]):
        version_text = ".".join(str(part) for part in info["version"])
        raise RuntimeBootstrapError(
            "Runtime Environment invalid: project Python %s is unsupported; Python 3.11 or newer is required. "
            "Run rebuild_job_learning_planner_runtime.bat."
            % version_text
        )
    return info


def create_runtime(
    project_root: Path, bootstrap: Probe, runner: Runner = _run
) -> Path:
    root, venv_directory, runtime_python = runtime_paths(project_root)
    print("Creating local project environment...")
    result = runner(
        tuple(bootstrap["command"]) + ("-m", "venv", str(venv_directory)),
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not runtime_python.is_file():
        details = (result.stderr or result.stdout or "No diagnostic output.").strip()
        raise RuntimeBootstrapError(
            "Could not create the project environment at %s. Bootstrap interpreter: %s. %s"
            % (venv_directory, bootstrap["executable"], details)
        )
    return runtime_python


def install_dependencies(
    project_root: Path, runtime_python: Path, runner: Runner = _run
) -> None:
    root, venv_directory, _ = runtime_paths(project_root)
    requirements = root / REQUIREMENTS_FILE_NAME
    print("Installing project dependencies...")
    result = runner(
        (
            str(runtime_python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            "-r",
            str(requirements),
        ),
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "No diagnostic output.").strip()
        if len(details) > 2000:
            details = details[-2000:]
        raise RuntimeBootstrapError(
            "Dependency installation failed for %s using %s. %s\n"
            "Next step: check network/package access, then run the Runtime Environment Rebuild entry."
            % (venv_directory, runtime_python, details)
        )
    stamp = venv_directory / REQUIREMENTS_STAMP_NAME
    stamp.write_text(_requirements_digest(requirements) + "\n", encoding="ascii")


def _dependencies_current(
    project_root: Path, runtime_python: Path, runner: Runner = _run
) -> bool:
    root, venv_directory, _ = runtime_paths(project_root)
    requirements = root / REQUIREMENTS_FILE_NAME
    stamp = venv_directory / REQUIREMENTS_STAMP_NAME
    try:
        recorded = stamp.read_text(encoding="ascii").strip()
    except OSError:
        return False
    return recorded == _requirements_digest(requirements) and dependencies_available(
        runtime_python, runner=runner
    )


def remove_runtime_environment(project_root: Path) -> None:
    """Remove exactly the project-local .venv and nothing else."""
    root, venv_directory, _ = runtime_paths(project_root)
    resolved = venv_directory.resolve()
    if resolved.parent != root or resolved.name != VENV_DIRECTORY_NAME:
        raise RuntimeBootstrapError("Refusing to rebuild an unexpected runtime path.")
    if resolved.exists():
        shutil.rmtree(str(resolved))


def ensure_project_runtime(
    project_root: Path = PROJECT_ROOT,
    rebuild: bool = False,
    runner: Runner = _run,
) -> Path:
    root, venv_directory, runtime_python = runtime_paths(project_root)
    if rebuild:
        selected, attempts = discover_bootstrap_python(runner=runner)
        if selected is None:
            raise RuntimeBootstrapError(_missing_python_message(attempts))
        remove_runtime_environment(root)
        print("Checking Python runtime...")
        print("Compatible Python found: %s" % selected["version"])
        runtime_python = create_runtime(root, selected, runner=runner)
    elif venv_directory.exists():
        if not runtime_python.is_file():
            raise RuntimeBootstrapError(
                "Runtime Environment invalid: %s is missing.\n"
                "Next step: run rebuild_job_learning_planner_runtime.bat. "
                "Runtime rebuild replaces only .venv and does not touch user data."
                % runtime_python
            )
    else:
        print("Checking Python runtime...")
        selected, attempts = discover_bootstrap_python(runner=runner)
        if selected is None:
            raise RuntimeBootstrapError(_missing_python_message(attempts))
        print("Compatible Python found: %s" % selected["version"])
        runtime_python = create_runtime(root, selected, runner=runner)

    validate_runtime(runtime_python, runner=runner)
    if not _dependencies_current(root, runtime_python, runner=runner):
        install_dependencies(root, runtime_python, runner=runner)
        if not dependencies_available(runtime_python, runner=runner):
            raise RuntimeBootstrapError(
                "Dependency validation failed in %s after installation. "
                "Run rebuild_job_learning_planner_runtime.bat."
                % venv_directory
            )
    print("Environment ready.")
    return runtime_python


def _missing_python_message(attempts: Sequence[Probe]) -> str:
    incompatible = [
        "%s (%s)" % (item["label"], item["version"])
        for item in attempts
        if item["status"] == "incompatible"
    ]
    detected = ", ".join(incompatible) if incompatible else "none"
    return (
        "No compatible Bootstrap Python was found. Job Learning Planner requires Python 3.11 or newer. "
        "Incompatible versions detected: %s. Install a compatible Python, then start again; "
        "the project will not download Python or change PATH." % detected
    )


def launch_application(
    project_root: Path, runtime_python: Path, runner: Runner = _run
) -> int:
    print("Starting Job Learning Planner...")
    result = runner(
        (str(runtime_python), "-m", "ui.launcher"),
        cwd=str(Path(project_root).resolve()),
    )
    return result.returncode


def run(
    project_root: Path = PROJECT_ROOT,
    rebuild: bool = False,
    runner: Runner = _run,
) -> int:
    try:
        runtime_python = ensure_project_runtime(
            project_root=project_root, rebuild=rebuild, runner=runner
        )
        return launch_application(project_root, runtime_python, runner=runner)
    except RuntimeBootstrapError as exc:
        print("\nJob Learning Planner could not start.")
        print(str(exc))
        return 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare the local project runtime.")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="replace only the project-local .venv before starting",
    )
    args = parser.parse_args(argv)
    return run(rebuild=args.rebuild)


if __name__ == "__main__":
    raise SystemExit(main())
