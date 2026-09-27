from __future__ import annotations

from datetime import datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from schemas.core import (
    AtomicMarketSignal,
    Capability,
    CapabilityCatalogDocument,
    JDAnalysis,
    PersonalCapabilityState,
    Practice,
    RoadmapVersion,
    Role,
    SourceMapping,
)


FINGERPRINT = "a" * 64


def test_capability_identity_is_opaque_uuid_and_not_semantic() -> None:
    first = Capability(name="Python")
    second = Capability(name="Python")

    assert isinstance(first.capability_id, UUID)
    assert first.capability_id != second.capability_id
    assert "Python" not in str(first.capability_id)

    renamed = first.model_copy(update={"name": "Python Engineering"})
    assert renamed.capability_id == first.capability_id


def test_source_mapping_is_global_expression_to_capability_contract() -> None:
    capability = Capability(name="Python")
    mapping = SourceMapping.create("  Python   Programming  ", capability.capability_id)

    assert mapping.normalized_expression == "python programming"
    assert mapping.capability_id == capability.capability_id

    with pytest.raises(ValidationError, match="不一致"):
        SourceMapping(
            source_expression="Python",
            normalized_expression="java",
            capability_id=capability.capability_id,
        )


def test_catalog_rejects_duplicate_names_without_using_name_as_identity() -> None:
    first = Capability(name="Python")
    second = Capability(name="python")

    assert first.capability_id != second.capability_id
    with pytest.raises(ValidationError, match="name 不能重复"):
        CapabilityCatalogDocument(capabilities=[first, second])


def test_jd_analysis_preserves_atomic_source_and_evidence_lineage() -> None:
    role = Role(name="Backend Engineer")
    analysis = JDAnalysis(
        job_id=UUID("11111111-1111-4111-8111-111111111111"),
        role_id=role.role_id,
        source_fingerprint=FINGERPRINT,
        signals=[
            AtomicMarketSignal(
                source_expression="Spring Boot 或 FastAPI",
                atomic_expression="FastAPI",
                evidence="熟悉 Spring Boot 或 FastAPI 开发",
            )
        ],
    )

    assert analysis.signals[0].atomic_expression == "FastAPI"
    assert analysis.signals[0].source_expression in analysis.signals[0].evidence
    assert set(AtomicMarketSignal.model_fields) == {
        "source_expression",
        "atomic_expression",
        "evidence",
    }


def test_personal_and_roadmap_minima_reject_old_lifecycle_fields() -> None:
    capability = Capability(name="Python")
    state = PersonalCapabilityState(
        capability_id=capability.capability_id, current_level=3
    )
    practice = Practice(
        capability_id=capability.capability_id,
        description="Built a typed command-line tool",
    )
    roadmap = RoadmapVersion(
        role_id=Role(name="Backend").role_id,
        generated_at=datetime.fromisoformat("2026-09-10T10:00:00+08:00"),
        input_fingerprint=FINGERPRINT,
        content="Next learning step",
    )

    assert state.current_level == 3
    assert practice.description
    assert roadmap.content

    with pytest.raises(ValidationError, match="Extra inputs"):
        PersonalCapabilityState(
            capability_id=capability.capability_id,
            current_level=3,
            target_level=4,
        )
    with pytest.raises(ValidationError, match="时间必须包含时区"):
        RoadmapVersion(
            role_id=roadmap.role_id,
            generated_at=datetime(2026, 9, 10, 10, 0),
            input_fingerprint=FINGERPRINT,
            content="Invalid timestamp",
        )
