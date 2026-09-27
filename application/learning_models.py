from __future__ import annotations

from dataclasses import dataclass

from application.market_models import SimpleRoleView


@dataclass(frozen=True)
class PracticeView:
    practice_id: str
    description: str


@dataclass(frozen=True)
class LearningCapabilityView:
    capability_id: str
    name: str
    current_level: int | None
    practices: tuple[PracticeView, ...]
    knowledge_status: str | None
    included_in_roadmap: bool


@dataclass(frozen=True)
class MyLearningView:
    current_role: SimpleRoleView | None
    capabilities: tuple[LearningCapabilityView, ...]
    personal_states_sha256: str
    practices_sha256: str
    roadmap_scope_sha256: str | None


@dataclass(frozen=True)
class LevelCriterionView:
    level: int
    text: str


@dataclass(frozen=True)
class LearningDetailView:
    current_role: SimpleRoleView
    capability: LearningCapabilityView
    criteria_source: str
    level_criteria: tuple[LevelCriterionView, ...]
    prerequisites: tuple[str, ...]
    core_topics: tuple[str, ...]
    useful_practices: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    knowledge_status: str | None
    personal_states_sha256: str
    practices_sha256: str
    roadmap_scope_sha256: str | None
