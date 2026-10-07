from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_application_learning import _mapped_roles
from tests.test_application_capabilities import _role_with_signals
from tests.test_application_knowledge import _knowledge_payload
from application.capabilities import CapabilityOperations
from application.market import MarketOperations
from src.core_storage import CoreStorage
from ui.app import create_app


def _client(tmp_path: Path) -> tuple[TestClient, str, str, dict[str, str]]:
    root = tmp_path / "state"
    role_a, role_b, ids = _mapped_roles(root)
    client = TestClient(create_app(root), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    client.cookies.set("job_learning_current_role", role_a)
    return client, role_a, role_b, ids


def test_my_learning_is_role_scoped_and_distinguishes_unset_from_zero(
    tmp_path: Path,
) -> None:
    client, role_a, role_b, ids = _client(tmp_path)
    page = client.get("/learning")
    assert page.status_code == 200
    assert "Python" in page.text and "Docker" in page.text
    assert "Java" not in page.text and "Excel" not in page.text
    assert "Level not set" in page.text

    view = client.app.state.learning.view(role_a)
    saved = client.post(
        f'/learning/capabilities/{ids["Python"]}/level',
        data={
            "role_id": role_a,
            "current_level": "0",
            "expected_sha256": view.personal_states_sha256,
        },
        follow_redirects=False,
    )
    assert saved.status_code == 303
    page = client.get("/learning")
    assert "Level 0 / 5" in page.text
    assert "Level not set" in page.text
    detail = client.get(f'/learning/capabilities/{ids["Python"]}')
    assert detail.status_code == 200
    assert "Using generic level criteria" in detail.text
    assert all(f"Level {level}" in detail.text for level in range(6))

    client.post(
        "/roles/switch",
        data={"role_name": "Role B"},
        follow_redirects=False,
    )
    switched = client.get("/learning")
    assert "Java" in switched.text and "Docker" in switched.text
    assert "Python" not in switched.text


def test_practice_add_edit_empty_remove_is_available_and_shared(tmp_path: Path) -> None:
    client, role_a, role_b, ids = _client(tmp_path)
    before = client.app.state.learning.view(role_a)
    added = client.post(
        f'/learning/capabilities/{ids["Docker"]}/practices',
        data={
            "role_id": role_a,
            "description": "完成 Docker Compose 多服务项目",
            "expected_sha256": before.practices_sha256,
        },
        follow_redirects=False,
    )
    assert added.status_code == 303
    page = client.get(f'/learning/capabilities/{ids["Docker"]}')
    assert "Save Practice" in page.text
    assert "Edit Practice" in page.text
    assert "Saving an empty description removes this Practice" in page.text
    assert "Delete Practice" not in page.text
    assert page.text.count("完成 Docker Compose 多服务项目") == 2
    practice = client.app.state.learning.storage.load_practices().practices[0]

    client.post(
        "/roles/switch",
        data={"role_name": "Role B"},
        follow_redirects=False,
    )
    assert "完成 Docker Compose 多服务项目" in client.get(
        f'/learning/capabilities/{ids["Docker"]}'
    ).text
    current = client.app.state.learning.view(role_b)
    edited = client.post(
        f'/learning/capabilities/{ids["Docker"]}/practices/{practice.practice_id}/edit',
        data={
            "role_id": role_b,
            "description": "完成 Docker Compose 多服务与健康检查项目",
            "expected_sha256": current.practices_sha256,
        },
        follow_redirects=False,
    )
    assert edited.status_code == 303
    current = client.app.state.learning.view(role_b)
    deleted = client.post(
        f'/learning/capabilities/{ids["Docker"]}/practices/{practice.practice_id}/edit',
        data={
            "role_id": role_b,
            "description": "",
            "expected_sha256": current.practices_sha256,
        },
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    assert client.app.state.learning.storage.load_practices().practices == []


def test_ui_rejects_out_of_scope_mutation_and_hides_internal_roadmap_input(
    tmp_path: Path,
) -> None:
    client, role_a, _, ids = _client(tmp_path)
    blocked = client.post(
        f'/learning/capabilities/{ids["Java"]}/level',
        data={
            "role_id": role_a,
            "current_level": "3",
            "expected_sha256": client.app.state.learning.view(
                role_a
            ).personal_states_sha256,
        },
    )
    assert blocked.status_code == 422
    assert "not in the current Role" in blocked.text
    payload = client.get("/learning/stage-f-input")
    assert payload.status_code == 404


def test_ui_rejects_form_for_a_role_other_than_current_cookie(tmp_path: Path) -> None:
    client, role_a, role_b, ids = _client(tmp_path)
    blocked = client.post(
        f'/learning/capabilities/{ids["Java"]}/level',
        data={
            "role_id": role_b,
            "current_level": "4",
            "expected_sha256": client.app.state.learning.view(
                role_a
            ).personal_states_sha256,
        },
    )
    assert blocked.status_code == 422
    assert "does not match the current Role" in blocked.text
    assert client.app.state.learning.storage.load_personal_states().states == []


def test_learning_summary_search_and_pagination_remain_role_scoped(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    market = MarketOperations(root)
    names = [f"Capability {index:02d}" for index in range(12)]
    role_id = _role_with_signals(market, "Large Role", names)
    store = CoreStorage(root)
    for name in names:
        capability = store.create_capability(name)
        store.add_source_mapping(name, capability.capability_id)
    unrelated = store.create_capability("Unrelated Global Capability")
    assert unrelated.name == "Unrelated Global Capability"

    client = TestClient(create_app(root), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    client.cookies.set("job_learning_current_role", role_id)
    first = client.get("/learning")
    assert first.status_code == 200
    assert "Page 1 of 2" in first.text
    assert "Capability 00" in first.text
    assert "Capability 11" not in first.text
    second = client.get("/learning?page=2")
    assert "Capability 11" in second.text
    searched = client.get("/learning?query=Capability+11")
    assert "Capability 11" in searched.text
    assert "Capability 00" not in searched.text
    assert "Unrelated Global Capability" not in searched.text
    cleared = client.get("/learning")
    assert "Capability 00" in cleared.text


def test_learning_detail_prefers_specific_criteria_and_keeps_practice_crud(
    tmp_path: Path,
) -> None:
    client, role_a, _, ids = _client(tmp_path)
    capabilities = CapabilityOperations(client.app.state.learning.storage.root)
    research_input = capabilities.knowledge_research_input(role_a, ids["Docker"])
    capabilities.save_knowledge_result(
        role_a,
        ids["Docker"],
        _knowledge_payload(research_input, level_prefix="Docker"),
        expected_knowledge_sha256=None,
    )

    detail = client.get(f'/learning/capabilities/{ids["Docker"]}')
    assert detail.status_code == 200
    assert "Using Capability-specific criteria" in detail.text
    assert "Docker Level 3: observable task 3" in detail.text
    assert "Add Practice" in detail.text
    assert "Level not set" not in detail.text
    assert ">Not set<" in detail.text


def test_roadmap_scope_detail_edit_list_status_and_role_specific_display(
    tmp_path: Path,
) -> None:
    client, role_a, role_b, ids = _client(tmp_path)
    storage = client.app.state.learning.storage
    before_catalog = storage.load_catalog()
    before_states = storage.load_personal_states()
    before_practices = storage.load_practices()
    before_jobs = storage.load_jds(
        client.app.state.learning._uuid(role_a, "role_id")
    )

    listing = client.get("/learning")
    assert "In Roadmap" in listing.text
    detail = client.get(f'/learning/capabilities/{ids["Docker"]}')
    assert detail.status_code == 200
    assert 'role="switch"' in detail.text
    assert 'aria-checked="true"' in detail.text
    assert 'aria-describedby="roadmap-scope-help"' in detail.text
    assert 'name="included" value="false"' in detail.text
    assert 'class="badge badge-ready"' in detail.text
    assert 'role="tooltip"' in detail.text
    assert "roadmap-scope-track" not in detail.text
    assert "In Roadmap" in detail.text
    assert "Applies to this Role only." in detail.text
    assert "does not remove its Mapping, Knowledge, level, Practices, or market data" in detail.text

    view = client.app.state.learning.view(role_a)
    excluded = client.post(
        f'/learning/capabilities/{ids["Docker"]}/roadmap-scope',
        data={
            "role_id": role_a,
            "included": "false",
            "expected_sha256": view.roadmap_scope_sha256 or "",
        },
    )
    assert excluded.status_code == 200
    assert "Excluded from future Roadmaps for the current Role" in excluded.text
    assert 'aria-checked="false"' in excluded.text
    assert 'name="included" value="true"' in excluded.text
    assert 'class="badge badge-neutral"' in excluded.text
    listing = client.get("/learning")
    assert "Docker" in listing.text
    assert "Excluded from Roadmap" in listing.text

    client.post(
        "/roles/switch", data={"role_name": "Role B"}, follow_redirects=False
    )
    role_b_detail = client.get(f'/learning/capabilities/{ids["Docker"]}')
    assert "In Roadmap" in role_b_detail.text
    assert client.app.state.learning.view(role_b).roadmap_scope_sha256 is None

    client.post(
        "/roles/switch", data={"role_name": "Role A"}, follow_redirects=False
    )
    view = client.app.state.learning.view(role_a)
    included = client.post(
        f'/learning/capabilities/{ids["Docker"]}/roadmap-scope',
        data={
            "role_id": role_a,
            "included": "true",
            "expected_sha256": view.roadmap_scope_sha256 or "",
        },
    )
    assert included.status_code == 200
    assert "Included in future Roadmaps for the current Role" in included.text
    assert storage.load_catalog() == before_catalog
    assert storage.load_personal_states() == before_states
    assert storage.load_practices() == before_practices
    assert storage.load_jds(before_jobs.role_id) == before_jobs


def test_roadmap_scope_ui_is_localized_in_zh_cn(tmp_path: Path) -> None:
    root = tmp_path / "state"
    role_a, _, ids = _mapped_roles(root)
    client = TestClient(
        create_app(root),
        raise_server_exceptions=False,
        headers={"Accept-Language": "zh-CN"},
    )
    client.cookies.set("job_learning_current_role", role_a)
    detail = client.get(f'/learning/capabilities/{ids["Python"]}')
    assert detail.status_code == 200
    assert "已纳入学习路线" in detail.text
    assert "点击切换为未纳入学习路线" in detail.text
    assert "仅适用于当前岗位方向。" in detail.text
    assert "不会移除其映射、知识、等级、实践或市场数据" in detail.text

    view = client.app.state.learning.view(role_a)
    excluded = client.post(
        f'/learning/capabilities/{ids["Python"]}/roadmap-scope',
        data={
            "role_id": role_a,
            "included": "false",
            "expected_sha256": view.roadmap_scope_sha256 or "",
        },
    )
    assert excluded.status_code == 200
    assert "已从当前 Role 的后续学习路线中排除" in excluded.text
    assert "未纳入学习路线" in client.get("/learning").text
