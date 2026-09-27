from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from application.errors import ApplicationError
from scripts.apply_semantic_handoff import apply, apply_with_status
from tests.test_application_capabilities import _role_with_signals
from tests.test_application_knowledge import _knowledge_payload
from ui.app import create_app


def _knowledge_client(tmp_path: Path) -> tuple[TestClient, str, str]:
    client = TestClient(create_app(tmp_path / "state"), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    role_id = _role_with_signals(client.app.state.market, "API", ["FastAPI"])
    client.cookies.set("job_learning_current_role", role_id)
    operations = client.app.state.capabilities
    candidate = operations.workspace(role_id).pending_candidates[0]
    operations.add(
        role_id,
        candidate.candidate_fingerprint,
        "FastAPI",
        expected_catalog_sha256=operations.workspace(role_id).catalog_sha256,
    )
    capability_id = operations.workspace(role_id).current_capabilities[0].capability_id
    return client, role_id, capability_id


def test_first_research_and_failed_refresh_are_safe_in_capability_ui(
    tmp_path: Path,
) -> None:
    client, role_id, capability_id = _knowledge_client(tmp_path)
    page = client.get(f"/capabilities/{capability_id}")
    assert page.status_code == 200
    assert "Not researched" in page.text
    assert "Research Knowledge" in page.text
    assert "Research Plan" not in page.text
    assert "Finalize" not in page.text
    assert "research input" not in page.text.casefold()
    assert "result JSON" not in page.text

    prepared = client.post(
        f"/capabilities/{capability_id}/knowledge",
        follow_redirects=False,
    )
    assert prepared.status_code == 303
    prepared_page = client.get(f"/capabilities/{capability_id}")
    assert "Knowledge Research request is prepared" in prepared_page.text
    assert "Research has not run yet" in prepared_page.text
    assert "capability-knowledge-research" in prepared_page.text
    assert "return to Capability Detail" in prepared_page.text
    handoffs = client.app.state.capabilities.handoffs
    request = handoffs.load_request("capability-knowledge-research")
    research_input = request["input"]
    assert isinstance(research_input, dict)
    assert research_input["mode"] == "research"
    payload = _knowledge_payload(research_input)
    handoffs.draft_path("capability-knowledge-research").write_text(
        payload, encoding="utf-8"
    )
    apply("capability-knowledge-research", tmp_path / "state")
    available = client.get(f"/capabilities/{capability_id}")
    assert "Routing and dependency injection" in available.text
    assert "Build and test a small API" in available.text
    assert "FastAPI documentation" in available.text
    assert "Refresh Knowledge" in available.text

    before = client.app.state.capabilities.detail(
        role_id, capability_id
    ).knowledge.value
    prepared_refresh = client.post(
        f"/capabilities/{capability_id}/knowledge",
        follow_redirects=False,
    )
    assert prepared_refresh.status_code == 303
    handoffs.draft_path("capability-knowledge-research").write_text(
        "{}", encoding="utf-8"
    )
    with pytest.raises(ApplicationError):
        apply_with_status("capability-knowledge-research", tmp_path / "state")
    failed_page = client.get(f"/capabilities/{capability_id}")
    assert "Knowledge research result did not pass validation" in failed_page.text
    assert (
        client.app.state.capabilities.detail(role_id, capability_id).knowledge.value
        == before
    )

    refresh_request = handoffs.load_request("capability-knowledge-research")
    refresh_input = refresh_request["input"]
    assert isinstance(refresh_input, dict)
    refreshed_payload = _knowledge_payload(
        refresh_input,
        generated_at="2026-09-10T13:00:00+08:00",
        topic="Async endpoints and dependency injection",
    )
    handoffs.draft_path("capability-knowledge-research").write_text(
        refreshed_payload, encoding="utf-8"
    )
    apply("capability-knowledge-research", tmp_path / "state")
    assert (
        "Async endpoints and dependency injection"
        in client.get(f"/capabilities/{capability_id}").text
    )


def test_ui_reuses_global_knowledge_but_keeps_default_role_scope(
    tmp_path: Path,
) -> None:
    client, role_a, capability_id = _knowledge_client(tmp_path)
    operations = client.app.state.capabilities
    payload = _knowledge_payload(
        operations.knowledge_research_input(role_a, capability_id)
    )
    operations.save_knowledge_result(
        role_a,
        capability_id,
        payload,
        expected_knowledge_sha256=None,
    )
    role_b = _role_with_signals(client.app.state.market, "Shared API", ["FastAPI"])
    client.post(
        "/roles/switch",
        data={"role_name": "Shared API"},
        follow_redirects=False,
    )
    page_b = client.get("/capabilities")
    current_section = page_b.text.split("All Capabilities", 1)[0]
    assert "FastAPI" in current_section
    assert "available" in current_section
    detail_b = client.get(f"/capabilities/{capability_id}")
    assert "Routing and dependency injection" in detail_b.text

    role_c = _role_with_signals(client.app.state.market, "Java", ["Spring Boot"])
    spring = operations.workspace(role_c).pending_candidates[0]
    operations.add(
        role_c,
        spring.candidate_fingerprint,
        "Spring Boot",
        expected_catalog_sha256=operations.workspace(role_c).catalog_sha256,
    )
    client.post(
        "/roles/switch",
        data={"role_name": "Java"},
        follow_redirects=False,
    )
    page_c = client.get("/capabilities")
    current_c = page_c.text.split("All Capabilities", 1)[0]
    assert "Spring Boot" in current_c
    assert "FastAPI" not in current_c
