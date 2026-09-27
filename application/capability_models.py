from __future__ import annotations

from dataclasses import dataclass

from application.market_models import AtomicEvidenceView, SimpleRoleView
from schemas.core import CapabilityKnowledge


@dataclass(frozen=True)
class CapabilityListItemView:
    capability_id: str
    name: str
    atomic_expressions: tuple[str, ...]
    evidence_count: int
    knowledge_status: str | None = None


@dataclass(frozen=True)
class InboxCandidateView:
    candidate_fingerprint: str
    atomic_expression: str
    jd_count: int
    sample_size: int
    evidence: tuple[AtomicEvidenceView, ...]
    recommendation_available: bool = False


@dataclass(frozen=True)
class SkippedCandidateView:
    candidate_fingerprint: str
    atomic_expression: str
    source_present: bool


@dataclass(frozen=True)
class RecommendationView:
    explanation: str
    learning_value: str
    recommended_action: str
    recommended_canonical_name: str | None
    recommended_merge_target: str | None
    recommended_merge_target_id: str | None
    rationale: str
    evidence_quotes: tuple[str, ...]


@dataclass(frozen=True)
class MergeTargetView:
    capability_id: str
    name: str
    historical_expressions: tuple[str, ...]


@dataclass(frozen=True)
class SourceMappingDetailView:
    source_expression: str
    affected_roles: tuple[str, ...]


@dataclass(frozen=True)
class CapabilityWorkspaceView:
    current_role: SimpleRoleView | None
    current_capabilities: tuple[CapabilityListItemView, ...]
    global_capabilities: tuple[CapabilityListItemView, ...]
    pending_candidates: tuple[InboxCandidateView, ...]
    skipped_candidates: tuple[SkippedCandidateView, ...]
    catalog_sha256: str
    skipped_sha256: str | None
    missing_knowledge: tuple[CapabilityListItemView, ...] = ()
    knowledge_batch: KnowledgeBatchView | None = None
    unanalyzed_candidates: tuple[InboxCandidateView, ...] = ()
    analysis_batch: CapabilityAnalysisBatchView | None = None


@dataclass(frozen=True)
class CapabilityInboxView:
    workspace: CapabilityWorkspaceView
    candidate: InboxCandidateView
    position: int
    remaining_count: int
    merge_candidates: tuple[MergeTargetView, ...] = ()
    merge_search_query: str = ""
    merge_search_results: tuple[MergeTargetView, ...] = ()
    recommendation: RecommendationView | None = None
    recommendation_handoff_state: str | None = None
    recommendation_handoff_message: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class CapabilityDetailView:
    current_role: SimpleRoleView
    capability: CapabilityListItemView
    mappings: tuple[SourceMappingDetailView, ...]
    evidence: tuple[AtomicEvidenceView, ...]
    catalog_sha256: str
    knowledge: KnowledgeView
    in_current_role: bool = True
    role_usage: tuple[str, ...] = ()
    current_level: int | None = None
    practice_count: int = 0
    personal_states_sha256: str = ""
    practices_sha256: str = ""
    reassign_expression: str = ""
    reassign_query: str = ""
    reassign_results: tuple[MergeTargetView, ...] = ()


@dataclass(frozen=True)
class KnowledgeView:
    status_key: str
    status_label: str
    summary: str
    value: CapabilityKnowledge | None
    expected_sha256: str | None
    handoff_state: str | None = None
    handoff_message: str | None = None


@dataclass(frozen=True)
class KnowledgeBatchFailureView:
    capability_name: str
    message: str


@dataclass(frozen=True)
class KnowledgeBatchView:
    role_id: str
    role_name: str
    total: int
    succeeded: int
    failed: int
    remaining: int
    batch_size: int
    batches_completed: int
    batch_count: int
    state_key: str
    failures: tuple[KnowledgeBatchFailureView, ...]


@dataclass(frozen=True)
class CapabilityAnalysisBatchFailureView:
    atomic_expression: str
    message: str


@dataclass(frozen=True)
class CapabilityAnalysisBatchView:
    role_id: str
    role_name: str
    total: int
    succeeded: int
    failed: int
    skipped: int
    remaining: int
    batch_size: int
    batches_completed: int
    batch_count: int
    state_key: str
    failures: tuple[CapabilityAnalysisBatchFailureView, ...]
