from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)


NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


def new_id() -> UUID:
    """Generate an opaque identity that is never derived from mutable semantics."""

    return uuid4()


def normalize_source_expression(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.strip()).casefold()
    if not normalized:
        raise ValueError("source expression 不能为空")
    return normalized


def _timezone_required(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("时间必须包含时区")
    return value


class CoreModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Role(CoreModel):
    role_id: UUID = Field(default_factory=new_id)
    name: NonEmptyText


class JD(CoreModel):
    job_id: UUID = Field(default_factory=new_id)
    role_id: UUID
    title: NonEmptyText
    company: NonEmptyText | None = None
    jd_text: NonEmptyText
    source_url: AnyHttpUrl | None = None


class AtomicMarketSignal(CoreModel):
    source_expression: NonEmptyText
    atomic_expression: NonEmptyText
    evidence: NonEmptyText

    @model_validator(mode="after")
    def source_must_be_in_evidence(self) -> AtomicMarketSignal:
        if self.source_expression not in self.evidence:
            raise ValueError("source_expression 必须是 evidence 中的原文片段")
        return self


class JDAnalysis(CoreModel):
    job_id: UUID
    role_id: UUID
    source_fingerprint: Sha256
    signals: list[AtomicMarketSignal] = Field(default_factory=list)


class Capability(CoreModel):
    capability_id: UUID = Field(default_factory=new_id)
    name: NonEmptyText


class SourceMapping(CoreModel):
    source_expression: NonEmptyText
    normalized_expression: NonEmptyText
    capability_id: UUID

    @model_validator(mode="after")
    def normalized_key_matches_expression(self) -> SourceMapping:
        expected = normalize_source_expression(self.source_expression)
        if self.normalized_expression != expected:
            raise ValueError("normalized_expression 与 source_expression 不一致")
        return self

    @classmethod
    def create(cls, source_expression: str, capability_id: UUID) -> SourceMapping:
        return cls(
            source_expression=source_expression,
            normalized_expression=normalize_source_expression(source_expression),
            capability_id=capability_id,
        )


class SkippedCandidate(CoreModel):
    role_id: UUID
    candidate_fingerprint: Sha256
    atomic_expression: NonEmptyText


class KnowledgeSource(CoreModel):
    source_id: UUID = Field(default_factory=new_id)
    title: NonEmptyText
    url: AnyHttpUrl


class KnowledgeItem(CoreModel):
    text: NonEmptyText
    source_ids: list[UUID] = Field(min_length=1)

    @field_validator("source_ids")
    @classmethod
    def source_ids_are_unique(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("source_ids 不能重复")
        return value


class CapabilityKnowledge(CoreModel):
    capability_id: UUID
    prerequisites: list[KnowledgeItem] = Field(default_factory=list)
    core_topics: list[KnowledgeItem] = Field(min_length=1)
    useful_practices: list[KnowledgeItem] = Field(min_length=1)
    acceptance_criteria: list[KnowledgeItem] = Field(min_length=1)
    level_criteria: list[KnowledgeItem] = Field(default_factory=list)
    sources: list[KnowledgeSource] = Field(min_length=1)
    generated_at: datetime
    input_fingerprint: Sha256

    _generated_at_has_timezone = field_validator("generated_at")(_timezone_required)

    @model_validator(mode="after")
    def validate_source_graph(self) -> CapabilityKnowledge:
        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Knowledge source_id 不能重复")
        known = set(source_ids)
        if self.level_criteria and len(self.level_criteria) != 6:
            raise ValueError("Knowledge level_criteria 必须完整包含 Level 0–5")
        for collection in (
            self.prerequisites,
            self.core_topics,
            self.useful_practices,
            self.acceptance_criteria,
            self.level_criteria,
        ):
            for item in collection:
                unknown = set(item.source_ids) - known
                if unknown:
                    raise ValueError("Knowledge item 引用了未知 source_id")
        return self


class PersonalCapabilityState(CoreModel):
    capability_id: UUID
    current_level: StrictInt = Field(ge=0, le=5)


class Practice(CoreModel):
    practice_id: UUID = Field(default_factory=new_id)
    capability_id: UUID
    description: NonEmptyText


class RoadmapVersion(CoreModel):
    roadmap_id: UUID = Field(default_factory=new_id)
    role_id: UUID
    generated_at: datetime
    input_fingerprint: Sha256
    content: NonEmptyText

    _generated_at_has_timezone = field_validator("generated_at")(_timezone_required)


class VersionedDocument(CoreModel):
    schema_version: Literal["1.0"] = "1.0"


class RolesDocument(VersionedDocument):
    roles: list[Role] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_roles(self) -> RolesDocument:
        ids = [item.role_id for item in self.roles]
        names = [normalize_source_expression(item.name) for item in self.roles]
        if len(ids) != len(set(ids)):
            raise ValueError("role_id 不能重复")
        if len(names) != len(set(names)):
            raise ValueError("Role name 不能重复")
        return self


class JDsDocument(VersionedDocument):
    role_id: UUID
    jobs: list[JD] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_jobs(self) -> JDsDocument:
        ids = [item.job_id for item in self.jobs]
        if len(ids) != len(set(ids)):
            raise ValueError("job_id 不能重复")
        if any(item.role_id != self.role_id for item in self.jobs):
            raise ValueError("JD 必须属于文档指定 Role")
        return self


class JDAnalysesDocument(VersionedDocument):
    role_id: UUID
    analyses: list[JDAnalysis] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_analyses(self) -> JDAnalysesDocument:
        ids = [item.job_id for item in self.analyses]
        if len(ids) != len(set(ids)):
            raise ValueError("同一 JD 只能有一个 current analysis")
        if any(item.role_id != self.role_id for item in self.analyses):
            raise ValueError("JDAnalysis 必须属于文档指定 Role")
        return self


class CapabilityCatalogDocument(VersionedDocument):
    capabilities: list[Capability] = Field(default_factory=list)
    source_mappings: list[SourceMapping] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_catalog(self) -> CapabilityCatalogDocument:
        ids = [item.capability_id for item in self.capabilities]
        names = [normalize_source_expression(item.name) for item in self.capabilities]
        mapping_keys = [item.normalized_expression for item in self.source_mappings]
        if len(ids) != len(set(ids)):
            raise ValueError("capability_id 不能重复")
        if len(names) != len(set(names)):
            raise ValueError("Capability name 不能重复")
        if len(mapping_keys) != len(set(mapping_keys)):
            raise ValueError("SourceMapping key 不能重复")
        known = set(ids)
        if any(item.capability_id not in known for item in self.source_mappings):
            raise ValueError("SourceMapping 必须指向已存在 Capability")
        return self


class PersonalCapabilityStatesDocument(VersionedDocument):
    states: list[PersonalCapabilityState] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_capabilities(self) -> PersonalCapabilityStatesDocument:
        ids = [item.capability_id for item in self.states]
        if len(ids) != len(set(ids)):
            raise ValueError("每个 Capability 只能有一个 current_level")
        return self


class PracticesDocument(VersionedDocument):
    practices: list[Practice] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_practices(self) -> PracticesDocument:
        ids = [item.practice_id for item in self.practices]
        if len(ids) != len(set(ids)):
            raise ValueError("practice_id 不能重复")
        return self


class SkippedCandidatesDocument(VersionedDocument):
    role_id: UUID
    candidates: list[SkippedCandidate] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_candidates(self) -> SkippedCandidatesDocument:
        keys = [item.candidate_fingerprint for item in self.candidates]
        if len(keys) != len(set(keys)):
            raise ValueError("SkippedCandidate fingerprint 不能重复")
        if any(item.role_id != self.role_id for item in self.candidates):
            raise ValueError("SkippedCandidate 必须属于文档指定 Role")
        return self


class RoadmapScopeDocument(VersionedDocument):
    role_id: UUID
    excluded_capability_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_exclusions(self) -> RoadmapScopeDocument:
        values = [str(item) for item in self.excluded_capability_ids]
        if len(values) != len(set(values)):
            raise ValueError("Roadmap Scope exclusion 不能重复")
        if values != sorted(values):
            raise ValueError("Roadmap Scope exclusion 必须按 capability_id 排序")
        return self
