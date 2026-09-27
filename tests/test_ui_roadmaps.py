from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from application.learning import LearningOperations
from application.roadmaps import RoadmapOperations
from scripts.apply_semantic_handoff import apply
from tests.test_application_roadmaps import (
    _mapped_role_without_knowledge,
    _ready_role,
    _result,
)
from tests.test_application_knowledge import _knowledge_payload
from ui.app import create_app


def test_navigation_and_generate_regenerate_history_flow(tmp_path: Path) -> None:
    root = tmp_path / "state"
    operations, learning, role_id, capability_id = _ready_role(root)
    client = TestClient(create_app(root), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    client.cookies.set("job_learning_current_role", role_id)
    client.cookies.set("job_learning_ui_locale", "en")
    page = client.get("/roadmaps")
    assert page.status_code == 200
    for label in ("Market", "Capabilities", "My Learning", "Roadmap", "Settings"):
        assert label in page.text
    assert "Generate Roadmap" in page.text
    assert "Export current input" not in page.text
    assert "result JSON" not in page.text
    prepared = client.post(
        "/roadmaps",
        data={"role_id": role_id},
        follow_redirects=False,
    )
    assert prepared.status_code == 303
    prepared_page = client.get("/roadmaps")
    assert "Roadmap Generation request is prepared" in prepared_page.text
    assert "Roadmap has not been generated yet" in prepared_page.text
    assert "job-learning-roadmap" in prepared_page.text
    assert "return to Roadmap" in prepared_page.text
    handoffs = client.app.state.roadmaps.handoffs
    request = handoffs.load_request("job-learning-roadmap")
    roadmap_input = request["input"]
    assert isinstance(roadmap_input, dict)
    handoffs.draft_path("job-learning-roadmap").write_text(
        _result(str(roadmap_input["input_fingerprint"]), "# First"),
        encoding="utf-8",
    )
    apply("job-learning-roadmap", root)
    first_list = client.get("/roadmaps")
    assert "First" not in first_list.text
    first_id = operations.view(role_id).history[0].roadmap_id
    assert "First" in client.get(f"/roadmaps/{first_id}").text

    learning.set_level(
        role_id,
        capability_id,
        4,
        expected_sha256=learning.view(role_id).personal_states_sha256,
    )
    changed = client.get("/roadmaps")
    assert "Inputs changed" in changed.text
    assert "Regenerate Roadmap" in changed.text
    client.post(
        "/roadmaps",
        data={"role_id": role_id},
        follow_redirects=False,
    )
    request = handoffs.load_request("job-learning-roadmap")
    roadmap_input = request["input"]
    assert isinstance(roadmap_input, dict)
    handoffs.draft_path("job-learning-roadmap").write_text(
        _result(str(roadmap_input["input_fingerprint"]), "# Second"),
        encoding="utf-8",
    )
    apply("job-learning-roadmap", root)
    history = client.get("/roadmaps")
    assert "Second" not in history.text
    latest_id = operations.view(role_id).history[0].roadmap_id
    assert "Second" in client.get(f"/roadmaps/{latest_id}").text
    assert history.text.count("Historical") >= 1


def test_blockers_link_to_real_pages_and_invalid_result_preserves_current(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    client = TestClient(create_app(root), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    market = client.app.state.market
    role_id, _ = market.create_role("Empty", market.view().roles_sha256)
    client.cookies.set("job_learning_current_role", role_id)
    page = client.get("/roadmaps")
    assert "Add at least one JD" in page.text
    assert 'href="/market"' in page.text
    blocked = client.post("/roadmaps", data={"role_id": role_id})
    assert blocked.status_code == 422


def test_partial_knowledge_counts_and_generate_remains_available(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    capabilities, role_id, ids = _mapped_role_without_knowledge(
        root, ["FastAPI", "Docker"]
    )
    capabilities.save_knowledge_result(
        role_id,
        ids["FastAPI"],
        _knowledge_payload(
            capabilities.knowledge_research_input(role_id, ids["FastAPI"])
        ),
        expected_knowledge_sha256=None,
    )
    client = TestClient(create_app(root), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    client.cookies.set("job_learning_current_role", role_id)

    page = client.get("/roadmaps")
    assert page.status_code == 200
    assert "Roadmap Scope" in page.text
    assert "2 / 2 capabilities included" in page.text
    assert "Manage in My Learning" in page.text
    assert "Knowledge ready" in page.text
    assert "Need research" in page.text
    assert "1 Capability" in page.text
    assert "Generate Roadmap" in page.text
    assert "result will be limited" not in page.text
    assert "will contain only Market relevance and research guidance" in page.text
    assert 'href="/capabilities#current-capabilities"' in page.text

    prepared = client.post(
        "/roadmaps", data={"role_id": role_id}, follow_redirects=False
    )
    assert prepared.status_code == 303
    request = client.app.state.roadmaps.handoffs.load_request(
        "job-learning-roadmap"
    )
    assert {
        item["guidance_mode"] for item in request["input"]["capabilities"]
    } == {"knowledge-ready", "research-needed"}


def test_zero_knowledge_ui_allows_limited_generation(tmp_path: Path) -> None:
    root = tmp_path / "state"
    _, role_id, _ = _mapped_role_without_knowledge(root, ["FastAPI"])
    client = TestClient(create_app(root), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    client.cookies.set("job_learning_current_role", role_id)

    page = client.get("/roadmaps")
    assert page.status_code == 200
    assert "Knowledge ready" in page.text
    assert "Need research" in page.text
    assert "Generate Roadmap" in page.text
    assert "Token" not in page.text
    assert client.post(
        "/roadmaps", data={"role_id": role_id}, follow_redirects=False
    ).status_code == 303


def test_zero_selected_guidance_is_distinct_and_history_stays_visible(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    _, role_id, ids = _mapped_role_without_knowledge(root, ["FastAPI"])
    roadmaps = RoadmapOperations(root)
    fingerprint = str(roadmaps.generation_input(role_id)["input_fingerprint"])
    roadmaps.save_result(role_id, _result(fingerprint, "# Existing Roadmap"))
    learning = LearningOperations(root)
    learning.set_roadmap_inclusion(
        role_id,
        ids["FastAPI"],
        False,
        expected_sha256=learning.view(role_id).roadmap_scope_sha256,
    )
    client = TestClient(create_app(root), raise_server_exceptions=False)
    client.cookies.set("job_learning_current_role", role_id)
    client.cookies.set("job_learning_ui_locale", "en")

    page = client.get("/roadmaps")
    assert "0 / 1 capabilities included" in page.text
    assert "Include at least one Capability in Roadmap" in page.text
    assert 'href="/learning"' in page.text
    assert "Roadmap history: 1 / 30" in page.text
    assert client.post(
        "/roadmaps", data={"role_id": role_id}, follow_redirects=False
    ).status_code == 422
