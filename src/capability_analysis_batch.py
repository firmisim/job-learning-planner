from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from schemas.capability_recommendation import CapabilityRecommendation
from src.state_safety import atomic_replace_bytes, sha256_file


CAPABILITY_ANALYSIS_BATCH_SIZE = 20


class CapabilityAnalysisBatchStore:
    """Replaceable execution coordination for batched Capability Analysis."""

    def __init__(self, storage_root: Path) -> None:
        self.root = storage_root.resolve() / "handoffs" / "capability-analysis"
        self.manifest_path = self.root / "batch_manifest.json"
        self.recommendations_path = self.root / "recommendations.json"

    @staticmethod
    def _read(path: Path, label: str) -> tuple[dict[str, Any] | None, str | None]:
        fingerprint = sha256_file(path)
        if fingerprint is None:
            return None, None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"{label} is invalid") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{label} is invalid")
        return value, fingerprint

    @staticmethod
    def _write(
        path: Path, payload: dict[str, Any], *, expected_sha256: str | None
    ) -> None:
        encoded = (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        atomic_replace_bytes(path, encoded, expected_sha256=expected_sha256)

    def load_manifest(self) -> tuple[dict[str, Any] | None, str | None]:
        value, fingerprint = self._read(
            self.manifest_path, "Capability Analysis batch manifest"
        )
        if value is not None and value.get("manifest_version") != "1.0":
            raise ValueError("Capability Analysis batch manifest is invalid")
        return value, fingerprint

    def prepare(
        self,
        *,
        role_id: str,
        role_name: str,
        candidates: list[dict[str, str]],
    ) -> dict[str, Any]:
        if not candidates:
            raise ValueError("Capability Analysis batch cannot be empty")
        fingerprints = [item["candidate_fingerprint"] for item in candidates]
        batches = [
            fingerprints[index : index + CAPABILITY_ANALYSIS_BATCH_SIZE]
            for index in range(0, len(fingerprints), CAPABILITY_ANALYSIS_BATCH_SIZE)
        ]
        manifest: dict[str, Any] = {
            "manifest_version": "1.0",
            "manifest_id": str(uuid4()),
            "prepared_at": datetime.now().astimezone().isoformat(),
            "role": {"role_id": role_id, "name": role_name},
            "batch_size": CAPABILITY_ANALYSIS_BATCH_SIZE,
            "selected": candidates,
            "batches": batches,
            "next_batch_index": 0,
            "completed_candidate_fingerprints": [],
            "skipped_candidate_fingerprints": [],
            "failed_items": {},
        }
        _, expected = self.load_manifest()
        self._write(self.manifest_path, manifest, expected_sha256=expected)
        return manifest

    def replace_manifest(
        self, manifest: dict[str, Any], *, expected_sha256: str | None
    ) -> None:
        self._write(self.manifest_path, manifest, expected_sha256=expected_sha256)

    def load_recommendations(self) -> dict[str, dict[str, Any]]:
        value, _ = self._read(
            self.recommendations_path, "Capability recommendations"
        )
        if value is None:
            return {}
        if value.get("cache_version") != "1.0" or not isinstance(
            value.get("recommendations"), dict
        ):
            raise ValueError("Capability recommendations are invalid")
        valid: dict[str, dict[str, Any]] = {}
        for fingerprint, payload in value["recommendations"].items():
            if not isinstance(fingerprint, str) or not isinstance(payload, dict):
                continue
            try:
                recommendation = CapabilityRecommendation.model_validate(payload)
            except ValueError:
                continue
            if recommendation.candidate_fingerprint == fingerprint:
                valid[fingerprint] = recommendation.model_dump(mode="json")
        return valid

    def save_recommendation(self, recommendation: CapabilityRecommendation) -> None:
        value, expected = self._read(
            self.recommendations_path, "Capability recommendations"
        )
        if value is None:
            value = {"cache_version": "1.0", "recommendations": {}}
        if value.get("cache_version") != "1.0" or not isinstance(
            value.get("recommendations"), dict
        ):
            raise ValueError("Capability recommendations are invalid")
        value["recommendations"][recommendation.candidate_fingerprint] = (
            recommendation.model_dump(mode="json")
        )
        self._write(self.recommendations_path, value, expected_sha256=expected)
