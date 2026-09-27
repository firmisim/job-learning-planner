from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import TypeVar
from uuid import UUID

from pydantic import BaseModel, ValidationError

from schemas.core import (
    Capability,
    CapabilityCatalogDocument,
    CapabilityKnowledge,
    JD,
    JDAnalysesDocument,
    JDAnalysis,
    JDsDocument,
    PersonalCapabilityState,
    PersonalCapabilityStatesDocument,
    Practice,
    PracticesDocument,
    RoadmapScopeDocument,
    RoadmapVersion,
    Role,
    RolesDocument,
    SkippedCandidate,
    SkippedCandidatesDocument,
    SourceMapping,
    normalize_source_expression,
)
from src.state_safety import (
    StaleStateError,
    atomic_replace_bytes,
    atomic_replace_file_set,
    sha256_file,
)

MAX_ROADMAP_VERSIONS_PER_ROLE = 30


DocumentT = TypeVar("DocumentT", bound=BaseModel)


class CoreStorage:
    """Concrete file boundary for the minimum core model.

    The layout is intentionally explicit. It is not a generic repository layer.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.roles_path = self.root / "roles.json"
        self.catalog_path = self.root / "capabilities.json"
        self.personal_states_path = self.root / "personal_capabilities.json"
        self.practices_path = self.root / "practices.json"
        self.roles_root = self.root / "roles"
        self.knowledge_root = self.root / "knowledge"

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.roles_root.mkdir(parents=True, exist_ok=True)
        self.knowledge_root.mkdir(parents=True, exist_ok=True)
        self._initialize_document(self.roles_path, RolesDocument())
        self._initialize_document(self.catalog_path, CapabilityCatalogDocument())
        self._initialize_document(
            self.personal_states_path, PersonalCapabilityStatesDocument()
        )
        self._initialize_document(self.practices_path, PracticesDocument())

    def _initialize_document(self, path: Path, document: BaseModel) -> None:
        if path.exists():
            self._load(path, type(document))
            return
        self._write(path, document, expected_sha256=None)

    @staticmethod
    def _encoded(document: BaseModel) -> bytes:
        payload = document.model_dump(mode="json")
        return (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")

    @staticmethod
    def _load_with_sha(path: Path, model: type[DocumentT]) -> tuple[DocumentT, str]:
        if not path.is_file():
            raise FileNotFoundError(f"缺少 Core storage 文件: {path}")
        try:
            content = path.read_bytes()
            document = model.model_validate_json(content)
        except (OSError, UnicodeDecodeError, ValidationError) as exc:
            raise ValueError(f"Core storage 文件无效: {path}: {exc}") from exc
        return document, hashlib.sha256(content).hexdigest()

    @classmethod
    def _load(cls, path: Path, model: type[DocumentT]) -> DocumentT:
        return cls._load_with_sha(path, model)[0]

    @classmethod
    def _write(
        cls,
        path: Path,
        document: BaseModel,
        *,
        expected_sha256: str | None,
    ) -> str:
        # Serialize and revalidate before the atomic replacement boundary.
        encoded = cls._encoded(document)
        type(document).model_validate_json(encoded)
        return atomic_replace_bytes(path, encoded, expected_sha256=expected_sha256)

    def _role_dir(self, role_id: UUID) -> Path:
        return self.roles_root / str(role_id)

    def _roadmap_scope_path(self, role_id: UUID) -> Path:
        return self._role_dir(role_id) / "roadmap_scope.json"

    def _require_role(self, role_id: UUID) -> Role:
        for role in self.load_roles().roles:
            if role.role_id == role_id:
                return role
        raise ValueError("Role 不存在")

    def _require_capability(self, capability_id: UUID) -> Capability:
        for capability in self.load_catalog().capabilities:
            if capability.capability_id == capability_id:
                return capability
        raise ValueError("Capability 不存在")

    def load_roles(self) -> RolesDocument:
        return self._load(self.roles_path, RolesDocument)

    def load_roles_snapshot(self) -> tuple[RolesDocument, str]:
        return self._load_with_sha(self.roles_path, RolesDocument)

    def load_catalog(self) -> CapabilityCatalogDocument:
        return self._load(self.catalog_path, CapabilityCatalogDocument)

    def load_catalog_snapshot(
        self,
    ) -> tuple[CapabilityCatalogDocument, str]:
        return self._load_with_sha(self.catalog_path, CapabilityCatalogDocument)

    def load_personal_states(self) -> PersonalCapabilityStatesDocument:
        return self._load(self.personal_states_path, PersonalCapabilityStatesDocument)

    def load_personal_states_snapshot(
        self,
    ) -> tuple[PersonalCapabilityStatesDocument, str]:
        return self._load_with_sha(
            self.personal_states_path, PersonalCapabilityStatesDocument
        )

    def load_practices(self) -> PracticesDocument:
        return self._load(self.practices_path, PracticesDocument)

    def load_practices_snapshot(self) -> tuple[PracticesDocument, str]:
        return self._load_with_sha(self.practices_path, PracticesDocument)

    def load_roadmap_scope_snapshot(
        self, role_id: UUID
    ) -> tuple[RoadmapScopeDocument, str | None]:
        self._require_role(role_id)
        path = self._roadmap_scope_path(role_id)
        if not path.is_file():
            return RoadmapScopeDocument(role_id=role_id), None
        document, fingerprint = self._load_with_sha(path, RoadmapScopeDocument)
        if document.role_id != role_id:
            raise ValueError("Roadmap Scope 必须属于指定 Role")
        known_capabilities = {
            item.capability_id for item in self.load_catalog().capabilities
        }
        if any(
            item not in known_capabilities
            for item in document.excluded_capability_ids
        ):
            raise ValueError("Roadmap Scope 引用了未知 Capability")
        return document, fingerprint

    def is_capability_included_in_roadmap(
        self, role_id: UUID, capability_id: UUID
    ) -> bool:
        self._require_capability(capability_id)
        scope, _ = self.load_roadmap_scope_snapshot(role_id)
        return capability_id not in scope.excluded_capability_ids

    def set_roadmap_scope_inclusion(
        self,
        role_id: UUID,
        capability_id: UUID,
        included: bool,
        *,
        expected_sha256: str | None,
    ) -> str | None:
        if type(included) is not bool:
            raise ValueError("included 必须是 boolean")
        self._require_capability(capability_id)
        current, current_sha256 = self.load_roadmap_scope_snapshot(role_id)
        excluded = set(current.excluded_capability_ids)
        currently_included = capability_id not in excluded
        if currently_included == included:
            return current_sha256
        self._check_expected(current_sha256, expected_sha256)
        if included:
            excluded.remove(capability_id)
        else:
            excluded.add(capability_id)
        updated = RoadmapScopeDocument(
            role_id=role_id,
            excluded_capability_ids=sorted(excluded, key=str),
        )
        path = self._roadmap_scope_path(role_id)
        if not updated.excluded_capability_ids:
            atomic_replace_file_set([(path, None, current_sha256)])
            return None
        return self._write(path, updated, expected_sha256=current_sha256)

    @staticmethod
    def _check_expected(actual: str, expected: str | None) -> None:
        if expected is not None and actual != expected:
            raise StaleStateError("目标文件已发生变化，请刷新页面后重试")

    def create_role(self, name: str, *, expected_sha256: str | None = None) -> Role:
        current, current_sha256 = self._load_with_sha(self.roles_path, RolesDocument)
        self._check_expected(current_sha256, expected_sha256)
        role = Role(name=name)
        updated = current.model_copy(update={"roles": [*current.roles, role]})
        role_dir = self._role_dir(role.role_id)
        role_dir.mkdir(parents=True, exist_ok=False)
        try:
            self._initialize_document(
                role_dir / "jds.json", JDsDocument(role_id=role.role_id)
            )
            self._initialize_document(
                role_dir / "jd_analyses.json",
                JDAnalysesDocument(role_id=role.role_id),
            )
            self._initialize_document(
                role_dir / "skipped_candidates.json",
                SkippedCandidatesDocument(role_id=role.role_id),
            )
            (role_dir / "roadmaps").mkdir(exist_ok=False)
            # Publish the Role only after its complete empty storage exists.
            self._write(
                self.roles_path,
                RolesDocument.model_validate(updated.model_dump()),
                expected_sha256=current_sha256,
            )
        except Exception:
            for path in sorted(role_dir.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            role_dir.rmdir()
            raise
        return role

    def rename_role(
        self,
        role_id: UUID,
        name: str,
        *,
        expected_sha256: str | None = None,
    ) -> Role:
        current, current_sha256 = self._load_with_sha(self.roles_path, RolesDocument)
        self._check_expected(current_sha256, expected_sha256)
        if role_id not in {item.role_id for item in current.roles}:
            raise ValueError("Role 不存在")
        renamed = Role(role_id=role_id, name=name)
        roles = [renamed if item.role_id == role_id else item for item in current.roles]
        document = RolesDocument(roles=roles)
        self._write(
            self.roles_path,
            document,
            expected_sha256=current_sha256,
        )
        return renamed

    def delete_role(self, role_id: UUID, *, expected_sha256: str | None = None) -> None:
        current, current_sha256 = self._load_with_sha(self.roles_path, RolesDocument)
        self._check_expected(current_sha256, expected_sha256)
        if role_id not in {item.role_id for item in current.roles}:
            raise ValueError("Role 不存在")
        role_dir = self._role_dir(role_id).resolve()
        if role_dir.parent != self.roles_root.resolve() or not role_dir.is_dir():
            raise ValueError("Role storage 边界无效")
        quarantine = self.roles_root / f".deleting-{role_id}"
        if quarantine.exists():
            raise ValueError("Role 删除暂存目录已存在")
        os.replace(role_dir, quarantine)
        try:
            self._write(
                self.roles_path,
                RolesDocument(
                    roles=[item for item in current.roles if item.role_id != role_id]
                ),
                expected_sha256=current_sha256,
            )
        except Exception:
            os.replace(quarantine, role_dir)
            raise
        shutil.rmtree(quarantine)

    def load_jds(self, role_id: UUID) -> JDsDocument:
        self._require_role(role_id)
        return self._load(self._role_dir(role_id) / "jds.json", JDsDocument)

    def load_jds_snapshot(self, role_id: UUID) -> tuple[JDsDocument, str]:
        self._require_role(role_id)
        return self._load_with_sha(self._role_dir(role_id) / "jds.json", JDsDocument)

    def add_jd(
        self,
        role_id: UUID,
        *,
        title: str,
        jd_text: str,
        company: str | None = None,
        source_url: str | None = None,
        expected_sha256: str | None = None,
    ) -> JD:
        self._require_role(role_id)
        path = self._role_dir(role_id) / "jds.json"
        current, current_sha256 = self._load_with_sha(path, JDsDocument)
        self._check_expected(current_sha256, expected_sha256)
        job = JD(
            role_id=role_id,
            title=title,
            company=company,
            jd_text=jd_text,
            source_url=source_url,
        )
        document = JDsDocument(role_id=role_id, jobs=[*current.jobs, job])
        self._write(path, document, expected_sha256=current_sha256)
        return job

    def replace_jds(
        self,
        role_id: UUID,
        jobs: list[JD],
        *,
        expected_sha256: str | None = None,
    ) -> None:
        self._require_role(role_id)
        path = self._role_dir(role_id) / "jds.json"
        _, current_sha256 = self._load_with_sha(path, JDsDocument)
        self._check_expected(current_sha256, expected_sha256)
        document = JDsDocument(role_id=role_id, jobs=jobs)
        self._retain_current_analyses(role_id, document)
        self._write(path, document, expected_sha256=current_sha256)

    def delete_jds(
        self,
        role_id: UUID,
        job_ids: set[UUID],
        *,
        expected_sha256: str | None = None,
    ) -> int:
        current, current_sha256 = self.load_jds_snapshot(role_id)
        self._check_expected(current_sha256, expected_sha256)
        known = {item.job_id for item in current.jobs}
        if not job_ids or not job_ids <= known:
            raise ValueError("JD selection 无效")
        jobs = [item for item in current.jobs if item.job_id not in job_ids]
        document = JDsDocument(role_id=role_id, jobs=jobs)
        self._retain_current_analyses(role_id, document)
        self._write(
            self._role_dir(role_id) / "jds.json",
            document,
            expected_sha256=current_sha256,
        )
        return len(job_ids)

    def _retain_current_analyses(self, role_id: UUID, jobs: JDsDocument) -> None:
        path = self._role_dir(role_id) / "jd_analyses.json"
        current, current_sha256 = self._load_with_sha(path, JDAnalysesDocument)
        job_ids = {item.job_id for item in jobs.jobs}
        document = JDAnalysesDocument(
            role_id=role_id,
            analyses=[item for item in current.analyses if item.job_id in job_ids],
        )
        self._write(path, document, expected_sha256=current_sha256)

    def load_jd_analyses(self, role_id: UUID) -> JDAnalysesDocument:
        self._require_role(role_id)
        return self._load(
            self._role_dir(role_id) / "jd_analyses.json", JDAnalysesDocument
        )

    def load_jd_analyses_snapshot(
        self, role_id: UUID
    ) -> tuple[JDAnalysesDocument, str]:
        self._require_role(role_id)
        return self._load_with_sha(
            self._role_dir(role_id) / "jd_analyses.json",
            JDAnalysesDocument,
        )

    def jd_analyses_sha256(self, role_id: UUID) -> str:
        """Return the concurrency token without parsing a generated analysis asset."""

        self._require_role(role_id)
        path = self._role_dir(role_id) / "jd_analyses.json"
        current_sha256 = sha256_file(path)
        if current_sha256 is None:
            raise FileNotFoundError(f"缺少 Core storage 文件: {path}")
        return current_sha256

    def replace_jd_analyses(
        self,
        role_id: UUID,
        analyses: list[JDAnalysis],
        *,
        expected_sha256: str | None = None,
    ) -> None:
        jobs = self.load_jds(role_id)
        job_ids = {item.job_id for item in jobs.jobs}
        if any(item.job_id not in job_ids for item in analyses):
            raise ValueError("JDAnalysis 必须引用当前 Role 中存在的 JD")
        path = self._role_dir(role_id) / "jd_analyses.json"
        current_sha256 = self.jd_analyses_sha256(role_id)
        self._check_expected(current_sha256, expected_sha256)
        self._write(
            path,
            JDAnalysesDocument(role_id=role_id, analyses=analyses),
            expected_sha256=current_sha256,
        )

    def save_jd_analysis(self, analysis: JDAnalysis) -> None:
        jobs = self.load_jds(analysis.role_id)
        if analysis.job_id not in {item.job_id for item in jobs.jobs}:
            raise ValueError("JDAnalysis 必须引用当前 Role 中存在的 JD")
        path = self._role_dir(analysis.role_id) / "jd_analyses.json"
        current, expected_sha256 = self._load_with_sha(path, JDAnalysesDocument)
        analyses = [item for item in current.analyses if item.job_id != analysis.job_id]
        analyses.append(analysis)
        document = JDAnalysesDocument(role_id=analysis.role_id, analyses=analyses)
        self._write(path, document, expected_sha256=expected_sha256)

    def create_capability(
        self, name: str, *, expected_sha256: str | None = None
    ) -> Capability:
        current, current_sha256 = self._load_with_sha(
            self.catalog_path, CapabilityCatalogDocument
        )
        self._check_expected(current_sha256, expected_sha256)
        capability = Capability(name=name)
        document = CapabilityCatalogDocument(
            capabilities=[*current.capabilities, capability],
            source_mappings=current.source_mappings,
        )
        self._write(
            self.catalog_path,
            document,
            expected_sha256=current_sha256,
        )
        return capability

    def create_capability_with_mapping(
        self,
        name: str,
        source_expression: str,
        *,
        expected_sha256: str | None = None,
    ) -> tuple[Capability, SourceMapping, bool]:
        current, current_sha256 = self._load_with_sha(
            self.catalog_path, CapabilityCatalogDocument
        )
        key = normalize_source_expression(source_expression)
        capabilities_by_id = {item.capability_id: item for item in current.capabilities}
        for mapping in current.source_mappings:
            if mapping.normalized_expression != key:
                continue
            capability = capabilities_by_id[mapping.capability_id]
            if normalize_source_expression(
                capability.name
            ) == normalize_source_expression(name):
                return capability, mapping, False
            raise ValueError("SourceMapping 已指向不同 Capability")
        self._check_expected(current_sha256, expected_sha256)
        if normalize_source_expression(name) in {
            normalize_source_expression(item.name) for item in current.capabilities
        }:
            raise ValueError("Capability name 已存在，请改为 Merge")
        capability = Capability(name=name)
        mapping = SourceMapping.create(source_expression, capability.capability_id)
        document = CapabilityCatalogDocument(
            capabilities=[*current.capabilities, capability],
            source_mappings=[*current.source_mappings, mapping],
        )
        self._write(
            self.catalog_path,
            document,
            expected_sha256=current_sha256,
        )
        return capability, mapping, True

    def rename_capability(
        self,
        capability_id: UUID,
        name: str,
        *,
        expected_sha256: str | None = None,
    ) -> Capability:
        current, current_sha256 = self._load_with_sha(
            self.catalog_path, CapabilityCatalogDocument
        )
        self._check_expected(current_sha256, expected_sha256)
        if capability_id not in {item.capability_id for item in current.capabilities}:
            raise ValueError("Capability 不存在")
        renamed = Capability(capability_id=capability_id, name=name)
        capabilities = [
            renamed if item.capability_id == capability_id else item
            for item in current.capabilities
        ]
        document = CapabilityCatalogDocument(
            capabilities=capabilities,
            source_mappings=current.source_mappings,
        )
        self._write(
            self.catalog_path,
            document,
            expected_sha256=current_sha256,
        )
        return renamed

    def add_source_mapping(
        self,
        source_expression: str,
        capability_id: UUID,
        *,
        expected_sha256: str | None = None,
    ) -> SourceMapping:
        current, current_sha256 = self._load_with_sha(
            self.catalog_path, CapabilityCatalogDocument
        )
        if capability_id not in {item.capability_id for item in current.capabilities}:
            raise ValueError("Capability 不存在")
        key = normalize_source_expression(source_expression)
        for mapping in current.source_mappings:
            if mapping.normalized_expression == key:
                if mapping.capability_id == capability_id:
                    return mapping
                raise ValueError("SourceMapping 已指向不同 Capability")
        self._check_expected(current_sha256, expected_sha256)
        mapping = SourceMapping.create(source_expression, capability_id)
        document = CapabilityCatalogDocument(
            capabilities=current.capabilities,
            source_mappings=[*current.source_mappings, mapping],
        )
        self._write(
            self.catalog_path,
            document,
            expected_sha256=current_sha256,
        )
        return mapping

    def remove_source_mapping(
        self,
        source_expression: str,
        capability_id: UUID,
        *,
        expected_sha256: str | None = None,
    ) -> SourceMapping:
        current, current_sha256 = self.load_catalog_snapshot()
        self._check_expected(current_sha256, expected_sha256)
        key = normalize_source_expression(source_expression)
        mapping = next(
            (item for item in current.source_mappings if item.normalized_expression == key),
            None,
        )
        if mapping is None:
            raise ValueError("SourceMapping 不存在")
        if mapping.capability_id != capability_id:
            raise ValueError("SourceMapping 已发生变化")
        self._write(
            self.catalog_path,
            CapabilityCatalogDocument(
                capabilities=current.capabilities,
                source_mappings=[
                    item
                    for item in current.source_mappings
                    if item.normalized_expression != key
                ],
            ),
            expected_sha256=current_sha256,
        )
        return mapping

    def reassign_source_mapping(
        self,
        source_expression: str,
        capability_id: UUID,
        new_capability_id: UUID,
        *,
        expected_sha256: str | None = None,
    ) -> SourceMapping:
        current, current_sha256 = self.load_catalog_snapshot()
        self._check_expected(current_sha256, expected_sha256)
        known = {item.capability_id for item in current.capabilities}
        if new_capability_id not in known:
            raise ValueError("新的 Capability target 不存在")
        key = normalize_source_expression(source_expression)
        existing = next(
            (item for item in current.source_mappings if item.normalized_expression == key),
            None,
        )
        if existing is None:
            raise ValueError("SourceMapping 不存在")
        if existing.capability_id != capability_id:
            raise ValueError("SourceMapping 已发生变化")
        if capability_id == new_capability_id:
            return existing
        reassigned = SourceMapping.create(existing.source_expression, new_capability_id)
        self._write(
            self.catalog_path,
            CapabilityCatalogDocument(
                capabilities=current.capabilities,
                source_mappings=[
                    reassigned if item.normalized_expression == key else item
                    for item in current.source_mappings
                ],
            ),
            expected_sha256=current_sha256,
        )
        return reassigned

    def load_skipped_candidates(self, role_id: UUID) -> SkippedCandidatesDocument:
        self._require_role(role_id)
        return self._load(
            self._role_dir(role_id) / "skipped_candidates.json",
            SkippedCandidatesDocument,
        )

    def load_skipped_candidates_snapshot(
        self, role_id: UUID
    ) -> tuple[SkippedCandidatesDocument, str]:
        self._require_role(role_id)
        return self._load_with_sha(
            self._role_dir(role_id) / "skipped_candidates.json",
            SkippedCandidatesDocument,
        )

    def skip_candidate(
        self,
        candidate: SkippedCandidate,
        *,
        expected_sha256: str | None = None,
    ) -> bool:
        self._require_role(candidate.role_id)
        path = self._role_dir(candidate.role_id) / "skipped_candidates.json"
        current, current_sha256 = self._load_with_sha(path, SkippedCandidatesDocument)
        if candidate.candidate_fingerprint in {
            item.candidate_fingerprint for item in current.candidates
        }:
            return False
        self._check_expected(current_sha256, expected_sha256)
        document = SkippedCandidatesDocument(
            role_id=candidate.role_id,
            candidates=[*current.candidates, candidate],
        )
        self._write(path, document, expected_sha256=current_sha256)
        return True

    def restore_skipped_candidate(
        self,
        role_id: UUID,
        candidate_fingerprint: str,
        *,
        expected_sha256: str | None = None,
    ) -> bool:
        self._require_role(role_id)
        path = self._role_dir(role_id) / "skipped_candidates.json"
        current, current_sha256 = self._load_with_sha(path, SkippedCandidatesDocument)
        candidates = [
            item
            for item in current.candidates
            if item.candidate_fingerprint != candidate_fingerprint
        ]
        if len(candidates) == len(current.candidates):
            return False
        self._check_expected(current_sha256, expected_sha256)
        self._write(
            path,
            SkippedCandidatesDocument(role_id=role_id, candidates=candidates),
            expected_sha256=current_sha256,
        )
        return True

    def save_knowledge(
        self,
        knowledge: CapabilityKnowledge,
        *,
        expected_sha256: str | None,
    ) -> str:
        self._require_capability(knowledge.capability_id)
        path = self.knowledge_root / f"{knowledge.capability_id}.json"
        if path.is_file():
            current, current_sha256 = self._load_with_sha(path, CapabilityKnowledge)
            if current == knowledge:
                return current_sha256
            self._check_expected(current_sha256, expected_sha256)
        elif expected_sha256 is not None:
            raise StaleStateError("目标文件已发生变化，请刷新页面后重试")
        return self._write(path, knowledge, expected_sha256=expected_sha256)

    def load_knowledge_snapshot(
        self, capability_id: UUID
    ) -> tuple[CapabilityKnowledge | None, str | None]:
        self._require_capability(capability_id)
        path = self.knowledge_root / f"{capability_id}.json"
        if not path.is_file():
            return None, None
        return self._load_with_sha(path, CapabilityKnowledge)

    def load_knowledge(self, capability_id: UUID) -> CapabilityKnowledge:
        self._require_capability(capability_id)
        return self._load(
            self.knowledge_root / f"{capability_id}.json",
            CapabilityKnowledge,
        )

    def remove_knowledge(
        self,
        capability_id: UUID,
        *,
        expected_sha256: str | None,
    ) -> CapabilityKnowledge:
        self._require_capability(capability_id)
        path = self.knowledge_root / f"{capability_id}.json"
        if not path.is_file():
            raise ValueError("Capability Knowledge 不存在")
        knowledge, actual_sha256 = self._load_with_sha(path, CapabilityKnowledge)
        self._check_expected(actual_sha256, expected_sha256)
        atomic_replace_file_set([(path, None, actual_sha256)])
        return knowledge

    def delete_capability(
        self,
        capability_id: UUID,
        *,
        expected_catalog_sha256: str,
        expected_personal_states_sha256: str,
        expected_practices_sha256: str,
        expected_knowledge_sha256: str | None,
    ) -> Capability:
        catalog, catalog_sha256 = self.load_catalog_snapshot()
        states, states_sha256 = self.load_personal_states_snapshot()
        practices, practices_sha256 = self.load_practices_snapshot()
        self._check_expected(catalog_sha256, expected_catalog_sha256)
        self._check_expected(states_sha256, expected_personal_states_sha256)
        self._check_expected(practices_sha256, expected_practices_sha256)
        capability = next(
            (item for item in catalog.capabilities if item.capability_id == capability_id),
            None,
        )
        if capability is None:
            raise ValueError("Capability 不存在")
        if any(
            item.capability_id == capability_id for item in catalog.source_mappings
        ):
            raise ValueError("Capability 仍有 SourceMapping，请先 Unmap 或 Reassign")

        knowledge_path = self.knowledge_root / f"{capability_id}.json"
        actual_knowledge_sha256 = sha256_file(knowledge_path)
        if actual_knowledge_sha256 != expected_knowledge_sha256:
            raise StaleStateError("目标文件已发生变化，请刷新页面后重试")
        if actual_knowledge_sha256 is not None:
            self._load(knowledge_path, CapabilityKnowledge)

        scope_changes: list[tuple[Path, bytes | None, str | None]] = []
        for role in self.load_roles().roles:
            scope, scope_sha256 = self.load_roadmap_scope_snapshot(role.role_id)
            if capability_id not in scope.excluded_capability_ids:
                continue
            updated_scope = RoadmapScopeDocument(
                role_id=role.role_id,
                excluded_capability_ids=[
                    item
                    for item in scope.excluded_capability_ids
                    if item != capability_id
                ],
            )
            scope_changes.append(
                (
                    self._roadmap_scope_path(role.role_id),
                    (
                        self._encoded(updated_scope)
                        if updated_scope.excluded_capability_ids
                        else None
                    ),
                    scope_sha256,
                )
            )

        updated_states = PersonalCapabilityStatesDocument(
            states=[item for item in states.states if item.capability_id != capability_id]
        )
        updated_practices = PracticesDocument(
            practices=[
                item for item in practices.practices if item.capability_id != capability_id
            ]
        )
        updated_catalog = CapabilityCatalogDocument(
            capabilities=[
                item for item in catalog.capabilities if item.capability_id != capability_id
            ],
            source_mappings=catalog.source_mappings,
        )
        atomic_replace_file_set(
            [
                (
                    self.personal_states_path,
                    self._encoded(updated_states),
                    states_sha256,
                ),
                (
                    self.practices_path,
                    self._encoded(updated_practices),
                    practices_sha256,
                ),
                (knowledge_path, None, actual_knowledge_sha256),
                (
                    self.catalog_path,
                    self._encoded(updated_catalog),
                    catalog_sha256,
                ),
                *scope_changes,
            ]
        )
        return capability

    def set_current_level(
        self,
        capability_id: UUID,
        current_level: int,
        *,
        expected_sha256: str | None = None,
    ) -> PersonalCapabilityState:
        self._require_capability(capability_id)
        current, actual_sha256 = self._load_with_sha(
            self.personal_states_path, PersonalCapabilityStatesDocument
        )
        state = PersonalCapabilityState(
            capability_id=capability_id, current_level=current_level
        )
        existing = next(
            (item for item in current.states if item.capability_id == capability_id),
            None,
        )
        if existing == state:
            return existing
        self._check_expected(actual_sha256, expected_sha256)
        values = [
            item for item in current.states if item.capability_id != capability_id
        ]
        values.append(state)
        document = PersonalCapabilityStatesDocument(states=values)
        self._write(
            self.personal_states_path,
            document,
            expected_sha256=actual_sha256,
        )
        return state

    def add_practice(
        self,
        capability_id: UUID,
        description: str,
        *,
        expected_sha256: str | None = None,
    ) -> Practice:
        self._require_capability(capability_id)
        current, actual_sha256 = self._load_with_sha(
            self.practices_path, PracticesDocument
        )
        self._check_expected(actual_sha256, expected_sha256)
        practice = Practice(capability_id=capability_id, description=description)
        document = PracticesDocument(practices=[*current.practices, practice])
        self._write(
            self.practices_path,
            document,
            expected_sha256=actual_sha256,
        )
        return practice

    def edit_practice(
        self,
        practice_id: UUID,
        description: str,
        *,
        expected_sha256: str | None = None,
    ) -> Practice:
        current, actual_sha256 = self._load_with_sha(
            self.practices_path, PracticesDocument
        )
        existing = next(
            (item for item in current.practices if item.practice_id == practice_id),
            None,
        )
        if existing is None:
            raise ValueError("Practice 不存在")
        updated = Practice(
            practice_id=existing.practice_id,
            capability_id=existing.capability_id,
            description=description,
        )
        if updated == existing:
            return existing
        self._check_expected(actual_sha256, expected_sha256)
        document = PracticesDocument(
            practices=[
                updated if item.practice_id == practice_id else item
                for item in current.practices
            ]
        )
        self._write(
            self.practices_path,
            document,
            expected_sha256=actual_sha256,
        )
        return updated

    def delete_practice(
        self,
        practice_id: UUID,
        *,
        expected_sha256: str | None = None,
    ) -> Practice:
        current, actual_sha256 = self._load_with_sha(
            self.practices_path, PracticesDocument
        )
        existing = next(
            (item for item in current.practices if item.practice_id == practice_id),
            None,
        )
        if existing is None:
            raise ValueError("Practice 不存在")
        self._check_expected(actual_sha256, expected_sha256)
        document = PracticesDocument(
            practices=[
                item for item in current.practices if item.practice_id != practice_id
            ]
        )
        self._write(
            self.practices_path,
            document,
            expected_sha256=actual_sha256,
        )
        return existing

    def append_roadmap(self, roadmap: RoadmapVersion) -> Path:
        self._require_role(roadmap.role_id)
        path = (
            self._role_dir(roadmap.role_id) / "roadmaps" / f"{roadmap.roadmap_id}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = self._encoded(roadmap)
        RoadmapVersion.model_validate_json(encoded)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(path, flags)
        try:
            with os.fdopen(descriptor, "wb") as file:
                file.write(encoded)
                file.flush()
                os.fsync(file.fileno())
        except Exception:
            if path.exists():
                path.unlink()
            raise
        return path

    def list_roadmaps(self, role_id: UUID) -> list[RoadmapVersion]:
        self._require_role(role_id)
        root = self._role_dir(role_id) / "roadmaps"
        roadmaps = [self._load(path, RoadmapVersion) for path in root.glob("*.json")]
        return sorted(
            roadmaps, key=lambda item: (item.generated_at, str(item.roadmap_id))
        )

    def delete_roadmap(self, role_id: UUID, roadmap_id: UUID) -> RoadmapVersion:
        """Remove one immutable generated artifact without touching source facts."""

        self._require_role(role_id)
        path = self._role_dir(role_id) / "roadmaps" / f"{roadmap_id}.json"
        if not path.is_file():
            raise ValueError("Roadmap version 不存在")
        roadmap = self._load(path, RoadmapVersion)
        if roadmap.role_id != role_id or roadmap.roadmap_id != roadmap_id:
            raise ValueError("Roadmap version 不属于当前 Role")
        path.unlink()
        return roadmap

    def enforce_roadmap_retention(
        self,
        role_id: UUID,
        *,
        preserve_roadmap_id: UUID,
        limit: int = MAX_ROADMAP_VERSIONS_PER_ROLE,
    ) -> tuple[RoadmapVersion, ...]:
        """Keep the newest bounded Role history after a new version is durable."""

        if limit < 1:
            raise ValueError("Roadmap retention limit 必须大于 0")
        versions = self.list_roadmaps(role_id)
        overflow = len(versions) - limit
        if overflow <= 0:
            return ()
        removable = [
            item for item in versions if item.roadmap_id != preserve_roadmap_id
        ]
        removed: list[RoadmapVersion] = []
        for item in removable[:overflow]:
            removed.append(self.delete_roadmap(role_id, item.roadmap_id))
        return tuple(removed)
