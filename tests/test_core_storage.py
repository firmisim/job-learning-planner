from __future__ import annotations

import inspect
from datetime import datetime
from pathlib import Path

import pytest

import schemas.core as core_schema_module
import src.core_storage as core_storage_module
from schemas.core import (
    AtomicMarketSignal,
    CapabilityKnowledge,
    JDAnalysis,
    KnowledgeItem,
    KnowledgeSource,
    RoadmapVersion,
    SkippedCandidate,
)
from src.core_storage import CoreStorage
from src.state_safety import StaleStateError, sha256_file


FINGERPRINT = "b" * 64


def test_new_core_has_no_legacy_model_dependency() -> None:
    source = inspect.getsource(core_schema_module) + inspect.getsource(
        core_storage_module
    )
    prohibited_imports = (
        "schemas.capability_assessment",
        "schemas.gap_analysis",
        "schemas.governance",
        "schemas.learning_state",
        "schemas.practice_evidence",
        "schemas.roadmap_context",
        "src.capability_identity",
        "src.governance",
        "src.gap_analysis",
    )
    assert not any(value in source for value in prohibited_imports)


def test_empty_storage_initializes_one_global_truth_per_collection(
    tmp_path: Path,
) -> None:
    store = CoreStorage(tmp_path / "state")
    store.initialize()

    assert store.load_roles().roles == []
    assert store.load_catalog().capabilities == []
    assert store.load_personal_states().states == []
    assert store.load_practices().practices == []
    assert sorted(path.name for path in store.root.glob("*.json")) == [
        "capabilities.json",
        "personal_capabilities.json",
        "practices.json",
        "roles.json",
    ]


def test_minimum_entities_round_trip_with_global_and_role_boundaries(
    tmp_path: Path,
) -> None:
    store = CoreStorage(tmp_path / "state")
    store.initialize()
    role_a = store.create_role("Backend")
    role_b = store.create_role("Platform")
    capability = store.create_capability("Python")

    renamed = store.rename_capability(capability.capability_id, "Python Engineering")
    assert renamed.capability_id == capability.capability_id
    mapping = store.add_source_mapping("Python programming", capability.capability_id)
    assert mapping.capability_id == capability.capability_id
    assert (
        store.add_source_mapping("Python programming", capability.capability_id)
        == mapping
    )

    state = store.set_current_level(capability.capability_id, 3)
    practice = store.add_practice(
        capability.capability_id, "Built a production-style API"
    )
    assert store.load_personal_states().states == [state]
    assert store.load_practices().practices == [practice]

    job = store.add_jd(
        role_a.role_id,
        title="Backend Engineer",
        company="Example",
        jd_text="熟悉 Python 或 Go 开发",
    )
    analysis = JDAnalysis(
        job_id=job.job_id,
        role_id=role_a.role_id,
        source_fingerprint=FINGERPRINT,
        signals=[
            AtomicMarketSignal(
                source_expression="Python 或 Go",
                atomic_expression="Python",
                evidence="熟悉 Python 或 Go 开发",
            )
        ],
    )
    store.save_jd_analysis(analysis)
    assert store.load_jd_analyses(role_a.role_id).analyses == [analysis]
    assert store.load_jds(role_b.role_id).jobs == []
    assert store.load_jd_analyses(role_b.role_id).analyses == []

    skipped = SkippedCandidate(
        role_id=role_a.role_id,
        candidate_fingerprint="c" * 64,
        atomic_expression="Communication",
    )
    store.skip_candidate(skipped)
    assert store.load_skipped_candidates(role_a.role_id).candidates == [skipped]
    assert store.load_skipped_candidates(role_b.role_id).candidates == []

    source = KnowledgeSource(title="Python docs", url="https://docs.python.org/3/")
    knowledge = CapabilityKnowledge(
        capability_id=capability.capability_id,
        core_topics=[KnowledgeItem(text="Typing", source_ids=[source.source_id])],
        useful_practices=[
            KnowledgeItem(text="Build an API", source_ids=[source.source_id])
        ],
        acceptance_criteria=[
            KnowledgeItem(text="Explain the types", source_ids=[source.source_id])
        ],
        sources=[source],
        generated_at=datetime.fromisoformat("2026-09-10T10:00:00+08:00"),
        input_fingerprint="e" * 64,
    )
    knowledge_hash = store.save_knowledge(knowledge, expected_sha256=None)
    assert knowledge_hash == sha256_file(
        store.knowledge_root / f"{capability.capability_id}.json"
    )
    assert store.load_knowledge(capability.capability_id) == knowledge

    roadmap = RoadmapVersion(
        role_id=role_a.role_id,
        generated_at=datetime.fromisoformat("2026-09-10T11:00:00+08:00"),
        input_fingerprint="d" * 64,
        content="Learn typing, then build an API.",
    )
    store.append_roadmap(roadmap)
    assert store.list_roadmaps(role_a.role_id) == [roadmap]
    assert store.list_roadmaps(role_b.role_id) == []


def test_role_and_source_do_not_define_capability_identity(tmp_path: Path) -> None:
    store = CoreStorage(tmp_path / "state")
    store.initialize()
    role = store.create_role("Backend")
    capability = store.create_capability("Python")
    original_id = capability.capability_id

    renamed_role = store.rename_role(role.role_id, "API Engineering")
    store.add_source_mapping("Python API development", original_id)

    assert renamed_role.role_id == role.role_id
    assert store.load_catalog().capabilities[0].capability_id == original_id


def test_storage_rejects_malformed_data_and_stale_atomic_write(
    tmp_path: Path,
) -> None:
    store = CoreStorage(tmp_path / "state")
    store.initialize()
    store.roles_path.write_text(
        '{"schema_version":"1.0","roles":[{}]}\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="Core storage 文件无效"):
        store.load_roles()

    store.roles_path.write_text(
        '{"schema_version":"1.0","roles":[]}\n', encoding="utf-8"
    )
    loaded, expected_sha256 = store._load_with_sha(
        store.roles_path, type(store.load_roles())
    )
    # Semantically equivalent concurrent bytes still invalidate the exact token.
    store.roles_path.write_text(
        '{"roles": [], "schema_version": "1.0"}\n', encoding="utf-8"
    )
    with pytest.raises(StaleStateError):
        store._write(
            store.roles_path,
            loaded,
            expected_sha256=expected_sha256,
        )


def test_mapping_conflict_and_append_only_roadmap_are_rejected(
    tmp_path: Path,
) -> None:
    store = CoreStorage(tmp_path / "state")
    store.initialize()
    role = store.create_role("Backend")
    python = store.create_capability("Python")
    java = store.create_capability("Java")
    store.add_source_mapping("Backend programming", python.capability_id)
    with pytest.raises(ValueError, match="不同 Capability"):
        store.add_source_mapping(" backend  programming ", java.capability_id)

    roadmap = RoadmapVersion(
        role_id=role.role_id,
        generated_at=datetime.fromisoformat("2026-09-10T11:00:00+08:00"),
        input_fingerprint=FINGERPRINT,
        content="One immutable version",
    )
    store.append_roadmap(roadmap)
    with pytest.raises(FileExistsError):
        store.append_roadmap(roadmap)


def test_new_storage_has_no_persisted_derived_workflow_truth(tmp_path: Path) -> None:
    store = CoreStorage(tmp_path / "state")
    store.initialize()
    names = {path.name for path in store.root.rglob("*") if path.is_file()}

    prohibited = {
        "gap.json",
        "freshness.json",
        "coverage.json",
        "readiness.json",
        "governance_decision.json",
        "research_plan.json",
        "research_result.json",
        "roadmap_context.json",
    }
    assert not names & prohibited
