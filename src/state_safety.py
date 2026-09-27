from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Iterable


class StaleStateError(RuntimeError):
    """持久化目标已在表单加载后发生变化。"""


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_replace_bytes(
    path: Path,
    content: bytes,
    *,
    expected_sha256: str | None,
) -> str:
    """在同目录验证 stale token 后原子替换一个文件。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    current_sha256 = sha256_file(path)
    if current_sha256 != expected_sha256:
        raise StaleStateError("目标文件已发生变化，请刷新页面后重试")

    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return hashlib.sha256(content).hexdigest()


def atomic_replace_file_set(
    changes: Iterable[tuple[Path, bytes | None, str | None]],
) -> None:
    """Apply one small, prevalidated file set with in-process rollback.

    ``None`` content removes a file. This is intentionally a storage primitive for
    one bounded aggregate mutation, not a workflow or transaction framework.
    """

    prepared = list(changes)
    originals: dict[Path, bytes | None] = {}
    staged: dict[Path, Path] = {}
    try:
        for path, content, expected_sha256 in prepared:
            current_sha256 = sha256_file(path)
            if current_sha256 != expected_sha256:
                raise StaleStateError("目标文件已发生变化，请刷新页面后重试")
            originals[path] = path.read_bytes() if path.is_file() else None
            if content is None:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
            )
            temporary_path = Path(temporary_name)
            try:
                with os.fdopen(handle, "wb") as file:
                    file.write(content)
                    file.flush()
                    os.fsync(file.fileno())
            except Exception:
                if temporary_path.exists():
                    temporary_path.unlink()
                raise
            staged[path] = temporary_path
    except Exception:
        for temporary_path in staged.values():
            if temporary_path.exists():
                temporary_path.unlink()
        raise

    applied: list[Path] = []
    try:
        for path, content, _ in prepared:
            if content is None:
                if path.exists():
                    path.unlink()
            else:
                os.replace(staged[path], path)
            applied.append(path)
    except Exception:
        for path in reversed(applied):
            original = originals[path]
            if original is None:
                if path.exists():
                    path.unlink()
                continue
            handle, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".rollback", dir=path.parent
            )
            rollback_path = Path(temporary_name)
            try:
                with os.fdopen(handle, "wb") as file:
                    file.write(original)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(rollback_path, path)
            finally:
                if rollback_path.exists():
                    rollback_path.unlink()
        raise
    finally:
        for temporary_path in staged.values():
            if temporary_path.exists():
                temporary_path.unlink()
