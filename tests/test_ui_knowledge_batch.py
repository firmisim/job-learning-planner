from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scripts.apply_semantic_handoff import apply
from tests.test_application_knowledge import _knowledge_payload
from tests.test_application_knowledge_batch import _batch_results, _mapped_missing
from ui.app import create_app
from ui.i18n import LOCALE_COOKIE


def test_batch_selection_progress_role_scope_and_retry_ui(tmp_path: Path) -> None:
    root = tmp_path / "state"
    operations, role_a, ids_a = _mapped_missing(root, "Batch Role", 6)
    _, role_b, _ = _mapped_missing(root, "Other Role", 1)
    client = TestClient(create_app(root), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    client.cookies.set("job_learning_current_role", role_a)

    initial = client.get("/capabilities")
    assert initial.status_code == 200
    assert "Prepare Selected" in initial.text
    assert "Prepare All Unresearched" in initial.text
    assert "data-selected-count>0</span>" in initial.text
    assert "up to four" in initial.text
    assert "Refresh all" not in initial.text

    prepared = client.post(
        "/capabilities/knowledge/batch/selected",
        data={"role_id": role_a, "capability_id": ids_a[:5]},
        follow_redirects=False,
    )
    assert prepared.status_code == 303
    assert "selection_cleared=knowledge" in prepared.headers["location"]
    notice_page = client.get(prepared.headers["location"])
    assert "Prepared Capabilities: 5; batches: 2" in notice_page.text
    progress = client.get("/capabilities")
    assert "Batch Role" in progress.text
    assert "0 / 5 succeeded" in progress.text
    assert "0 / 2 batches completed" in progress.text
    assert "capability-knowledge-research" in progress.text
    assert "research has not run for this batch yet" in progress.text
    assert "One Skill run processes one batch" in progress.text
    assert "return to Capabilities" in progress.text

    request = operations.handoffs.load_request("capability-knowledge-research")
    results = _batch_results(request)
    results[1]["level_criteria"] = results[1]["level_criteria"][:2]
    operations.handoffs.draft_path("capability-knowledge-research").write_text(
        json.dumps({"results": results}), encoding="utf-8"
    )
    apply("capability-knowledge-research", root)
    partial = client.get("/capabilities")
    assert "3 / 5 succeeded" in partial.text
    assert "1 / 2 batches completed" in partial.text
    assert "Retry Failed" in partial.text
    assert "Research result did not pass existing Knowledge validation" in partial.text

    switched = client.post(
        "/roles/switch",
        data={"role_name": "Other Role", "return_to": "/capabilities"},
        follow_redirects=False,
    )
    assert switched.status_code == 303
    other_role = client.get("/capabilities")
    assert other_role.status_code == 200
    assert "<span>Prepared Role</span>" not in other_role.text
    assert "0 / 5 succeeded" not in other_role.text
    assert "Retry Failed" not in other_role.text
    manifest, _ = operations.knowledge_batches.load_snapshot()
    assert manifest is not None
    assert manifest["role"]["role_id"] == role_a
    assert [item["capability_id"] for item in manifest["selected"]] == ids_a[:5]


def test_prepare_all_excludes_researched_and_retry_route_uses_failed_only(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    operations, role_id, ids = _mapped_missing(root, "All Role", 3)
    input_payload = operations.knowledge_research_input(role_id, ids[0])
    operations.save_knowledge_result(
        role_id,
        ids[0],
        _knowledge_payload(input_payload),
        expected_knowledge_sha256=None,
    )
    client = TestClient(create_app(root), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    client.cookies.set("job_learning_current_role", role_id)

    prepared = client.post(
        "/capabilities/knowledge/batch/all",
        data={"role_id": role_id},
        follow_redirects=False,
    )
    assert prepared.status_code == 303
    prepared_page = client.get(prepared.headers["location"])
    assert "Prepared Capabilities: 2; batches: 1" in prepared_page.text
    assert "capability-knowledge-research" in prepared_page.text
    assert "technical detail that is not shown here" not in prepared_page.text
    manifest, _ = operations.knowledge_batches.load_snapshot()
    assert manifest is not None
    assert [item["capability_id"] for item in manifest["selected"]] == ids[1:]

    request = operations.handoffs.load_request("capability-knowledge-research")
    result = _batch_results(request)
    result[0].pop("core_topics")
    operations.handoffs.draft_path("capability-knowledge-research").write_text(
        json.dumps({"results": result}), encoding="utf-8"
    )
    apply("capability-knowledge-research", root)
    attention = client.get("/capabilities")
    assert "Knowledge Research finished with 1 failed item" in attention.text
    assert "Retry Failed" in attention.text
    assert "One Skill run processes one batch" not in attention.text
    retried = client.post(
        "/capabilities/knowledge/batch/retry",
        data={"role_id": role_id},
        follow_redirects=False,
    )
    assert retried.status_code == 303
    retried_page = client.get(retried.headers["location"])
    assert "Prepared Capabilities: 1; batches: 1" in retried_page.text
    assert "capability-knowledge-research" in retried_page.text
    assert "technical detail that is not shown here" not in retried_page.text
    retry_manifest, _ = operations.knowledge_batches.load_snapshot()
    assert retry_manifest is not None
    assert [item["capability_id"] for item in retry_manifest["selected"]] == [ids[1]]


def test_knowledge_retry_rejects_non_matching_current_role_without_mutation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    operations, role_a, ids_a = _mapped_missing(root, "Prepared Role", 1)
    _, role_b, _ = _mapped_missing(root, "Current Role", 1)
    operations.prepare_knowledge_batch(role_a)
    request = operations.handoffs.load_request("capability-knowledge-research")
    result = _batch_results(request)
    result[0].pop("core_topics")
    operations.handoffs.draft_path("capability-knowledge-research").write_text(
        json.dumps({"results": result}), encoding="utf-8"
    )
    apply("capability-knowledge-research", root)
    before, before_sha256 = operations.knowledge_batches.load_snapshot()

    client = TestClient(create_app(root), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    client.post(
        "/roles/switch",
        data={"role_name": "Current Role", "return_to": "/capabilities"},
        follow_redirects=False,
    )
    rejected = client.post(
        "/capabilities/knowledge/batch/retry",
        data={"role_id": role_b},
        follow_redirects=False,
    )

    assert rejected.status_code == 422
    assert "does not match the prepared batch Role" in rejected.text
    after, after_sha256 = operations.knowledge_batches.load_snapshot()
    assert (after, after_sha256) == (before, before_sha256)
    assert after is not None
    assert [item["capability_id"] for item in after["selected"]] == ids_a


def test_completed_batch_stops_skill_guidance(tmp_path: Path) -> None:
    root = tmp_path / "state"
    operations, role_id, _ = _mapped_missing(root, "Complete Role", 1)
    client = TestClient(create_app(root), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    client.cookies.set("job_learning_current_role", role_id)

    client.post(
        "/capabilities/knowledge/batch/all",
        data={"role_id": role_id},
        follow_redirects=False,
    )
    request = operations.handoffs.load_request("capability-knowledge-research")
    operations.handoffs.draft_path("capability-knowledge-research").write_text(
        json.dumps({"results": _batch_results(request)}), encoding="utf-8"
    )
    apply("capability-knowledge-research", root)

    completed = client.get("/capabilities")
    assert "Knowledge Research is complete" in completed.text
    assert "No further Skill run is needed" in completed.text
    assert "One Skill run processes one batch" not in completed.text
    assert "Retry Failed" not in completed.text


def test_selected_knowledge_is_revalidated_before_manifest_creation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    operations, role_id, ids = _mapped_missing(root, "Eligibility Drift", 2)
    input_payload = operations.knowledge_research_input(role_id, ids[0])
    operations.save_knowledge_result(
        role_id,
        ids[0],
        _knowledge_payload(input_payload),
        expected_knowledge_sha256=None,
    )
    client = TestClient(create_app(root), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    client.cookies.set("job_learning_current_role", role_id)

    rejected = client.post(
        "/capabilities/knowledge/batch/selected",
        data={"role_id": role_id, "capability_id": ids},
        follow_redirects=False,
    )

    assert rejected.status_code == 422
    assert "do not have Knowledge" in rejected.text
    assert operations.knowledge_batches.load_snapshot() == (None, None)


@pytest.mark.parametrize(
    ("locale", "expected"),
    [
        ("zh-CN", "已准备 5 个能力，共 2 批"),
        ("en", "Prepared Capabilities: 5; batches: 2"),
    ],
)
def test_knowledge_batch_post_redirect_renders_localized_complete_notice(
    tmp_path: Path, locale: str, expected: str
) -> None:
    root = tmp_path / locale / "state"
    operations, role_id, ids = _mapped_missing(root, "Localized Knowledge", 5)
    client = TestClient(create_app(root), raise_server_exceptions=False)
    client.cookies.set(LOCALE_COOKIE, locale)
    client.cookies.set("job_learning_current_role", role_id)

    response = client.post(
        "/capabilities/knowledge/batch/selected",
        data={"role_id": role_id, "capability_id": ids},
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = client.get(response.headers["location"])
    assert page.status_code == 200
    assert expected in page.text
    assert "capability-knowledge-research" in page.text
    assert "detail_unavailable" not in page.text
    assert "technical detail that is not shown here" not in page.text
    assert "此处不展示的技术详情" not in page.text

    manifest, _ = operations.knowledge_batches.load_snapshot()
    assert manifest is not None
    assert manifest["role"]["role_id"] == role_id
    assert [item["capability_id"] for item in manifest["selected"]] == ids
    request = operations.handoffs.load_request("capability-knowledge-research")
    assert request["context"]["role_id"] == role_id
