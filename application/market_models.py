from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SimpleRoleView:
    role_id: str
    name: str
    current: bool


@dataclass(frozen=True)
class SourceJDView:
    job_id: str
    title: str
    company: str | None
    jd_text: str
    source_url: str | None
    analysis_current: bool


@dataclass(frozen=True)
class AtomicEvidenceView:
    job_id: str
    job_title: str
    source_expression: str
    evidence: str


@dataclass(frozen=True)
class AtomicSignalView:
    atomic_expression: str
    jd_count: int
    sample_size: int
    evidence: tuple[AtomicEvidenceView, ...]


@dataclass(frozen=True)
class StageBMarketView:
    roles: tuple[SimpleRoleView, ...]
    current_role: SimpleRoleView | None
    jobs: tuple[SourceJDView, ...]
    signals: tuple[AtomicSignalView, ...]
    jd_count: int
    sample_size: int
    current_analysis_count: int
    pending_analysis_count: int
    roles_sha256: str
    jds_sha256: str | None
    analyses_sha256: str | None
    analysis_handoff_state: str | None
    analysis_handoff_message: str | None
