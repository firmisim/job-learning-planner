from __future__ import annotations

import json
from pathlib import Path

import pytest

from application.capabilities import CapabilityOperations
from application.errors import ApplicationError
from application.market import MarketOperations
from application.roadmaps import RoadmapOperations
from scripts.apply_semantic_handoff import apply
from scripts.prepare_knowledge_batch import prepare
from tests.test_application_capabilities import _role_with_signals
from tests.test_application_knowledge import _knowledge_payload


def _mapped_missing(
    root: Path, role_name: str, count: int
) -> tuple[CapabilityOperations, str, list[str]]:
    market = MarketOperations(root)
    expressions = [f"{role_name} Capability {index:02d}" for index in range(count)]
    role_id = _role_with_signals(market, role_name, expressions)
    operations = CapabilityOperations(root)
    for expression in expressions:
        candidate = next(
            item
            for item in operations.workspace(role_id).pending_candidates
            if item.atomic_expression == expression
        )
        operations.add(
            role_id,
            candidate.candidate_fingerprint,
            expression,
            expected_catalog_sha256=operations.workspace(role_id).catalog_sha256,
        )
    return (
        operations,
        role_id,
        [item.capability_id for item in operations.workspace(role_id).current_capabilities],
    )


def _batch_results(request: dict[str, object]) -> list[dict[str, object]]:
    batch_input = request["input"]
    assert isinstance(batch_input, dict)
    capabilities = batch_input["capabilities"]
    assert isinstance(capabilities, list)
    return [json.loads(_knowledge_payload(item)) for item in capabilities]


def test_prepare_selected_and_all_are_role_scoped_missing_only(tmp_path: Path) -> None:
    root = tmp_path / "state"
    operations, role_a, ids_a = _mapped_missing(root, "Role A", 6)
    _, _, ids_b = _mapped_missing(root, "Role B", 1)
    researched_input = operations.knowledge_research_input(role_a, ids_a[0])
    operations.save_knowledge_result(
        role_a,
        ids_a[0],
        _knowledge_payload(researched_input),
        expected_knowledge_sha256=None,
    )

    message = operations.prepare_knowledge_batch(role_a, ids_a[1:4])
    assert "3 个 Capability" in message
    manifest, _ = operations.knowledge_batches.load_snapshot()
    assert manifest is not None
    assert manifest["role"]["role_id"] == role_a
    assert [item["capability_id"] for item in manifest["selected"]] == ids_a[1:4]
    assert manifest["batches"] == [ids_a[1:4]]

    with pytest.raises(ApplicationError, match="当前 Role"):
        operations.prepare_knowledge_batch(role_a, [ids_b[0]])
    with pytest.raises(ApplicationError, match="尚无 Knowledge"):
        operations.prepare_knowledge_batch(role_a, [ids_a[0]])

    operations.prepare_knowledge_batch(role_a)
    replaced, _ = operations.knowledge_batches.load_snapshot()
    assert replaced is not None
    selected = [item["capability_id"] for item in replaced["selected"]]
    assert selected == ids_a[1:]
    assert ids_a[0] not in selected
    assert ids_b[0] not in selected
    assert [len(batch) for batch in replaced["batches"]] == [4, 1]


@pytest.mark.parametrize(
    ("count", "expected_sizes"),
    [(1, [1]), (4, [4]), (5, [4, 1]), (9, [4, 4, 1])],
)
def test_fixed_deterministic_batch_boundaries(
    tmp_path: Path, count: int, expected_sizes: list[int]
) -> None:
    root = tmp_path / f"state-{count}"
    operations, role_id, ids = _mapped_missing(root, f"Role {count}", count)
    operations.prepare_knowledge_batch(role_id)
    manifest, _ = operations.knowledge_batches.load_snapshot()
    assert manifest is not None
    assert manifest["batch_size"] == 4
    assert [len(batch) for batch in manifest["batches"]] == expected_sizes
    assert [item for batch in manifest["batches"] for item in batch] == ids


def test_empty_selection_does_not_create_a_batch(tmp_path: Path) -> None:
    root = tmp_path / "state"
    operations, role_id, _ = _mapped_missing(root, "Empty selection", 1)
    with pytest.raises(ApplicationError, match="没有可准备"):
        operations.prepare_knowledge_batch(role_id, [])
    assert operations.knowledge_batches.load_snapshot() == (None, None)


def test_prepare_all_excludes_skipped_and_unmapped_signals(tmp_path: Path) -> None:
    root = tmp_path / "state"
    market = MarketOperations(root)
    role_id = _role_with_signals(market, "Bounded", ["Mapped", "Skipped", "Unmapped"])
    operations = CapabilityOperations(root)
    mapped = next(
        item
        for item in operations.workspace(role_id).pending_candidates
        if item.atomic_expression == "Mapped"
    )
    operations.add(
        role_id,
        mapped.candidate_fingerprint,
        "Mapped",
        expected_catalog_sha256=operations.workspace(role_id).catalog_sha256,
    )
    skipped = next(
        item
        for item in operations.workspace(role_id).pending_candidates
        if item.atomic_expression == "Skipped"
    )
    operations.skip(
        role_id,
        skipped.candidate_fingerprint,
        expected_skipped_sha256=operations.workspace(role_id).skipped_sha256 or "",
    )

    operations.prepare_knowledge_batch(role_id)
    manifest, _ = operations.knowledge_batches.load_snapshot()
    assert manifest is not None
    assert [item["canonical_name"] for item in manifest["selected"]] == ["Mapped"]


def test_one_run_applies_one_batch_with_partial_success_and_prepares_next(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    operations, role_id, ids = _mapped_missing(root, "Partial", 5)
    roadmaps = RoadmapOperations(root)
    assert roadmaps.view(role_id).can_generate is True
    before_fingerprint = roadmaps.generation_input(role_id)["input_fingerprint"]
    operations.prepare_knowledge_batch(role_id)
    request = operations.handoffs.load_request("capability-knowledge-research")
    assert request["input"]["mode"] == "batch"
    assert len(request["input"]["capabilities"]) == 4
    results = _batch_results(request)
    results[1]["level_criteria"] = results[1]["level_criteria"][:2]
    operations.handoffs.draft_path("capability-knowledge-research").write_text(
        json.dumps({"results": results}), encoding="utf-8"
    )

    message = apply("capability-knowledge-research", root)
    assert "3 项成功，1 项失败" in message
    assert operations.detail(role_id, ids[0]).knowledge.value is not None
    assert operations.detail(role_id, ids[1]).knowledge.value is None
    assert operations.detail(role_id, ids[2]).knowledge.value is not None
    assert operations.detail(role_id, ids[3]).knowledge.value is not None
    assert operations.detail(role_id, ids[4]).knowledge.value is None
    assert roadmaps.view(role_id).can_generate is True
    assert roadmaps.generation_input(role_id)["input_fingerprint"] != before_fingerprint

    manifest, _ = operations.knowledge_batches.load_snapshot()
    assert manifest is not None
    assert manifest["next_batch_index"] == 1
    assert set(manifest["failed_items"]) == {ids[1]}
    next_request = operations.handoffs.load_request("capability-knowledge-research")
    assert next_request["input"]["batch_index"] == 1
    assert [
        item["capability"]["capability_id"]
        for item in next_request["input"]["capabilities"]
    ] == [ids[4]]


def test_retry_failed_excludes_successes_and_can_finish(tmp_path: Path) -> None:
    root = tmp_path / "state"
    operations, role_id, ids = _mapped_missing(root, "Retry", 2)
    operations.prepare_knowledge_batch(role_id)
    request = operations.handoffs.load_request("capability-knowledge-research")
    results = _batch_results(request)
    results[1].pop("sources")
    operations.handoffs.draft_path("capability-knowledge-research").write_text(
        json.dumps({"results": results}), encoding="utf-8"
    )
    apply("capability-knowledge-research", root)

    operations.retry_failed_knowledge_batch(role_id)
    retry_manifest, _ = operations.knowledge_batches.load_snapshot()
    assert retry_manifest is not None
    assert [item["capability_id"] for item in retry_manifest["selected"]] == [ids[1]]
    retry_request = operations.handoffs.load_request("capability-knowledge-research")
    operations.handoffs.draft_path("capability-knowledge-research").write_text(
        json.dumps({"results": _batch_results(retry_request)}), encoding="utf-8"
    )
    apply("capability-knowledge-research", root)

    view = operations.workspace(role_id).knowledge_batch
    assert view is not None
    assert view.succeeded == 1
    assert view.failed == 0
    assert view.remaining == 0
    assert operations.detail(role_id, ids[0]).knowledge.value is not None
    assert operations.detail(role_id, ids[1]).knowledge.value is not None


def test_pre_execution_recheck_skips_already_researched_item(tmp_path: Path) -> None:
    root = tmp_path / "state"
    operations, role_id, ids = _mapped_missing(root, "Recheck", 2)
    operations.prepare_knowledge_batch(role_id)
    first_input = operations.knowledge_research_input(role_id, ids[0])
    operations.save_knowledge_result(
        role_id,
        ids[0],
        _knowledge_payload(first_input),
        expected_knowledge_sha256=None,
    )

    assert "第 1 / 1 批已准备" in prepare(root)
    request = operations.handoffs.load_request("capability-knowledge-research")
    assert [
        item["capability"]["capability_id"] for item in request["input"]["capabilities"]
    ] == [ids[1]]


def test_single_research_can_run_during_a_prepared_batch(tmp_path: Path) -> None:
    root = tmp_path / "state"
    operations, role_id, ids = _mapped_missing(root, "Single", 2)
    operations.prepare_knowledge_batch(role_id)
    operations.prepare_knowledge_research(role_id, ids[0])
    assert prepare(root) == "SINGLE_KNOWLEDGE_REQUEST_READY"
    request = operations.handoffs.load_request("capability-knowledge-research")
    assert request["input"]["mode"] == "research"
    operations.handoffs.draft_path("capability-knowledge-research").write_text(
        _knowledge_payload(request["input"]), encoding="utf-8"
    )
    apply("capability-knowledge-research", root)

    resumed = operations.handoffs.load_request("capability-knowledge-research")
    assert resumed["input"]["mode"] == "batch"
    assert [
        item["capability"]["capability_id"]
        for item in resumed["input"]["capabilities"]
    ] == [ids[1]]


def test_skill_contract_keeps_single_and_one_batch_modes() -> None:
    skill = (
        Path(__file__).resolve().parents[1]
        / ".agents"
        / "skills"
        / "capability-knowledge-research"
        / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "`research`, `refresh`, or `batch`" in skill
    assert "one fixed batch of at most four" in skill
    assert "must stop after applying this one batch" in skill
    assert "valid items remain saved when another item fails" in skill
    assert "include refresh items" in skill
