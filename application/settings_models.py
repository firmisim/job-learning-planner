from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SettingsView:
    role_count: int
    capability_count: int
    knowledge_count: int
    roadmap_count: int
    reset_manifest_json: str | None = None
    reset_id: str | None = None
    reset_targets: tuple[tuple[str, str], ...] = ()

