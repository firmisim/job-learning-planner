from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from schemas.development_reset import DevelopmentResetManifest, ResetFile
from src.core_storage import CoreStorage


PRESERVED_FILENAMES = {".gitkeep"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_file(path: Path, project_root: Path) -> str:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(project_root.resolve())
    except ValueError as exc:
        raise ValueError(f"Reset target 超出项目根目录: {path}") from exc
    if not resolved.is_file():
        raise ValueError(f"Reset target 不是普通文件: {path}")
    return relative.as_posix()


def _files_under(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return [
        item
        for item in path.rglob("*")
        if item.is_file() and item.name not in PRESERVED_FILENAMES
    ]


def _payload(manifest: DevelopmentResetManifest) -> dict[str, object]:
    return manifest.model_dump(mode="json", exclude={"reset_id", "generated_at"})


def _reset_id(manifest: DevelopmentResetManifest) -> str:
    encoded = json.dumps(
        _payload(manifest), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"reset-{hashlib.sha256(encoded).hexdigest()[:16]}"


def build_development_reset_manifest(
    project_root: Path,
    *,
    generated_at: datetime,
    state_directory: str = "state",
) -> DevelopmentResetManifest:
    root = project_root.resolve()
    current_state = {
        item.resolve() for item in _files_under(root / state_directory)
    }
    targets = [
        ResetFile(
            path=_relative_file(path, root),
            sha256=_sha256(path),
            classification="NEW_CORE_STATE",
        )
        for path in sorted(current_state, key=lambda item: str(item).casefold())
    ]
    provisional = DevelopmentResetManifest(
        reset_id="reset-0000000000000000",
        generated_at=generated_at,
        delete=targets,
    )
    return provisional.model_copy(update={"reset_id": _reset_id(provisional)})


def validate_development_reset_manifest(
    manifest: DevelopmentResetManifest,
) -> None:
    if manifest.reset_id != _reset_id(manifest):
        raise ValueError("Development Reset manifest ID 与内容不一致")


def manifest_is_current(
    project_root: Path, manifest: DevelopmentResetManifest
) -> bool:
    validate_development_reset_manifest(manifest)
    current = build_development_reset_manifest(
        project_root, generated_at=manifest.generated_at
    )
    return _payload(current) == _payload(manifest)


def write_development_reset_manifest(
    manifest: DevelopmentResetManifest, path: Path
) -> None:
    validate_development_reset_manifest(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )


def load_development_reset_manifest(path: Path) -> DevelopmentResetManifest:
    try:
        manifest = DevelopmentResetManifest.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, ValidationError) as exc:
        raise ValueError(f"Development Reset manifest 无效: {exc}") from exc
    validate_development_reset_manifest(manifest)
    return manifest


def execute_development_reset(
    project_root: Path,
    manifest: DevelopmentResetManifest,
    *,
    state_directory: str = "state",
) -> list[Path]:
    root = project_root.resolve()
    validate_development_reset_manifest(manifest)
    if not manifest_is_current(root, manifest):
        raise ValueError("Development Reset preview 已陈旧，请重新生成")

    targets: list[Path] = []
    for item in manifest.delete:
        target = (root / item.path).resolve()
        _relative_file(target, root)
        if _sha256(target) != item.sha256:
            raise ValueError(f"Development Reset target 已变化: {item.path}")
        targets.append(target)

    deleted: list[Path] = []
    for target in targets:
        target.unlink()
        deleted.append(target)

    CoreStorage(root / state_directory).initialize()
    return deleted
