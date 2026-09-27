from __future__ import annotations

import json
from pathlib import Path

import pytest

from application.capabilities import CapabilityOperations
from application.errors import ApplicationError
from application.market import MarketOperations
from scripts.apply_semantic_handoff import apply
from scripts.prepare_capability_analysis_batch import prepare
from tests.test_application_capabilities import _role_with_signals


def _pending(
    root: Path, role_name: str, count: int
) -> tuple[CapabilityOperations, str, list[str]]:
    market = MarketOperations(root)
    expressions = [f"{role_name} Candidate {index:02d}" for index in range(count)]
    role_id = _role_with_signals(market, role_name, expressions)
    operations = CapabilityOperations(root)
    fingerprints = [
        item.candidate_fingerprint
        for item in operations.workspace(role_id).pending_candidates
    ]
    return operations, role_id, fingerprints


def _recommendation(item: dict[str, object]) -> dict[str, object]:
    candidate = item["candidate"]
    assert isinstance(candidate, dict)
    evidence = candidate["evidence"]
    assert isinstance(evidence, list) and evidence
    first = evidence[0]
    assert isinstance(first, dict)
    return {
        "candidate_fingerprint": candidate["candidate_fingerprint"],
        "explanation": "A candidate drawn from the supplied JD evidence.",
        "learning_value": "The user should decide whether to retain it.",
        "recommended_action": "skip",
        "recommended_canonical_name": None,
        "recommended_merge_target": None,
        "rationale": "The supplied evidence is too narrow for a reusable object.",
        "evidence_quotes": [first["evidence"]],
    }


def _batch_results(request: dict[str, object]) -> list[dict[str, object]]:
    input_payload = request["input"]
    assert isinstance(input_payload, dict)
    candidates = input_payload["candidates"]
    assert isinstance(candidates, list)
    return [_recommendation(item) for item in candidates]


def test_selected_and_all_include_only_current_role_unanalyzed_candidates(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    operations, role_a, fingerprints = _pending(root, "Role A", 4)
    _, role_b, role_b_fingerprints = _pending(root, "Role B", 1)

    first = operations.inbox(role_a, fingerprints[0])
    recommendation = operations._validate_recommendation(
        first.workspace,
        first.candidate,
        json.dumps(_recommendation(operations._recommendation_input(first))),
        merge_target_names={item.name for item in first.merge_candidates},
    )
    operations.analysis_batches.save_recommendation(recommendation)
    operations.add(
        role_a,
        fingerprints[3],
        "Resolved Exact Capability",
        expected_catalog_sha256=operations.workspace(role_a).catalog_sha256,
    )

    message = operations.prepare_capability_analysis_batch(
        role_a, fingerprints[1:3]
    )
    assert "2 个 Candidate" in message
    manifest, _ = operations.analysis_batches.load_manifest()
    assert manifest is not None
    assert manifest["role"]["role_id"] == role_a
    assert [
        item["candidate_fingerprint"] for item in manifest["selected"]
    ] == fingerprints[1:3]

    with pytest.raises(ApplicationError, match="当前 Role"):
        operations.prepare_capability_analysis_batch(
            role_a, [role_b_fingerprints[0]]
        )
    with pytest.raises(ApplicationError, match="尚无 Recommendation"):
        operations.prepare_capability_analysis_batch(role_a, [fingerprints[0]])

    operations.prepare_capability_analysis_batch(role_a)
    replaced, _ = operations.analysis_batches.load_manifest()
    assert replaced is not None
    selected = [
        item["candidate_fingerprint"] for item in replaced["selected"]
    ]
    assert selected == fingerprints[1:3]
    assert fingerprints[0] not in selected
    assert fingerprints[3] not in selected
    assert role_b_fingerprints[0] not in selected


@pytest.mark.parametrize(
    ("count", "expected_sizes"),
    [(1, [1]), (20, [20]), (21, [20, 1]), (41, [20, 20, 1])],
)
def test_capability_analysis_uses_fixed_deterministic_batch_boundaries(
    tmp_path: Path, count: int, expected_sizes: list[int]
) -> None:
    root = tmp_path / f"state-{count}"
    operations, role_id, fingerprints = _pending(root, f"Batch {count}", count)
    operations.prepare_capability_analysis_batch(role_id)
    manifest, _ = operations.analysis_batches.load_manifest()
    assert manifest is not None
    assert manifest["batch_size"] == 20
    assert [len(batch) for batch in manifest["batches"]] == expected_sizes
    assert [item for batch in manifest["batches"] for item in batch] == fingerprints


def test_empty_selection_does_not_create_manifest(tmp_path: Path) -> None:
    root = tmp_path / "state"
    operations, role_id, _ = _pending(root, "Empty", 1)
    with pytest.raises(ApplicationError, match="没有可准备"):
        operations.prepare_capability_analysis_batch(role_id, [])
    assert operations.analysis_batches.load_manifest() == (None, None)


def test_one_run_applies_one_batch_with_partial_success_and_retry(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    operations, role_id, fingerprints = _pending(root, "Partial", 3)
    operations.prepare_capability_analysis_batch(role_id)
    request = operations.handoffs.load_request("capability-analysis")
    assert request["input"]["mode"] == "batch"
    results = _batch_results(request)
    results[1]["evidence_quotes"] = ["not supplied evidence"]
    operations.handoffs.draft_path("capability-analysis").write_text(
        json.dumps({"results": results}), encoding="utf-8"
    )

    message = apply("capability-analysis", root)
    assert "2 项 Recommendation 成功，1 项失败" in message
    cached = operations.analysis_batches.load_recommendations()
    assert set(cached) == {fingerprints[0], fingerprints[2]}
    assert len(operations.workspace(role_id).pending_candidates) == 3
    assert not operations.storage.load_catalog().source_mappings

    manifest, _ = operations.analysis_batches.load_manifest()
    assert manifest is not None
    assert manifest["next_batch_index"] == 1
    assert set(manifest["failed_items"]) == {fingerprints[1]}

    operations.retry_failed_capability_analysis_batch(role_id)
    retry, _ = operations.analysis_batches.load_manifest()
    assert retry is not None
    assert [
        item["candidate_fingerprint"] for item in retry["selected"]
    ] == [fingerprints[1]]
    retry_request = operations.handoffs.load_request("capability-analysis")
    operations.handoffs.draft_path("capability-analysis").write_text(
        json.dumps({"results": _batch_results(retry_request)}), encoding="utf-8"
    )
    apply("capability-analysis", root)
    assert set(operations.analysis_batches.load_recommendations()) == set(
        fingerprints
    )


def test_later_batch_recomputes_recall_from_latest_source_mapping(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    expressions = ["A Seed Candidate"]
    expressions.extend(f"Middle Candidate {index:02d}" for index in range(19))
    expressions.append("Z Shared-Platform tooling")
    market = MarketOperations(root)
    role_id = _role_with_signals(market, "Changing Catalog", expressions)
    operations = CapabilityOperations(root)
    pending = operations.workspace(role_id).pending_candidates
    operations.prepare_capability_analysis_batch(role_id)
    first_request = operations.handoffs.load_request("capability-analysis")
    first_inputs = first_request["input"]["candidates"]
    assert isinstance(first_inputs, list) and len(first_inputs) == 20
    operations.handoffs.draft_path("capability-analysis").write_text(
        json.dumps({"results": _batch_results(first_request)}), encoding="utf-8"
    )
    apply("capability-analysis", root)

    source = next(item for item in pending if item.atomic_expression == "A Seed Candidate")
    operations.add(
        role_id,
        source.candidate_fingerprint,
        "Shared Platform",
        expected_catalog_sha256=operations.workspace(role_id).catalog_sha256,
    )
    prepare(root)
    later = operations.handoffs.load_request("capability-analysis")
    later_inputs = later["input"]["candidates"]
    assert isinstance(later_inputs, list) and len(later_inputs) == 1
    assert later_inputs[0]["candidate"]["atomic_expression"] == (
        "Z Shared-Platform tooling"
    )
    assert later_inputs[0]["merge_candidates"][0]["name"] == "Shared Platform"
    assert "existing_capabilities" not in later_inputs[0]
    assert len(later_inputs[0]["merge_candidates"]) <= 5


def test_execution_recheck_skips_resolved_candidate(tmp_path: Path) -> None:
    root = tmp_path / "state"
    operations, role_id, fingerprints = _pending(root, "Resolved", 1)
    operations.prepare_capability_analysis_batch(role_id)
    operations.add(
        role_id,
        fingerprints[0],
        "Resolved Candidate",
        expected_catalog_sha256=operations.workspace(role_id).catalog_sha256,
    )

    assert prepare(root) == "NO_PENDING_CAPABILITY_ANALYSIS_BATCH"
    manifest, _ = operations.analysis_batches.load_manifest()
    assert manifest is not None
    assert manifest["next_batch_index"] == 1
    assert manifest["skipped_candidate_fingerprints"] == [fingerprints[0]]


def test_skill_contract_supports_single_and_one_batch_only() -> None:
    skill = (
        Path(__file__).resolve().parents[1]
        / ".agents"
        / "skills"
        / "capability-analysis"
        / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "one fixed batch of at most twenty" in skill
    assert "one Skill run processes one batch" in skill
    assert "must stop after this apply command" in skill
    assert "Full Catalog data is never supplied" in skill
    assert "does not persist a user decision" in skill
