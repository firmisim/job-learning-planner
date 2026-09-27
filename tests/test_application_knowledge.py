from __future__ import annotations

import json
import inspect
from pathlib import Path
from uuid import uuid4

import pytest

from application.capabilities import CapabilityOperations
from application.errors import ApplicationError
from application.market import MarketOperations
from schemas.core import CapabilityKnowledge
from tests.test_application_capabilities import _role_with_signals


def _mapped_capability(
    root: Path,
    role_name: str = "API Engineering",
    expression: str = "FastAPI",
) -> tuple[MarketOperations, CapabilityOperations, str, str]:
    market = MarketOperations(root)
    role_id = _role_with_signals(market, role_name, [expression])
    operations = CapabilityOperations(root)
    candidate = operations.workspace(role_id).pending_candidates[0]
    operations.add(
        role_id,
        candidate.candidate_fingerprint,
        expression,
        expected_catalog_sha256=operations.workspace(role_id).catalog_sha256,
    )
    capability_id = operations.workspace(role_id).current_capabilities[0].capability_id
    return market, operations, role_id, capability_id


def _knowledge_payload(
    research_input: dict[str, object],
    *,
    generated_at: str = "2026-09-10T12:00:00+08:00",
    topic: str = "Routing and dependency injection",
    level_prefix: str = "FastAPI",
) -> str:
    capability = research_input["capability"]
    assert isinstance(capability, dict)
    source_id = str(uuid4())
    return json.dumps(
        {
            "capability_id": capability["capability_id"],
            "prerequisites": [{"text": "Python typing", "source_ids": [source_id]}],
            "core_topics": [{"text": topic, "source_ids": [source_id]}],
            "useful_practices": [
                {"text": "Build and test a small API", "source_ids": [source_id]}
            ],
            "acceptance_criteria": [
                {
                    "text": "Can implement and test request validation",
                    "source_ids": [source_id],
                }
            ],
            "level_criteria": [
                {
                    "text": f"{level_prefix} Level {level}: observable task {level}",
                    "source_ids": [source_id],
                }
                for level in range(6)
            ],
            "sources": [
                {
                    "source_id": source_id,
                    "title": "FastAPI documentation",
                    "url": "https://fastapi.tiangolo.com/",
                }
            ],
            "generated_at": generated_at,
            "input_fingerprint": capability["input_fingerprint"],
        }
    )


def test_research_create_read_refresh_and_failed_refresh_preserves_old(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    _, operations, role_id, capability_id = _mapped_capability(root)
    research_input = operations.knowledge_research_input(role_id, capability_id)
    assert research_input["mode"] == "research"
    assert research_input["existing_knowledge"] is None
    payload = _knowledge_payload(research_input)

    personal_before = operations.storage.load_personal_states()
    practices_before = operations.storage.load_practices()
    operations.save_knowledge_result(
        role_id,
        capability_id,
        payload,
        expected_knowledge_sha256=None,
    )
    detail = operations.detail(role_id, capability_id)
    assert detail.knowledge.status_key == "available"
    assert detail.knowledge.value is not None
    assert detail.knowledge.value.capability_id.hex == capability_id.replace("-", "")
    assert len(detail.knowledge.value.level_criteria) == 6
    assert operations.storage.load_personal_states() == personal_before
    assert operations.storage.load_practices() == practices_before

    # Repeated import of the same generated result is idempotent.
    operations.save_knowledge_result(
        role_id,
        capability_id,
        payload,
        expected_knowledge_sha256=None,
    )
    knowledge_path = operations.storage.knowledge_root / f"{capability_id}.json"
    old_bytes = knowledge_path.read_bytes()
    with pytest.raises(ApplicationError):
        operations.save_knowledge_result(
            role_id,
            capability_id,
            "{malformed",
            expected_knowledge_sha256=detail.knowledge.expected_sha256,
        )
    assert knowledge_path.read_bytes() == old_bytes

    refresh_input = operations.knowledge_research_input(role_id, capability_id)
    assert refresh_input["mode"] == "refresh"
    assert refresh_input["existing_knowledge"] is not None
    refreshed = _knowledge_payload(
        refresh_input,
        generated_at="2026-09-10T13:00:00+08:00",
        topic="Async endpoints and dependency injection",
        level_prefix="Refreshed FastAPI",
    )
    refresh_token = operations.detail(role_id, capability_id).knowledge.expected_sha256
    operations.save_knowledge_result(
        role_id,
        capability_id,
        refreshed,
        expected_knowledge_sha256=refresh_token,
    )
    assert (
        operations.detail(role_id, capability_id).knowledge.value.core_topics[0].text
        == "Async endpoints and dependency injection"
    )
    assert operations.detail(
        role_id, capability_id
    ).knowledge.value.level_criteria[3].text.startswith("Refreshed FastAPI")
    assert list(operations.storage.knowledge_root.glob("*.json")) == [knowledge_path]
    refreshed_bytes = knowledge_path.read_bytes()
    stale_result = _knowledge_payload(
        operations.knowledge_research_input(role_id, capability_id),
        generated_at="2026-09-10T14:00:00+08:00",
        topic="A stale concurrent replacement",
    )
    with pytest.raises(ApplicationError, match="数据已变化"):
        operations.save_knowledge_result(
            role_id,
            capability_id,
            stale_result,
            expected_knowledge_sha256=refresh_token,
        )
    assert knowledge_path.read_bytes() == refreshed_bytes


def test_knowledge_is_global_reusable_and_default_queries_are_role_scoped(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    market, operations, role_a, capability_id = _mapped_capability(root)
    payload = _knowledge_payload(
        operations.knowledge_research_input(role_a, capability_id)
    )
    operations.save_knowledge_result(
        role_a,
        capability_id,
        payload,
        expected_knowledge_sha256=None,
    )

    role_b = _role_with_signals(market, "Python Backend", ["FastAPI"])
    workspace_b = operations.workspace(role_b)
    assert [item.capability_id for item in workspace_b.current_capabilities] == [
        capability_id
    ]
    assert workspace_b.current_capabilities[0].knowledge_status == "available"
    assert (
        operations.detail(role_b, capability_id).knowledge.value
        == operations.detail(role_a, capability_id).knowledge.value
    )

    role_c = _role_with_signals(market, "Java Backend", ["Spring Boot"])
    candidate_c = operations.workspace(role_c).pending_candidates[0]
    operations.add(
        role_c,
        candidate_c.candidate_fingerprint,
        "Spring Boot",
        expected_catalog_sha256=operations.workspace(role_c).catalog_sha256,
    )
    workspace_c = operations.workspace(role_c)
    assert [item.name for item in workspace_c.current_capabilities] == ["Spring Boot"]
    assert workspace_c.current_capabilities[0].knowledge_status == "missing"
    global_detail = operations.detail(role_c, capability_id)
    assert global_detail.in_current_role is False
    assert global_detail.knowledge.value is not None


def test_status_is_derived_and_result_anchor_must_match_current_capability(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    _, operations, role_id, capability_id = _mapped_capability(root)
    research_input = operations.knowledge_research_input(role_id, capability_id)
    payload = _knowledge_payload(research_input)
    operations.save_knowledge_result(
        role_id,
        capability_id,
        payload,
        expected_knowledge_sha256=None,
    )
    before = operations.storage.load_knowledge_snapshot(
        operations._uuid(capability_id, "capability_id")
    )

    raw = json.loads(payload)
    raw["capability_id"] = str(uuid4())
    with pytest.raises(ApplicationError, match="锚定"):
        operations.save_knowledge_result(
            role_id,
            capability_id,
            json.dumps(raw),
            expected_knowledge_sha256=before[1],
        )
    assert (
        operations.storage.load_knowledge_snapshot(
            operations._uuid(capability_id, "capability_id")
        )
        == before
    )

    operations.rename(
        role_id,
        capability_id,
        "FastAPI Engineering",
        expected_catalog_sha256=operations.workspace(role_id).catalog_sha256,
    )
    assert operations.detail(role_id, capability_id).knowledge.status_key == (
        "refresh-suggested"
    )
    current_input = operations.knowledge_research_input(role_id, capability_id)
    assert current_input["capability"]["input_fingerprint"] != raw["input_fingerprint"]


def test_minimum_knowledge_schema_and_new_path_have_no_workflow_truth() -> None:
    assert set(CapabilityKnowledge.model_fields) == {
        "capability_id",
        "prerequisites",
        "core_topics",
        "useful_practices",
        "acceptance_criteria",
        "level_criteria",
        "sources",
        "generated_at",
        "input_fingerprint",
    }
    prohibited = {
        "research_plan",
        "workflow_state",
        "readiness",
        "coverage",
        "freshness",
        "role_id",
        "domain",
        "concept",
        "specific_skill",
    }
    assert not prohibited & set(CapabilityKnowledge.model_fields)

    import application.capabilities as application_module
    import src.knowledge as knowledge_module

    source = inspect.getsource(application_module) + inspect.getsource(knowledge_module)
    assert not any(
        value in source.casefold()
        for value in (
            "research_plan",
            "workflow_state",
            "readiness",
            "coverage",
            "freshness",
            "taxonomy",
        )
    )

    skill = (
        Path(__file__).resolve().parents[1]
        / ".agents"
        / "skills"
        / "capability-knowledge-research"
        / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "system-prepared current capability" in skill.casefold()
    assert "level_criteria" in skill
    assert "do not assess or modify the user's level" in skill.casefold()
    assert "apply_semantic_handoff.py capability-knowledge-research" in skill
    assert "prepare_capability_research.py" not in skill
    assert "save_capability_knowledge.py" not in skill


def test_level_criteria_are_optional_as_fallback_but_reject_partial_scales(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    _, operations, role_id, capability_id = _mapped_capability(root)
    research_input = operations.knowledge_research_input(role_id, capability_id)
    payload = json.loads(_knowledge_payload(research_input))
    payload.pop("level_criteria")
    operations.save_knowledge_result(
        role_id,
        capability_id,
        json.dumps(payload),
        expected_knowledge_sha256=None,
    )
    assert operations.detail(role_id, capability_id).knowledge.value.level_criteria == []

    refresh = json.loads(
        _knowledge_payload(
            operations.knowledge_research_input(role_id, capability_id),
            generated_at="2026-09-10T13:00:00+08:00",
        )
    )
    refresh["level_criteria"] = refresh["level_criteria"][:5]
    before = operations.storage.load_knowledge(
        operations._uuid(capability_id, "capability_id")
    )
    with pytest.raises(ApplicationError, match="Level 0–5"):
        operations.save_knowledge_result(
            role_id,
            capability_id,
            json.dumps(refresh),
            expected_knowledge_sha256=operations.detail(
                role_id, capability_id
            ).knowledge.expected_sha256,
        )
    assert operations.storage.load_knowledge(
        operations._uuid(capability_id, "capability_id")
    ) == before
