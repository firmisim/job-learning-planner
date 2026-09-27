from __future__ import annotations

import json
from pathlib import Path

import pytest

from application.errors import ApplicationError
from application.capabilities import CapabilityOperations
from application.learning import LearningOperations
from application.market import MarketOperations
from application.roadmaps import RoadmapOperations
from schemas.core import RoadmapVersion
from tests.test_application_knowledge import _knowledge_payload, _mapped_capability
from tests.test_application_capabilities import _role_with_signals


def _ready_role(root: Path) -> tuple[RoadmapOperations, LearningOperations, str, str]:
    _, capabilities, role_id, capability_id = _mapped_capability(root)
    research_input = capabilities.knowledge_research_input(role_id, capability_id)
    capabilities.save_knowledge_result(
        role_id,
        capability_id,
        _knowledge_payload(research_input),
        expected_knowledge_sha256=None,
    )
    learning = LearningOperations(root)
    view = learning.view(role_id)
    learning.set_level(
        role_id,
        capability_id,
        1,
        expected_sha256=view.personal_states_sha256,
    )
    learning.add_practice(
        role_id,
        capability_id,
        "Built a validated request endpoint",
        expected_sha256=learning.view(role_id).practices_sha256,
    )
    return RoadmapOperations(root), learning, role_id, capability_id


def _result(fingerprint: str, content: str = "# Learning Roadmap\n\n- Build the next API") -> str:
    return json.dumps(
        {
            "schema_version": "1.0",
            "input_fingerprint": fingerprint,
            "content": content,
        }
    )


def _mapped_role_without_knowledge(
    root: Path, expressions: list[str]
) -> tuple[CapabilityOperations, str, dict[str, str]]:
    market = MarketOperations(root)
    role_id = _role_with_signals(market, "Graceful Role", expressions)
    capabilities = CapabilityOperations(root)
    ids: dict[str, str] = {}
    for expression in expressions:
        candidate = next(
            item
            for item in capabilities.workspace(role_id).pending_candidates
            if item.atomic_expression == expression
        )
        capabilities.add(
            role_id,
            candidate.candidate_fingerprint,
            expression,
            expected_catalog_sha256=capabilities.workspace(role_id).catalog_sha256,
        )
        ids[expression] = next(
            item.capability_id
            for item in capabilities.workspace(role_id).current_capabilities
            if item.name == expression
        )
    return capabilities, role_id, ids


def test_input_uses_only_current_market_knowledge_level_and_practice(
    tmp_path: Path,
) -> None:
    operations, _, role_id, capability_id = _ready_role(tmp_path / "state")
    payload = operations.generation_input(role_id)
    assert payload["role"]["role_id"] == role_id  # type: ignore[index]
    assert payload["market"]["analyzed_jd_count"] == 1  # type: ignore[index]
    capability = payload["capabilities"][0]  # type: ignore[index]
    assert capability["capability_id"] == capability_id
    assert capability["knowledge_status"] == "available"
    assert capability["current_level"] == 1
    assert capability["level_criteria"]["source"] == "capability-specific"
    assert capability["level_criteria"]["levels"][1]["criterion"].startswith(
        "FastAPI Level 1"
    )
    assert capability["practices"][0]["description"] == (
        "Built a validated request endpoint"
    )
    encoded = json.dumps(payload).casefold()
    for prohibited in (
        "target_level",
        "assessment",
        "learning_state",
        "practice_evidence",
        "progress",
        "roadmap_context",
        "readiness",
        "roadmap_stale",
    ):
        assert prohibited not in encoded


def test_roadmap_uses_generic_level_criteria_when_specific_are_absent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    _, capabilities, role_id, capability_id = _mapped_capability(root)
    research_input = capabilities.knowledge_research_input(role_id, capability_id)
    payload = json.loads(_knowledge_payload(research_input))
    payload.pop("level_criteria")
    capabilities.save_knowledge_result(
        role_id, capability_id, json.dumps(payload), expected_knowledge_sha256=None
    )

    capability = RoadmapOperations(root).generation_input(role_id)["capabilities"][0]
    assert capability["level_criteria"]["source"] == "generic"
    assert len(capability["level_criteria"]["levels"]) == 6
    assert capability["current_level"] is None


def test_partial_and_zero_knowledge_are_generation_ready_with_explicit_inputs(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    capabilities, role_id, ids = _mapped_role_without_knowledge(
        root, ["FastAPI", "Docker"]
    )
    learning = LearningOperations(root)
    learning.set_level(
        role_id,
        ids["Docker"],
        2,
        expected_sha256=learning.view(role_id).personal_states_sha256,
    )
    learning.add_practice(
        role_id,
        ids["Docker"],
        "Built one container image",
        expected_sha256=learning.view(role_id).practices_sha256,
    )
    roadmaps = RoadmapOperations(root)

    zero = roadmaps.view(role_id)
    assert zero.can_generate is True
    assert zero.relevant_capability_count == 2
    assert zero.knowledge_ready_count == 0
    assert zero.knowledge_missing_count == 2
    missing = {
        item["name"]: item for item in roadmaps.generation_input(role_id)["capabilities"]
    }
    assert set(missing) == {"FastAPI", "Docker"}
    assert all(item["guidance_mode"] == "research-needed" for item in missing.values())
    assert all(item["knowledge"] is None for item in missing.values())
    assert missing["Docker"]["current_level"] == 2
    assert missing["Docker"]["practices"][0]["description"] == (
        "Built one container image"
    )
    assert missing["Docker"]["market"]["evidence"]

    research_input = capabilities.knowledge_research_input(
        role_id, ids["FastAPI"]
    )
    capabilities.save_knowledge_result(
        role_id,
        ids["FastAPI"],
        _knowledge_payload(research_input),
        expected_knowledge_sha256=None,
    )
    partial = roadmaps.view(role_id)
    assert partial.can_generate is True
    assert partial.knowledge_ready_count == 1
    assert partial.knowledge_missing_count == 1
    inputs = {
        item["name"]: item for item in roadmaps.generation_input(role_id)["capabilities"]
    }
    assert inputs["FastAPI"]["guidance_mode"] == "knowledge-ready"
    assert inputs["FastAPI"]["knowledge"] is not None
    assert inputs["FastAPI"]["level_criteria"]["source"] == (
        "capability-specific"
    )
    assert inputs["Docker"]["guidance_mode"] == "research-needed"


def test_readiness_still_requires_market_analysis_and_a_mapped_capability(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    market = MarketOperations(root)
    role_id, _ = market.create_role("Unanalyzed", market.view().roles_sha256)
    market.add_job(
        role_id,
        title="Backend",
        company=None,
        jd_text="FastAPI",
        source_url=None,
        expected_sha256=market.view(role_id).jds_sha256 or "",
    )
    unanalyzed = RoadmapOperations(root).view(role_id)
    assert unanalyzed.can_generate is False
    assert any("Analyze at least one" in label for label, _ in unanalyzed.blockers)

    analyzed_role = _role_with_signals(market, "Analyzed", ["Docker"])
    unmapped = RoadmapOperations(root).view(analyzed_role)
    assert unmapped.can_generate is False
    assert any("Map at least one" in label for label, _ in unmapped.blockers)


def test_skipped_and_unmapped_signals_do_not_reenter_roadmap_input(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    market = MarketOperations(root)
    role_id = _role_with_signals(
        market, "Boundaries", ["Mapped", "Skipped", "Unmapped"]
    )
    capabilities = CapabilityOperations(root)
    mapped = next(
        item
        for item in capabilities.workspace(role_id).pending_candidates
        if item.atomic_expression == "Mapped"
    )
    capabilities.add(
        role_id,
        mapped.candidate_fingerprint,
        "Mapped",
        expected_catalog_sha256=capabilities.workspace(role_id).catalog_sha256,
    )
    skipped = next(
        item
        for item in capabilities.workspace(role_id).pending_candidates
        if item.atomic_expression == "Skipped"
    )
    capabilities.skip(
        role_id,
        skipped.candidate_fingerprint,
        expected_skipped_sha256=capabilities.workspace(role_id).skipped_sha256 or "",
    )

    roadmap_input = RoadmapOperations(root).generation_input(role_id)
    assert [item["name"] for item in roadmap_input["capabilities"]] == ["Mapped"]
    assert {item["atomic_expression"] for item in roadmap_input["market"]["atomic_signals"]} == {
        "Mapped",
        "Skipped",
        "Unmapped",
    }


def test_roadmap_skill_limits_formal_learning_to_mapped_capabilities() -> None:
    repository = Path(__file__).resolve().parents[1]
    skill = (
        repository / ".agents" / "skills" / "job-learning-roadmap" / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "authoritative and exhaustive for formal learning content" in skill
    assert (
        "Market Signal → SourceMapping → Capability → Selected for Roadmap" in skill
    )
    assert "market-only, unmapped, skipped" in skill
    assert "Never turn one into a formal learning item" in skill
    assert "recreate a Capability the user skipped" in skill
    assert "reintroduce a Capability absent from `capabilities`" in skill
    assert "Knowledge and `guidance_mode` continue to control" in skill


def test_roadmap_skill_freezes_learning_map_progression_contract() -> None:
    skill = (
        Path(__file__).resolve().parents[1]
        / ".agents"
        / "skills"
        / "job-learning-roadmap"
        / "SKILL.md"
    ).read_text(encoding="utf-8")

    for contract in (
        "compact Learning Map and coarse learning waves",
        "more actionable, detailed, and practice-oriented guidance",
        "strong foundation may support later learning without consuming a major new learning stage",
        "allow parallel or largely independent learning",
        "Do not invent hard prerequisites merely to create a neat sequence",
        "Do not output importance scores, weights, ranks, P0/P1/P2",
        "must not fabricate prerequisites, topics, Practice, or mastery content",
    ):
        assert contract in skill


def _set_scope(
    learning: LearningOperations,
    role_id: str,
    capability_id: str,
    included: bool,
) -> None:
    learning.set_roadmap_inclusion(
        role_id,
        capability_id,
        included,
        expected_sha256=learning.view(role_id).roadmap_scope_sha256,
    )


def test_effective_scope_filters_before_fact_collection_and_defaults_to_all(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    _, role_id, ids = _mapped_role_without_knowledge(root, ["Alpha", "Beta"])
    roadmaps = RoadmapOperations(root)
    learning = LearningOperations(root)

    default_input = roadmaps.generation_input(role_id)
    assert [item["name"] for item in default_input["capabilities"]] == [
        "Alpha",
        "Beta",
    ]
    assert set(default_input) == {
        "schema_version",
        "role",
        "market",
        "capabilities",
        "input_fingerprint",
    }
    default_view = roadmaps.view(role_id)
    assert default_view.relevant_capability_count == 2
    assert default_view.selected_capability_count == 2

    _set_scope(learning, role_id, ids["Beta"], False)
    scoped = roadmaps.generation_input(role_id)
    assert [item["name"] for item in scoped["capabilities"]] == ["Alpha"]
    assert scoped["input_fingerprint"] != default_input["input_fingerprint"]
    scoped_view = roadmaps.view(role_id)
    assert scoped_view.relevant_capability_count == 2
    assert scoped_view.selected_capability_count == 1

    _set_scope(learning, role_id, ids["Beta"], True)
    restored = roadmaps.generation_input(role_id)
    assert [item["name"] for item in restored["capabilities"]] == ["Alpha", "Beta"]
    assert restored["input_fingerprint"] == default_input["input_fingerprint"]


def test_new_mapping_defaults_to_selected_and_changes_fingerprint(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    market = MarketOperations(root)
    role_id = _role_with_signals(market, "Expanding", ["Alpha", "Beta"])
    capabilities = CapabilityOperations(root)
    alpha = next(
        item
        for item in capabilities.workspace(role_id).pending_candidates
        if item.atomic_expression == "Alpha"
    )
    capabilities.add(
        role_id,
        alpha.candidate_fingerprint,
        "Alpha",
        expected_catalog_sha256=capabilities.workspace(role_id).catalog_sha256,
    )
    roadmaps = RoadmapOperations(root)
    before = roadmaps.generation_input(role_id)
    beta = next(
        item
        for item in capabilities.workspace(role_id).pending_candidates
        if item.atomic_expression == "Beta"
    )
    capabilities.add(
        role_id,
        beta.candidate_fingerprint,
        "Beta",
        expected_catalog_sha256=capabilities.workspace(role_id).catalog_sha256,
    )
    after = roadmaps.generation_input(role_id)

    assert [item["name"] for item in before["capabilities"]] == ["Alpha"]
    assert [item["name"] for item in after["capabilities"]] == ["Alpha", "Beta"]
    assert after["input_fingerprint"] != before["input_fingerprint"]


def test_excluded_facts_do_not_change_fingerprint_but_included_facts_do(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    capabilities, role_id, ids = _mapped_role_without_knowledge(
        root, ["Included", "Excluded"]
    )
    learning = LearningOperations(root)
    roadmaps = RoadmapOperations(root)
    _set_scope(learning, role_id, ids["Excluded"], False)
    initial = roadmaps.generation_input(role_id)["input_fingerprint"]

    excluded_input = capabilities.knowledge_research_input(role_id, ids["Excluded"])
    capabilities.save_knowledge_result(
        role_id,
        ids["Excluded"],
        _knowledge_payload(excluded_input),
        expected_knowledge_sha256=None,
    )
    assert roadmaps.generation_input(role_id)["input_fingerprint"] == initial
    learning.set_level(
        role_id,
        ids["Excluded"],
        2,
        expected_sha256=learning.view(role_id).personal_states_sha256,
    )
    assert roadmaps.generation_input(role_id)["input_fingerprint"] == initial
    learning.add_practice(
        role_id,
        ids["Excluded"],
        "Excluded practice",
        expected_sha256=learning.view(role_id).practices_sha256,
    )
    assert roadmaps.generation_input(role_id)["input_fingerprint"] == initial

    included_input = capabilities.knowledge_research_input(role_id, ids["Included"])
    capabilities.save_knowledge_result(
        role_id,
        ids["Included"],
        _knowledge_payload(included_input),
        expected_knowledge_sha256=None,
    )
    after_knowledge = roadmaps.generation_input(role_id)["input_fingerprint"]
    assert after_knowledge != initial
    learning.set_level(
        role_id,
        ids["Included"],
        3,
        expected_sha256=learning.view(role_id).personal_states_sha256,
    )
    after_level = roadmaps.generation_input(role_id)["input_fingerprint"]
    assert after_level != after_knowledge
    learning.add_practice(
        role_id,
        ids["Included"],
        "Included practice",
        expected_sha256=learning.view(role_id).practices_sha256,
    )
    assert roadmaps.generation_input(role_id)["input_fingerprint"] != after_level


def test_scope_change_stales_handoff_while_excluded_mutation_does_not(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    _, role_id, ids = _mapped_role_without_knowledge(root, ["Alpha", "Beta"])
    learning = LearningOperations(root)
    roadmaps = RoadmapOperations(root)
    roadmaps.prepare_generation(role_id)
    prepared = roadmaps.handoffs.load_request("job-learning-roadmap")["input"]
    assert isinstance(prepared, dict)
    _set_scope(learning, role_id, ids["Beta"], False)
    with pytest.raises(ApplicationError, match="过期"):
        roadmaps.save_result(
            role_id, _result(str(prepared["input_fingerprint"]), "# Stale")
        )

    selected_input = roadmaps.generation_input(role_id)
    learning.set_level(
        role_id,
        ids["Beta"],
        4,
        expected_sha256=learning.view(role_id).personal_states_sha256,
    )
    assert roadmaps.generation_input(role_id)["input_fingerprint"] == (
        selected_input["input_fingerprint"]
    )
    roadmaps.save_result(
        role_id, _result(str(selected_input["input_fingerprint"]), "# Current")
    )


def test_zero_selected_blocks_generation_but_preserves_history_actions(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    _, role_id, ids = _mapped_role_without_knowledge(root, ["Alpha"])
    learning = LearningOperations(root)
    roadmaps = RoadmapOperations(root)
    fingerprint = str(roadmaps.generation_input(role_id)["input_fingerprint"])
    roadmaps.save_result(role_id, _result(fingerprint, "# Retained"))
    roadmap_id = roadmaps.view(role_id).history[0].roadmap_id

    _set_scope(learning, role_id, ids["Alpha"], False)
    blocked = roadmaps.view(role_id)
    assert blocked.can_generate is False
    assert blocked.relevant_capability_count == 1
    assert blocked.selected_capability_count == 0
    assert blocked.history[0].roadmap_id == roadmap_id
    assert any("Include at least one" in label for label, _ in blocked.blockers)
    with pytest.raises(ApplicationError):
        roadmaps.prepare_generation(role_id)
    assert "Retained" in roadmaps.detail(role_id, roadmap_id).html
    _, exported = roadmaps.export_markdown(role_id, roadmap_id)
    assert exported == b"# Retained"
    roadmaps.delete(role_id, roadmap_id)
    assert roadmaps.view(role_id).history == ()


def test_knowledge_completion_changes_fingerprint_and_appends_history(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    capabilities, role_id, ids = _mapped_role_without_knowledge(root, ["FastAPI"])
    roadmaps = RoadmapOperations(root)
    first_fingerprint = str(roadmaps.generation_input(role_id)["input_fingerprint"])
    roadmaps.save_result(role_id, _result(first_fingerprint, "# Provisional v1"))
    first_version = roadmaps.storage.list_roadmaps(
        roadmaps._uuid(role_id, "role_id")
    )[0]

    research_input = capabilities.knowledge_research_input(
        role_id, ids["FastAPI"]
    )
    capabilities.save_knowledge_result(
        role_id,
        ids["FastAPI"],
        _knowledge_payload(research_input),
        expected_knowledge_sha256=None,
    )
    second_fingerprint = str(roadmaps.generation_input(role_id)["input_fingerprint"])
    assert second_fingerprint != first_fingerprint
    assert roadmaps.view(role_id).state_key == "changed"
    roadmaps.save_result(role_id, _result(second_fingerprint, "# Supported v2"))

    versions = roadmaps.storage.list_roadmaps(roadmaps._uuid(role_id, "role_id"))
    assert len(versions) == 2
    assert versions[0] == first_version
    assert versions[0].content == "# Provisional v1"
    assert versions[1].content == "# Supported v2"


def test_fingerprint_tracks_all_roadmap_inputs_and_not_history(tmp_path: Path) -> None:
    root = tmp_path / "state"
    operations, learning, role_id, capability_id = _ready_role(root)
    first = operations.generation_input(role_id)["input_fingerprint"]
    operations.save_result(role_id, _result(str(first)))
    assert operations.generation_input(role_id)["input_fingerprint"] == first

    learning.set_level(
        role_id,
        capability_id,
        2,
        expected_sha256=learning.view(role_id).personal_states_sha256,
    )
    second = operations.generation_input(role_id)["input_fingerprint"]
    assert second != first
    learning.add_practice(
        role_id,
        capability_id,
        "Added failure-case tests",
        expected_sha256=learning.view(role_id).practices_sha256,
    )
    assert operations.generation_input(role_id)["input_fingerprint"] != second


def test_generate_regenerate_history_and_failed_generation_safety(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    operations, learning, role_id, capability_id = _ready_role(root)
    fingerprint = str(operations.generation_input(role_id)["input_fingerprint"])
    operations.save_result(role_id, _result(fingerprint, "# Version one"))
    current = operations.view(role_id)
    assert current.state_key == "current"
    assert len(current.history) == 1
    assert "Version one" in operations.detail(
        role_id, current.history[0].roadmap_id
    ).html

    before_files = list((root / "roles" / role_id / "roadmaps").glob("*.json"))
    with pytest.raises(ApplicationError):
        operations.save_result(role_id, "{}")
    with pytest.raises(ApplicationError, match="过期"):
        operations.save_result(role_id, _result("0" * 64, "# Invalid"))
    assert list((root / "roles" / role_id / "roadmaps").glob("*.json")) == before_files
    assert "Version one" in operations.detail(
        role_id, current.history[0].roadmap_id
    ).html

    learning.set_level(
        role_id,
        capability_id,
        3,
        expected_sha256=learning.view(role_id).personal_states_sha256,
    )
    changed = operations.view(role_id)
    assert changed.state_key == "changed"
    next_fingerprint = str(
        operations.generation_input(role_id)["input_fingerprint"]
    )
    operations.save_result(role_id, _result(next_fingerprint, "# Version two"))
    final = operations.view(role_id)
    assert len(final.history) == 2
    assert final.history[0].latest is True
    assert "Version two" in operations.detail(
        role_id, final.history[0].roadmap_id
    ).html
    historical_id = final.history[1].roadmap_id
    historical = operations.detail(role_id, historical_id)
    assert historical.latest is False
    assert "Version one" in historical.html


def test_roadmap_history_is_role_specific(tmp_path: Path) -> None:
    root = tmp_path / "state"
    operations, _, role_a, _ = _ready_role(root)
    fingerprint = str(operations.generation_input(role_a)["input_fingerprint"])
    operations.save_result(role_a, _result(fingerprint))
    role_b = operations.storage.create_role("Other Role")
    assert operations.storage.list_roadmaps(role_b.role_id) == []
    with pytest.raises(ApplicationError):
        operations.detail(
            str(role_b.role_id), operations.view(role_a).history[0].roadmap_id
        )


def test_roadmap_version_remains_minimal() -> None:
    assert set(RoadmapVersion.model_fields) == {
        "roadmap_id",
        "role_id",
        "generated_at",
        "input_fingerprint",
        "content",
    }

    skill = (
        Path(__file__).resolve().parents[1]
        / ".agents"
        / "skills"
        / "job-learning-roadmap"
        / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "applicable generic or Capability-specific Level 0–5 criteria" in skill
    assert "do not invent a proficiency scale, score, target level" in skill.casefold()
    assert "`knowledge-ready`" in skill
    assert "`research-needed`" in skill
    assert "do not supply prerequisites, core topics, libraries" in skill.casefold()
