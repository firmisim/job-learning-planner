from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from application.errors import ApplicationError
from schemas.core import RoadmapVersion
from src.core_storage import MAX_ROADMAP_VERSIONS_PER_ROLE
from tests.test_application_roadmaps import _ready_role, _result
from ui.app import create_app


def _append_versions(
    operations, role_id: str, fingerprint: str, count: int
) -> list[RoadmapVersion]:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    versions = [
        RoadmapVersion(
            role_id=operations._uuid(role_id, "role_id"),
            generated_at=start + timedelta(minutes=index),
            input_fingerprint=fingerprint,
            content=f"# Stored version {index}\n\n内容 {index}",
        )
        for index in range(count)
    ]
    for version in versions:
        operations.storage.append_roadmap(version)
    return versions


def test_list_is_latest_first_fixed_ten_per_page_and_does_not_render_content(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    operations, _, role_id, _ = _ready_role(root)
    fingerprint = str(operations.generation_input(role_id)["input_fingerprint"])
    versions = _append_versions(operations, role_id, fingerprint, 12)
    client = TestClient(create_app(root), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    client.cookies.set("job_learning_current_role", role_id)

    first = client.get("/roadmaps")
    assert first.status_code == 200
    assert "Roadmap history: 12 / 30" in first.text
    assert first.text.count("Open Detail") == 10
    assert str(versions[-1].roadmap_id) in first.text
    assert str(versions[0].roadmap_id) not in first.text
    assert "Stored version 11" not in first.text

    second = client.get("/roadmaps?history_page=2")
    assert second.text.count("Open Detail") == 2
    assert str(versions[0].roadmap_id) in second.text


def test_detail_uses_stored_content_is_role_scoped_and_export_is_exact_utf8(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    operations, _, role_id, _ = _ready_role(root)
    fingerprint = str(operations.generation_input(role_id)["input_fingerprint"])
    content = "# 路线图\n\n- 原始 Markdown ✅"
    operations.save_result(role_id, _result(fingerprint, content))
    roadmap_id = operations.view(role_id).history[0].roadmap_id
    other = operations.storage.create_role("Other Role")

    detail = operations.detail(role_id, roadmap_id)
    assert detail.latest is True
    assert detail.matches_current_inputs is True
    assert "路线图" in detail.html
    with pytest.raises(ApplicationError):
        operations.detail(str(other.role_id), roadmap_id)

    client = TestClient(create_app(root), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    client.cookies.set("job_learning_current_role", role_id)
    exported = client.get(f"/roadmaps/{roadmap_id}/export")
    assert exported.status_code == 200
    assert exported.content == content.encode("utf-8")
    assert "filename*=UTF-8''" in exported.headers["content-disposition"]
    assert exported.headers["content-disposition"].endswith(".md")
    assert roadmap_id not in exported.headers["content-disposition"]
    assert client.get(f"/roadmaps/{roadmap_id}").status_code == 200

    client.cookies.set("job_learning_current_role", str(other.role_id))
    assert client.get(f"/roadmaps/{roadmap_id}").status_code == 422
    assert client.get(f"/roadmaps/{roadmap_id}/export").status_code == 422

    safe_name = operations._export_filename(
        'Data / AI: "Lead"', datetime(2026, 9, 14, 12, 30, tzinfo=timezone.utc)
    )
    assert safe_name == "Data_AI_Lead_roadmap_20260914_123000.md"


def test_retention_persists_new_version_before_removing_oldest_per_role(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    operations, _, role_id, _ = _ready_role(root)
    fingerprint = str(operations.generation_input(role_id)["input_fingerprint"])
    old = _append_versions(operations, role_id, fingerprint, 29)
    other = operations.storage.create_role("Other Role")
    other_version = RoadmapVersion(
        role_id=other.role_id,
        generated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        input_fingerprint="a" * 64,
        content="# Other",
    )
    operations.storage.append_roadmap(other_version)

    operations.save_result(role_id, _result(fingerprint, "# Version thirty"))
    assert len(operations.storage.list_roadmaps(operations._uuid(role_id, "role_id"))) == 30
    assert operations.storage.list_roadmaps(operations._uuid(role_id, "role_id"))[0] == old[0]

    operations.save_result(role_id, _result(fingerprint, "# Version thirty-one"))
    retained = operations.storage.list_roadmaps(operations._uuid(role_id, "role_id"))
    assert len(retained) == MAX_ROADMAP_VERSIONS_PER_ROLE
    assert old[0] not in retained
    assert retained[-1].content == "# Version thirty-one"
    assert operations.storage.list_roadmaps(other.role_id) == [other_version]

    before = tuple(retained)
    with pytest.raises(ApplicationError):
        operations.save_result(role_id, "{}")
    assert tuple(
        operations.storage.list_roadmaps(operations._uuid(role_id, "role_id"))
    ) == before


def test_retention_cleanup_observes_new_version_already_persisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "state"
    operations, _, role_id, _ = _ready_role(root)
    fingerprint = str(operations.generation_input(role_id)["input_fingerprint"])
    observed: list[bool] = []
    original = operations.storage.enforce_roadmap_retention

    def observe(role, *, preserve_roadmap_id, limit=MAX_ROADMAP_VERSIONS_PER_ROLE):
        observed.append(
            any(
                item.roadmap_id == preserve_roadmap_id
                for item in operations.storage.list_roadmaps(role)
            )
        )
        return original(
            role, preserve_roadmap_id=preserve_roadmap_id, limit=limit
        )

    monkeypatch.setattr(operations.storage, "enforce_roadmap_retention", observe)
    operations.save_result(role_id, _result(fingerprint, "# Safely persisted first"))
    assert observed == [True]


def test_single_delete_allows_latest_and_historical_without_touching_sources(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    operations, _, role_id, _ = _ready_role(root)
    fingerprint = str(operations.generation_input(role_id)["input_fingerprint"])
    operations.save_result(role_id, _result(fingerprint, "# First"))
    operations.save_result(role_id, _result(fingerprint, "# Second"))
    before_catalog = operations.storage.load_catalog()
    before_jds = operations.storage.load_jds(operations._uuid(role_id, "role_id"))
    view = operations.view(role_id)
    latest_id, historical_id = view.history[0].roadmap_id, view.history[1].roadmap_id

    operations.delete(role_id, historical_id)
    remaining = operations.view(role_id)
    assert [item.roadmap_id for item in remaining.history] == [latest_id]
    operations.delete(role_id, latest_id)
    assert operations.view(role_id).history == ()
    assert operations.view(role_id).state_key == "missing"
    assert operations.storage.load_catalog() == before_catalog
    assert operations.storage.load_jds(operations._uuid(role_id, "role_id")) == before_jds

    other = operations.storage.create_role("Other Role")
    with pytest.raises(ApplicationError):
        operations.delete(str(other.role_id), latest_id)


def test_full_capacity_warning_and_delete_route(tmp_path: Path) -> None:
    root = tmp_path / "state"
    operations, _, role_id, _ = _ready_role(root)
    fingerprint = str(operations.generation_input(role_id)["input_fingerprint"])
    _append_versions(operations, role_id, fingerprint, 30)
    client = TestClient(create_app(root), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    client.cookies.set("job_learning_current_role", role_id)
    page = client.get("/roadmaps")
    assert "next successful generation will remove the oldest" in page.text

    latest_id = operations.view(role_id).history[0].roadmap_id
    response = client.post(
        f"/roadmaps/{latest_id}/delete",
        data={"role_id": role_id},
        follow_redirects=False,
    )
    assert response.status_code == 303
    after = operations.view(role_id)
    assert len(after.history) == 29
    assert after.history[0].latest is True
