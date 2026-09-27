from __future__ import annotations

from dataclasses import dataclass

from application.market_models import SimpleRoleView


@dataclass(frozen=True)
class RoadmapDetailView:
    current_role: SimpleRoleView
    roadmap_id: str
    generated_at: str
    latest: bool
    matches_current_inputs: bool
    html: str


@dataclass(frozen=True)
class RoadmapHistoryItemView:
    roadmap_id: str
    generated_at: str
    latest: bool
    matches_current_inputs: bool


@dataclass(frozen=True)
class RoadmapWorkspaceView:
    current_role: SimpleRoleView | None
    state_key: str
    state_label: str
    summary: str
    current_input_fingerprint: str | None
    can_generate: bool
    action_label: str
    blockers: tuple[tuple[str, str], ...]
    history: tuple[RoadmapHistoryItemView, ...]
    handoff_state: str | None = None
    handoff_message: str | None = None
    relevant_capability_count: int = 0
    selected_capability_count: int = 0
    knowledge_ready_count: int = 0
    knowledge_missing_count: int = 0
    retention_limit: int = 30
