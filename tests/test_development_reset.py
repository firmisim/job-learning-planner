from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from src.core_storage import CoreStorage
from src.development_reset import (
    build_development_reset_manifest,
    execute_development_reset,
)


NOW = datetime.fromisoformat("2026-09-10T12:00:00+08:00")


def _write(path: Path, content: str = "fixture\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_full_development_reset_is_bounded_and_initializes_new_storage(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "README.md", "preserved source\n")
    _write(tmp_path / ".git" / "HEAD", "preserved\n")
    _write(tmp_path / ".venv" / "marker", "preserved\n")
    _write(tmp_path / "examples" / "jobs.example.xlsx")
    _write(tmp_path / "state" / ".gitkeep", "")
    _write(tmp_path / "state" / "generated-state.json")

    store = CoreStorage(tmp_path / "state")
    store.initialize()
    role = store.create_role("Scoped Role")
    capability = store.create_capability("Scoped Capability")
    store.set_roadmap_scope_inclusion(
        role.role_id, capability.capability_id, False, expected_sha256=None
    )
    scope_path = (
        f"state/roles/{role.role_id}/roadmap_scope.json"
    )

    manifest = build_development_reset_manifest(tmp_path, generated_at=NOW)
    targets = {item.path for item in manifest.delete}

    assert "state/generated-state.json" in targets
    assert scope_path in targets
    assert "README.md" not in targets
    assert ".git/HEAD" not in targets
    assert ".venv/marker" not in targets
    assert "examples/jobs.example.xlsx" not in targets
    assert "state/.gitkeep" not in targets
    assert {item.classification for item in manifest.delete} == {"NEW_CORE_STATE"}

    deleted = execute_development_reset(tmp_path, manifest)

    assert {path.relative_to(tmp_path).as_posix() for path in deleted} == targets
    assert (tmp_path / "README.md").exists()
    assert (tmp_path / ".git" / "HEAD").exists()
    assert (tmp_path / ".venv" / "marker").exists()
    assert (tmp_path / "examples" / "jobs.example.xlsx").exists()
    assert (tmp_path / "state" / ".gitkeep").exists()
    store = CoreStorage(tmp_path / "state")
    assert store.load_roles().roles == []
    assert store.load_catalog().capabilities == []
    assert store.load_personal_states().states == []
    assert store.load_practices().practices == []
    assert not list((tmp_path / "state" / "roles").rglob("*.json"))
    assert not (tmp_path / scope_path).exists()


def test_development_reset_rejects_changed_target(tmp_path: Path) -> None:
    target = tmp_path / "state" / "roles.json"
    _write(target, "before\n")
    manifest = build_development_reset_manifest(tmp_path, generated_at=NOW)
    target.write_text("after\n", encoding="utf-8")

    with pytest.raises(ValueError, match="已陈旧"):
        execute_development_reset(tmp_path, manifest)
    assert target.read_text(encoding="utf-8") == "after\n"
