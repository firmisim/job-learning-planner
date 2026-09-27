from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_application_capabilities import _role_with_signals
from scripts.apply_semantic_handoff import apply
from ui.app import create_app


def _client_with_role(
    tmp_path: Path,
    expressions: list[str],
) -> tuple[TestClient, str]:
    client = TestClient(create_app(tmp_path / "state"), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    role_id = _role_with_signals(
        client.app.state.market,
        "AI Application Development",
        expressions,
    )
    client.cookies.set("job_learning_current_role", role_id)
    return client, role_id


def test_inbox_keeps_add_merge_skip_in_one_candidate_page(tmp_path: Path) -> None:
    client, role_id = _client_with_role(tmp_path, ["LLM API使用"])
    existing = client.app.state.capabilities.storage.create_capability(
        "AI API Development"
    )
    workspace = client.app.state.capabilities.workspace(role_id)
    candidate = workspace.pending_candidates[0]

    page = client.get(f"/capabilities/inbox/{candidate.candidate_fingerprint}")
    assert page.status_code == 200
    assert "Add new Capability" in page.text
    assert "Merge into existing" in page.text
    assert "Skip for this Role" in page.text
    assert "AI API Development" not in page.text
    searched = client.get(
        f"/capabilities/inbox/{candidate.candidate_fingerprint}"
        "?merge_query=AI+API"
    )
    assert 'value="AI API Development"' in searched.text

    recommendation = {
        "candidate_fingerprint": candidate.candidate_fingerprint,
        "explanation": "A market signal about integrating language-model APIs.",
        "learning_value": "Useful for building AI applications.",
        "recommended_action": "add",
        "recommended_canonical_name": "LLM API",
        "rationale": "This can be learned as a durable capability.",
        "evidence_quotes": ["LLM API使用"],
    }
    prepared = client.post(
        f"/capabilities/inbox/{candidate.candidate_fingerprint}/recommendation",
        follow_redirects=False,
    )
    assert prepared.status_code == 303
    prepared_page = client.get(
        f"/capabilities/inbox/{candidate.candidate_fingerprint}"
    )
    assert "Capability Analysis request is prepared" in prepared_page.text
    assert "recommendation has not been generated yet" in prepared_page.text
    assert "capability-analysis" in prepared_page.text
    assert "return to this Capability Inbox candidate" in prepared_page.text
    assert "Add new Capability" in prepared_page.text
    assert "Merge into existing" in prepared_page.text
    assert "Skip for this Role" in prepared_page.text
    handoffs = client.app.state.capabilities.handoffs
    handoffs.draft_path("capability-analysis").write_text(
        json.dumps(recommendation), encoding="utf-8"
    )
    apply("capability-analysis", tmp_path / "state")
    advised = client.get(f"/capabilities/inbox/{candidate.candidate_fingerprint}")
    assert "Suggested action" in advised.text
    assert ">add<" in advised.text
    assert "Merge into existing" in advised.text
    assert "Recommendation input" not in advised.text
    assert "result JSON" not in advised.text

    merged = client.post(
        f"/capabilities/inbox/{candidate.candidate_fingerprint}/merge",
        data={
            "role_id": role_id,
            "capability_name": existing.name,
            "expected_catalog_sha256": workspace.catalog_sha256,
        },
        follow_redirects=False,
    )
    assert merged.status_code == 303
    assert merged.headers["location"].startswith("/capabilities")
    assert [
        item.name
        for item in client.app.state.capabilities.workspace(
            role_id
        ).current_capabilities
    ] == ["AI API Development"]


def test_validation_error_keeps_candidate_and_all_choices(tmp_path: Path) -> None:
    client, role_id = _client_with_role(
        tmp_path, ["Existing expression", "New expression"]
    )
    operations = client.app.state.capabilities
    operations.storage.create_capability("Existing Capability")
    workspace = operations.workspace(role_id)
    candidate = next(
        item
        for item in workspace.pending_candidates
        if item.atomic_expression == "New expression"
    )
    blocked = client.post(
        f"/capabilities/inbox/{candidate.candidate_fingerprint}/add",
        data={
            "role_id": role_id,
            "canonical_name": "Existing Capability",
            "expected_catalog_sha256": workspace.catalog_sha256,
        },
    )
    assert blocked.status_code == 422
    assert "Capability name already exists; use Merge" in blocked.text
    assert "New expression" in blocked.text
    assert "Add new Capability" in blocked.text
    assert "Merge into existing" in blocked.text
    assert "Skip for this Role" in blocked.text


def test_skip_restore_and_rename_are_available_in_ui(tmp_path: Path) -> None:
    client, role_id = _client_with_role(tmp_path, ["Observability", "Fast API"])
    operations = client.app.state.capabilities
    workspace = operations.workspace(role_id)
    skipped = next(
        item
        for item in workspace.pending_candidates
        if item.atomic_expression == "Observability"
    )
    response = client.post(
        f"/capabilities/inbox/{skipped.candidate_fingerprint}/skip",
        data={
            "role_id": role_id,
            "expected_skipped_sha256": workspace.skipped_sha256,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    capability_page = client.get("/capabilities")
    assert "Skipped Candidates" in capability_page.text
    assert "Restore" in capability_page.text

    current = operations.workspace(role_id)
    restored = client.post(
        f"/capabilities/skipped/{skipped.candidate_fingerprint}/restore",
        data={
            "role_id": role_id,
            "expected_skipped_sha256": current.skipped_sha256,
        },
        follow_redirects=False,
    )
    assert restored.status_code == 303
    assert skipped.candidate_fingerprint in restored.headers["location"]

    fast_api = next(
        item
        for item in operations.workspace(role_id).pending_candidates
        if item.atomic_expression == "Fast API"
    )
    operations.add(
        role_id,
        fast_api.candidate_fingerprint,
        "FastAPI",
        expected_catalog_sha256=operations.workspace(role_id).catalog_sha256,
    )
    capability = operations.workspace(role_id).current_capabilities[0]
    detail = client.get(f"/capabilities/{capability.capability_id}")
    assert detail.status_code == 200
    assert "Canonical name" in detail.text
    assert ">Rename<" in detail.text
    renamed = client.post(
        f"/capabilities/{capability.capability_id}/rename",
        data={
            "role_id": role_id,
            "name": "FastAPI Engineering",
            "expected_catalog_sha256": operations.workspace(role_id).catalog_sha256,
        },
        follow_redirects=False,
    )
    assert renamed.status_code == 303
    assert operations.workspace(role_id).current_capabilities[0].capability_id == (
        capability.capability_id
    )


def test_capability_default_view_switches_role_working_set(tmp_path: Path) -> None:
    client, role_a = _client_with_role(tmp_path, ["FastAPI"])
    operations = client.app.state.capabilities
    candidate_a = operations.workspace(role_a).pending_candidates[0]
    operations.add(
        role_a,
        candidate_a.candidate_fingerprint,
        "FastAPI",
        expected_catalog_sha256=operations.workspace(role_a).catalog_sha256,
    )
    role_b = _role_with_signals(
        client.app.state.market, "Java Backend", ["Spring Boot"]
    )
    candidate_b = operations.workspace(role_b).pending_candidates[0]
    operations.add(
        role_b,
        candidate_b.candidate_fingerprint,
        "Spring Boot",
        expected_catalog_sha256=operations.workspace(role_b).catalog_sha256,
    )

    client.post(
        "/roles/switch",
        data={"role_name": "AI"},
        follow_redirects=False,
    )
    page_a = client.get("/capabilities")
    current_a = page_a.text.split("All Capabilities", 1)[0]
    assert "FastAPI" in current_a
    assert "Spring Boot" not in current_a

    client.post(
        "/roles/switch",
        data={"role_name": "Java Backend"},
        follow_redirects=False,
    )
    page_b = client.get("/capabilities")
    current_b = page_b.text.split("All Capabilities", 1)[0]
    assert "Spring Boot" in current_b
    assert "FastAPI" not in current_b
