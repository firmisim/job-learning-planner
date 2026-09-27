from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scripts.apply_semantic_handoff import apply
from tests.test_application_capability_analysis_batch import (
    _batch_results,
    _pending,
)
from ui.app import create_app
from ui.i18n import LOCALE_COOKIE


def test_batch_selection_progress_guidance_and_retry_ui(tmp_path: Path) -> None:
    root = tmp_path / "state"
    operations, role_id, fingerprints = _pending(root, "UI Batch", 3)
    client = TestClient(create_app(root), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    client.cookies.set("job_learning_current_role", role_id)

    initial = client.get("/capabilities")
    assert initial.status_code == 200
    assert "Prepare Selected" in initial.text
    assert "Prepare All Unanalyzed" in initial.text
    assert "Recommendation not generated" in initial.text

    response = client.post(
        "/capabilities/analysis/batch/selected",
        data={"role_id": role_id, "candidate_fingerprint": fingerprints[:2]},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "selection_cleared=analysis" in response.headers["location"]
    notice_page = client.get(response.headers["location"])
    assert "Prepared candidates: 2; batches: 1" in notice_page.text
    progress = client.get("/capabilities")
    assert "0 / 2" in progress.text
    assert "capability-analysis" in progress.text
    assert "Recommendations have not been generated" in progress.text
    assert "One Skill run processes one batch" in progress.text
    assert "return to Capability Inbox" in progress.text
    assert "batch_manifest.json" not in progress.text

    request = operations.handoffs.load_request("capability-analysis")
    results = _batch_results(request)
    results[1]["evidence_quotes"] = ["invalid evidence"]
    operations.handoffs.draft_path("capability-analysis").write_text(
        json.dumps({"results": results}), encoding="utf-8"
    )
    apply("capability-analysis", root)
    attention = client.get("/capabilities")
    assert "1 / 2" in attention.text
    assert "Retry Failed" in attention.text
    assert "Recommendation ready" in attention.text
    assert "One Skill run processes one batch" not in attention.text

    retried = client.post(
        "/capabilities/analysis/batch/retry",
        data={"role_id": role_id},
        follow_redirects=False,
    )
    assert retried.status_code == 303
    retried_page = client.get(retried.headers["location"])
    assert "Prepared candidates: 1; batches: 1" in retried_page.text
    assert "capability-analysis" in retried_page.text
    assert "technical detail that is not shown here" not in retried_page.text
    retry_manifest, _ = operations.analysis_batches.load_manifest()
    assert retry_manifest is not None
    assert [
        item["candidate_fingerprint"] for item in retry_manifest["selected"]
    ] == [fingerprints[1]]


def test_analysis_batch_is_hidden_and_retry_rejected_for_other_role(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    operations, role_a, _ = _pending(root, "Prepared Analysis", 1)
    _, role_b, _ = _pending(root, "Current Analysis", 1)
    operations.prepare_capability_analysis_batch(role_a)
    manifest, manifest_sha256 = operations.analysis_batches.load_manifest()

    client = TestClient(create_app(root), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    client.post(
        "/roles/switch",
        data={"role_name": "Current Analysis", "return_to": "/capabilities"},
        follow_redirects=False,
    )
    page = client.get("/capabilities")
    assert page.status_code == 200
    assert "<span>Prepared Role</span>" not in page.text
    assert "The current Capability Analysis batch is prepared" not in page.text

    rejected = client.post(
        "/capabilities/analysis/batch/retry",
        data={"role_id": role_b},
        follow_redirects=False,
    )
    assert rejected.status_code == 422
    assert "does not match the prepared batch Role" in rejected.text
    after, after_sha256 = operations.analysis_batches.load_manifest()
    assert (after, after_sha256) == (manifest, manifest_sha256)


def test_completed_batch_stops_guidance_and_inbox_shows_advice(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    operations, role_id, fingerprints = _pending(root, "Complete UI", 1)
    client = TestClient(create_app(root), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    client.cookies.set("job_learning_current_role", role_id)
    prepared = client.post(
        "/capabilities/analysis/batch/all",
        data={"role_id": role_id},
        follow_redirects=False,
    )
    prepared_page = client.get(prepared.headers["location"])
    assert "Prepared candidates: 1; batches: 1" in prepared_page.text
    assert "capability-analysis" in prepared_page.text
    assert "technical detail that is not shown here" not in prepared_page.text
    request = operations.handoffs.load_request("capability-analysis")
    operations.handoffs.draft_path("capability-analysis").write_text(
        json.dumps({"results": _batch_results(request)}), encoding="utf-8"
    )
    apply("capability-analysis", root)

    completed = client.get("/capabilities")
    assert "Capability Analysis is complete" in completed.text
    assert "No further Skill run is needed" in completed.text
    assert "One Skill run processes one batch" not in completed.text
    inbox = client.get(f"/capabilities/inbox/{fingerprints[0]}")
    assert "The supplied evidence is too narrow" in inbox.text
    assert "Add new Capability" in inbox.text
    assert "Merge into existing" in inbox.text
    assert "Skip for this Role" in inbox.text


def test_selected_candidate_is_revalidated_after_it_is_resolved(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    operations, role_id, fingerprints = _pending(root, "Eligibility Drift", 2)
    operations.add(
        role_id,
        fingerprints[0],
        "Resolved Candidate",
        expected_catalog_sha256=operations.workspace(role_id).catalog_sha256,
    )
    client = TestClient(create_app(root), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    client.cookies.set("job_learning_current_role", role_id)

    rejected = client.post(
        "/capabilities/analysis/batch/selected",
        data={"role_id": role_id, "candidate_fingerprint": fingerprints},
        follow_redirects=False,
    )

    assert rejected.status_code == 422
    assert "pending candidates without recommendations" in rejected.text
    assert operations.analysis_batches.load_manifest() == (None, None)


@pytest.mark.parametrize(
    ("locale", "expected"),
    [
        ("zh-CN", "已准备 2 个候选项，共 1 批"),
        ("en", "Prepared candidates: 2; batches: 1"),
    ],
)
def test_analysis_batch_post_redirect_renders_localized_complete_notice(
    tmp_path: Path, locale: str, expected: str
) -> None:
    root = tmp_path / locale / "state"
    operations, role_id, fingerprints = _pending(root, "Localized Analysis", 2)
    client = TestClient(create_app(root), raise_server_exceptions=False)
    client.cookies.set(LOCALE_COOKIE, locale)
    client.cookies.set("job_learning_current_role", role_id)

    response = client.post(
        "/capabilities/analysis/batch/selected",
        data={"role_id": role_id, "candidate_fingerprint": fingerprints},
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = client.get(response.headers["location"])
    assert page.status_code == 200
    assert expected in page.text
    assert "capability-analysis" in page.text
    assert "detail_unavailable" not in page.text
    assert "technical detail that is not shown here" not in page.text
    assert "此处不展示的技术详情" not in page.text

    manifest, _ = operations.analysis_batches.load_manifest()
    assert manifest is not None
    assert manifest["role"]["role_id"] == role_id
    assert [
        item["candidate_fingerprint"] for item in manifest["selected"]
    ] == fingerprints
    request = operations.handoffs.load_request("capability-analysis")
    assert request["context"]["role_id"] == role_id
