from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.state_safety import atomic_replace_bytes, sha256_file


KNOWLEDGE_BATCH_SIZE = 4


class KnowledgeBatchStore:
    """Replaceable execution manifest for current Knowledge batch research."""

    def __init__(self, storage_root: Path) -> None:
        self.path = (
            storage_root.resolve()
            / "handoffs"
            / "capability-knowledge-research"
            / "batch_manifest.json"
        )

    def load_snapshot(self) -> tuple[dict[str, Any] | None, str | None]:
        fingerprint = sha256_file(self.path)
        if fingerprint is None:
            return None, None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Knowledge batch manifest is invalid") from exc
        if not isinstance(value, dict) or value.get("manifest_version") != "1.0":
            raise ValueError("Knowledge batch manifest is invalid")
        return value, fingerprint

    def prepare(
        self,
        *,
        role_id: str,
        role_name: str,
        capabilities: list[dict[str, str]],
    ) -> dict[str, Any]:
        if not capabilities:
            raise ValueError("Knowledge batch cannot be empty")
        capability_ids = [item["capability_id"] for item in capabilities]
        batches = [
            capability_ids[index : index + KNOWLEDGE_BATCH_SIZE]
            for index in range(0, len(capability_ids), KNOWLEDGE_BATCH_SIZE)
        ]
        manifest: dict[str, Any] = {
            "manifest_version": "1.0",
            "manifest_id": str(uuid4()),
            "prepared_at": datetime.now().astimezone().isoformat(),
            "role": {"role_id": role_id, "name": role_name},
            "batch_size": KNOWLEDGE_BATCH_SIZE,
            "selected": capabilities,
            "batches": batches,
            "next_batch_index": 0,
            "completed_capability_ids": [],
            "failed_items": {},
        }
        _, expected = self.load_snapshot()
        self._write(manifest, expected_sha256=expected)
        return manifest

    def replace(
        self, manifest: dict[str, Any], *, expected_sha256: str | None
    ) -> None:
        self._write(manifest, expected_sha256=expected_sha256)

    def _write(
        self, manifest: dict[str, Any], *, expected_sha256: str | None
    ) -> None:
        encoded = (
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        atomic_replace_bytes(
            self.path,
            encoded,
            expected_sha256=expected_sha256,
        )
