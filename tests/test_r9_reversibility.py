from datetime import datetime
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from application.capabilities import CapabilityOperations
from application.learning import LearningOperations
from application.market import MarketOperations
from application.roadmaps import RoadmapOperations
from schemas.core import RoadmapVersion
from tests.test_application_capabilities import _role_with_signals
from tests.test_application_knowledge import _knowledge_payload
from ui.app import create_app


def _shared_mapping(root: Path) -> tuple[CapabilityOperations, str, str, str, str]:
    market = MarketOperations(root)
    role_a = _role_with_signals(market, "Role A", ["Fast API"])
    role_b = _role_with_signals(market, "Role B", ["Fast API"])
    operations = CapabilityOperations(root)
    target_a = operations.storage.create_capability("FastAPI")
    target_b = operations.storage.create_capability("Python Web")
    candidate = operations.workspace(role_a).pending_candidates[0]
    operations.merge(
        role_a,
        candidate.candidate_fingerprint,
        str(target_a.capability_id),
        expected_catalog_sha256=operations.workspace(role_a).catalog_sha256,
    )
    return operations, role_a, role_b, str(target_a.capability_id), str(target_b.capability_id)


def _save_knowledge(
    operations: CapabilityOperations, role_id: str, capability_id: str
) -> None:
    request = operations.knowledge_research_input(role_id, capability_id)
    operations.save_knowledge_result(
        role_id,
        capability_id,
        _knowledge_payload(request),
        expected_knowledge_sha256=None,
    )


def test_unmap_returns_current_sources_to_pending_and_preserves_history(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    operations, role_a, role_b, target_a, _ = _shared_mapping(root)
    role_uuid = operations._uuid(role_a, "role_id")
    history = RoadmapVersion(
        role_id=role_uuid,
        generated_at=datetime.fromisoformat("2026-09-14T10:00:00+08:00"),
        input_fingerprint="a" * 64,
        content="Historical FastAPI roadmap",
    )
    operations.storage.append_roadmap(history)
    before_fingerprint = RoadmapOperations(root).generation_input(role_a)[
        "input_fingerprint"
    ]
    detail = operations.detail(role_a, target_a)

    assert detail.mappings[0].affected_roles == ("Role A", "Role B")
    operations.unmap(
        role_a,
        target_a,
        "Fast API",
        expected_catalog_sha256=detail.catalog_sha256,
    )

    assert [item.atomic_expression for item in operations.workspace(role_a).pending_candidates] == ["Fast API"]
    assert [item.atomic_expression for item in operations.workspace(role_b).pending_candidates] == ["Fast API"]
    assert RoadmapOperations(root).generation_input(role_a)["input_fingerprint"] != before_fingerprint
    assert operations.storage.list_roadmaps(role_uuid) == [history]


def test_reassign_is_one_catalog_write_and_updates_all_role_working_sets(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    operations, role_a, role_b, target_a, target_b = _shared_mapping(root)
    detail = operations.detail(role_a, target_a)
    operations.reassign(
        role_a,
        target_a,
        "Fast API",
        "Python Web",
        expected_catalog_sha256=detail.catalog_sha256,
    )

    catalog = operations.storage.load_catalog()
    mapping = catalog.source_mappings[0]
    assert str(mapping.capability_id) == target_b
    assert all(
        [item.name for item in operations.workspace(role).current_capabilities]
        == ["Python Web"]
        for role in (role_a, role_b)
    )
    with pytest.raises(Exception, match="SourceMapping"):
        operations.storage.reassign_source_mapping(
            "Fast API",
            operations._uuid(target_a, "capability_id"),
            operations._uuid(target_b, "capability_id"),
            expected_sha256=operations.workspace(role_a).catalog_sha256,
        )


def test_remove_knowledge_preserves_capability_mapping_level_and_practice(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    operations, role_a, _, target_a, _ = _shared_mapping(root)
    _save_knowledge(operations, role_a, target_a)
    learning = LearningOperations(root)
    view = learning.view(role_a)
    learning.set_level(role_a, target_a, 3, expected_sha256=view.personal_states_sha256)
    view = learning.view(role_a)
    learning.add_practice(
        role_a, target_a, "Built a production API", expected_sha256=view.practices_sha256
    )
    before_fingerprint = RoadmapOperations(root).generation_input(role_a)["input_fingerprint"]
    detail = operations.detail(role_a, target_a)

    operations.remove_knowledge(
        role_a,
        target_a,
        expected_knowledge_sha256=detail.knowledge.expected_sha256 or "",
    )

    assert operations.detail(role_a, target_a).knowledge.value is None
    assert operations.storage.load_catalog().source_mappings
    assert operations.storage.load_personal_states().states[0].current_level == 3
    assert operations.storage.load_practices().practices[0].description == "Built a production API"
    assert RoadmapOperations(root).view(role_a).can_generate is True
    assert RoadmapOperations(root).generation_input(role_a)["input_fingerprint"] != before_fingerprint


def test_delete_orphan_removes_owned_current_data_but_not_historical_roadmap(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    market = MarketOperations(root)
    role_id = _role_with_signals(market, "Role", ["Unrelated signal"])
    operations = CapabilityOperations(root)
    capability = operations.storage.create_capability("Orphan Capability")
    capability_id = str(capability.capability_id)
    _save_knowledge(operations, role_id, capability_id)
    states = operations.storage.load_personal_states_snapshot()
    operations.storage.set_current_level(
        capability.capability_id, 2, expected_sha256=states[1]
    )
    practices = operations.storage.load_practices_snapshot()
    operations.storage.add_practice(
        capability.capability_id, "Orphan practice", expected_sha256=practices[1]
    )
    role_uuid = operations._uuid(role_id, "role_id")
    history = RoadmapVersion(
        role_id=role_uuid,
        generated_at=datetime.fromisoformat("2026-09-14T11:00:00+08:00"),
        input_fingerprint="b" * 64,
        content="Snapshot mentions Orphan Capability",
    )
    operations.storage.append_roadmap(history)
    detail = operations.detail(role_id, capability_id)
    assert detail.in_current_role is False

    operations.delete_capability(
        role_id,
        capability_id,
        expected_catalog_sha256=detail.catalog_sha256,
        expected_personal_states_sha256=detail.personal_states_sha256,
        expected_practices_sha256=detail.practices_sha256,
        expected_knowledge_sha256=detail.knowledge.expected_sha256,
    )

    assert capability not in operations.storage.load_catalog().capabilities
    assert not (operations.storage.knowledge_root / f"{capability_id}.json").exists()
    assert all(item.capability_id != capability.capability_id for item in operations.storage.load_personal_states().states)
    assert all(item.capability_id != capability.capability_id for item in operations.storage.load_practices().practices)
    assert operations.storage.list_roadmaps(role_uuid) == [history]


def test_delete_is_blocked_only_by_active_mapping(tmp_path: Path) -> None:
    root = tmp_path / "state"
    operations, role_a, _, target_a, _ = _shared_mapping(root)
    detail = operations.detail(role_a, target_a)
    with pytest.raises(Exception, match="Unmap 或 Reassign"):
        operations.delete_capability(
            role_a,
            target_a,
            expected_catalog_sha256=detail.catalog_sha256,
            expected_personal_states_sha256=detail.personal_states_sha256,
            expected_practices_sha256=detail.practices_sha256,
            expected_knowledge_sha256=detail.knowledge.expected_sha256,
        )


def test_capability_delete_rolls_back_every_owned_file_on_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.state_safety as safety

    root = tmp_path / "state"
    market = MarketOperations(root)
    role_id = _role_with_signals(market, "Role", ["Other"])
    operations = CapabilityOperations(root)
    capability = operations.storage.create_capability("Disposable")
    capability_id = str(capability.capability_id)
    _save_knowledge(operations, role_id, capability_id)
    states = operations.storage.load_personal_states_snapshot()
    operations.storage.set_current_level(capability.capability_id, 1, expected_sha256=states[1])
    practices = operations.storage.load_practices_snapshot()
    operations.storage.add_practice(capability.capability_id, "Keep on failure", expected_sha256=practices[1])
    detail = operations.detail(role_id, capability_id)
    paths = (
        operations.storage.catalog_path,
        operations.storage.personal_states_path,
        operations.storage.practices_path,
        operations.storage.knowledge_root / f"{capability_id}.json",
    )
    before = {path: path.read_bytes() for path in paths}
    real_replace = safety.os.replace
    failed = False

    def fail_catalog_once(source: object, destination: object) -> None:
        nonlocal failed
        if Path(destination) == operations.storage.catalog_path and not failed:
            failed = True
            raise OSError("simulated publish failure")
        real_replace(source, destination)

    monkeypatch.setattr(safety.os, "replace", fail_catalog_once)
    with pytest.raises(Exception):
        operations.delete_capability(
            role_id,
            capability_id,
            expected_catalog_sha256=detail.catalog_sha256,
            expected_personal_states_sha256=detail.personal_states_sha256,
            expected_practices_sha256=detail.practices_sha256,
            expected_knowledge_sha256=detail.knowledge.expected_sha256,
        )

    assert {path: path.read_bytes() for path in paths} == before


def test_ui_exposes_current_fact_corrections_without_new_lifecycles(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    operations, role_a, _, target_a, target_b = _shared_mapping(root)
    _save_knowledge(operations, role_a, target_a)
    client = TestClient(create_app(root), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    client.cookies.set("job_learning_current_role", role_a)

    page = client.get(f"/capabilities/{target_a}")
    assert page.status_code == 200
    assert "Unmap" in page.text and "Reassign" in page.text
    assert "Remove Knowledge" in page.text
    assert "Delete is blocked" in page.text
    assert "Role A" in page.text
    searched = client.get(
        f"/capabilities/{target_a}?reassign_expression=Fast%20API&reassign_query=Python"
    )
    assert "Python Web" in searched.text
    assert target_b not in searched.text

    detail = operations.detail(role_a, target_a)
    unmap = client.post(
        f"/capabilities/{target_a}/mappings/unmap",
        data={
            "role_id": role_a,
            "source_expression": "Fast API",
            "expected_catalog_sha256": detail.catalog_sha256,
        },
        follow_redirects=False,
    )
    assert unmap.status_code == 303
    orphan = client.get(f"/capabilities/{target_a}")
    assert "No mapped expressions" in orphan.text
    assert "Delete Capability" in orphan.text
    catalog = client.get("/capabilities?all_query=FastAPI#all-capabilities")
    assert "FastAPI" in catalog.text and "View and manage" in catalog.text


def test_no_clear_level_separate_practice_delete_or_reversibility_lifecycle() -> None:
    repository = Path(__file__).resolve().parents[1]
    learning_template = (repository / "ui" / "templates" / "learning_detail.html").read_text(encoding="utf-8")
    capability_template = (repository / "ui" / "templates" / "capability_detail.html").read_text(encoding="utf-8")
    schemas = (repository / "schemas" / "core.py").read_text(encoding="utf-8")

    assert "Clear Level" not in learning_template
    assert "Delete Practice" not in learning_template
    assert "t('practice.empty_removes')" in learning_template
    assert "Retire Capability" not in capability_template
    assert not any(name in schemas for name in ("MappingRevision", "UndoRecord", "RetiredCapability", "ImpactState"))
