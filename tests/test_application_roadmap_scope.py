from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from application.capabilities import CapabilityOperations
from application.errors import ApplicationError
from application.learning import LearningOperations
from application.market import MarketOperations
from application.roadmaps import RoadmapOperations
from schemas.core import AtomicMarketSignal, JDAnalysis
from src.market import jd_source_fingerprint
from tests.test_application_learning import _mapped_roles


def _scope_path(root: Path, role_id: str) -> Path:
    return root / "roles" / role_id / "roadmap_scope.json"


def test_default_exclude_include_idempotency_and_deterministic_storage(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    role_a, _, ids = _mapped_roles(root)
    operations = LearningOperations(root)
    role_uuid = operations._uuid(role_a, "role_id")
    python_uuid = operations._uuid(ids["Python"], "capability_id")
    docker_uuid = operations._uuid(ids["Docker"], "capability_id")
    path = _scope_path(root, role_a)

    initial = operations.view(role_a)
    assert all(item.included_in_roadmap for item in initial.capabilities)
    assert initial.roadmap_scope_sha256 is None
    assert not path.exists()

    operations.set_roadmap_inclusion(
        role_a, ids["Python"], False, expected_sha256=None
    )
    excluded = operations.view(role_a)
    assert next(
        item for item in excluded.capabilities if item.name == "Python"
    ).included_in_roadmap is False
    first_bytes = path.read_bytes()
    operations.set_roadmap_inclusion(
        role_a,
        ids["Python"],
        False,
        expected_sha256=excluded.roadmap_scope_sha256,
    )
    assert path.read_bytes() == first_bytes

    operations.set_roadmap_inclusion(
        role_a,
        ids["Docker"],
        False,
        expected_sha256=operations.view(role_a).roadmap_scope_sha256,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {
        "excluded_capability_ids": sorted([str(python_uuid), str(docker_uuid)]),
        "role_id": str(role_uuid),
        "schema_version": "1.0",
    }

    operations.set_roadmap_inclusion(
        role_a,
        ids["Python"],
        True,
        expected_sha256=operations.view(role_a).roadmap_scope_sha256,
    )
    operations.set_roadmap_inclusion(
        role_a,
        ids["Docker"],
        True,
        expected_sha256=operations.view(role_a).roadmap_scope_sha256,
    )
    assert not path.exists()
    operations.set_roadmap_inclusion(
        role_a, ids["Docker"], True, expected_sha256=None
    )
    assert not path.exists()


def test_scope_rejects_invalid_references_and_corruption_without_overwrite(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    role_a, _, ids = _mapped_roles(root)
    operations = LearningOperations(root)

    with pytest.raises(ApplicationError, match="Role 不存在"):
        operations.set_roadmap_inclusion(
            str(uuid4()), ids["Python"], False, expected_sha256=None
        )
    with pytest.raises(ValueError, match="Capability 不存在"):
        operations.storage.set_roadmap_scope_inclusion(
            operations._uuid(role_a, "role_id"),
            uuid4(),
            False,
            expected_sha256=None,
        )

    path = _scope_path(root, role_a)
    path.write_text('{"role_id":"broken"}\n', encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Core storage 文件无效"):
        operations.storage.load_roadmap_scope_snapshot(
            operations._uuid(role_a, "role_id")
        )
    assert path.read_bytes() == before


def test_scope_is_role_specific_and_new_capability_defaults_to_included(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    role_a, role_b, ids = _mapped_roles(root)
    operations = LearningOperations(root)
    operations.set_roadmap_inclusion(
        role_a, ids["Docker"], False, expected_sha256=None
    )

    assert next(
        item for item in operations.view(role_a).capabilities if item.name == "Docker"
    ).included_in_roadmap is False
    assert next(
        item for item in operations.view(role_b).capabilities if item.name == "Docker"
    ).included_in_roadmap is True

    store = operations.storage
    capability = store.create_capability("Kubernetes")
    store.add_source_mapping("Kubernetes", capability.capability_id)
    market = MarketOperations(root)
    current = market.view(role_a)
    market.add_job(
        role_a,
        title="Platform",
        company=None,
        jd_text="Kubernetes",
        source_url=None,
        expected_sha256=current.jds_sha256 or "",
    )
    jobs = store.load_jds(operations._uuid(role_a, "role_id"))
    # A newly added JD needs current analysis before it enters the working set.
    new_job = jobs.jobs[-1]
    store.save_jd_analysis(
        JDAnalysis(
            job_id=new_job.job_id,
            role_id=new_job.role_id,
            source_fingerprint=jd_source_fingerprint(new_job),
            signals=[
                AtomicMarketSignal(
                    source_expression="Kubernetes",
                    atomic_expression="Kubernetes",
                    evidence="Kubernetes",
                )
            ],
        )
    )
    assert next(
        item
        for item in operations.view(role_a).capabilities
        if item.name == "Kubernetes"
    ).included_in_roadmap is True


def test_unmap_reassign_rename_and_dormant_reactivation_preserve_scope(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    role_a, _, ids = _mapped_roles(root)
    learning = LearningOperations(root)
    capabilities = CapabilityOperations(root)
    learning.set_roadmap_inclusion(
        role_a, ids["Python"], False, expected_sha256=None
    )
    role_uuid = learning._uuid(role_a, "role_id")
    python_uuid = learning._uuid(ids["Python"], "capability_id")

    detail = capabilities.detail(role_a, ids["Python"])
    capabilities.rename(
        role_a,
        ids["Python"],
        "Python Engineering",
        expected_catalog_sha256=detail.catalog_sha256,
    )
    assert python_uuid in learning.storage.load_roadmap_scope_snapshot(role_uuid)[
        0
    ].excluded_capability_ids

    detail = capabilities.detail(role_a, ids["Python"])
    capabilities.unmap(
        role_a,
        ids["Python"],
        "Python",
        expected_catalog_sha256=detail.catalog_sha256,
    )
    assert all(
        item.capability_id != ids["Python"]
        for item in learning.view(role_a).capabilities
    )
    assert python_uuid in learning.storage.load_roadmap_scope_snapshot(role_uuid)[
        0
    ].excluded_capability_ids

    learning.storage.add_source_mapping("Python", python_uuid)
    restored = next(
        item
        for item in learning.view(role_a).capabilities
        if item.capability_id == ids["Python"]
    )
    assert restored.included_in_roadmap is False

    detail = capabilities.detail(role_a, ids["Python"])
    capabilities.reassign(
        role_a,
        ids["Python"],
        "Python",
        "Excel",
        expected_catalog_sha256=detail.catalog_sha256,
    )
    assert python_uuid in learning.storage.load_roadmap_scope_snapshot(role_uuid)[
        0
    ].excluded_capability_ids
    excel = next(
        item for item in learning.view(role_a).capabilities if item.name == "Excel"
    )
    assert excel.included_in_roadmap is True


def test_role_and_capability_delete_clean_scope_without_touching_other_facts(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    role_a, role_b, ids = _mapped_roles(root)
    learning = LearningOperations(root)
    store = learning.storage
    role_a_uuid = learning._uuid(role_a, "role_id")
    role_b_uuid = learning._uuid(role_b, "role_id")
    excel_uuid = learning._uuid(ids["Excel"], "capability_id")
    python_uuid = learning._uuid(ids["Python"], "capability_id")

    store.set_roadmap_scope_inclusion(
        role_a_uuid, excel_uuid, False, expected_sha256=None
    )
    store.set_roadmap_scope_inclusion(
        role_a_uuid,
        python_uuid,
        False,
        expected_sha256=store.load_roadmap_scope_snapshot(role_a_uuid)[1],
    )
    store.set_roadmap_scope_inclusion(
        role_b_uuid, excel_uuid, False, expected_sha256=None
    )
    store.set_current_level(excel_uuid, 4)
    store.add_practice(excel_uuid, "Built a workbook")

    capability_ops = CapabilityOperations(root)
    detail = capability_ops.detail(role_a, ids["Excel"])
    capability_ops.delete_capability(
        role_a,
        ids["Excel"],
        expected_catalog_sha256=detail.catalog_sha256,
        expected_personal_states_sha256=detail.personal_states_sha256,
        expected_practices_sha256=detail.practices_sha256,
        expected_knowledge_sha256=detail.knowledge.expected_sha256,
    )
    assert store.load_roadmap_scope_snapshot(role_a_uuid)[
        0
    ].excluded_capability_ids == [python_uuid]
    assert not _scope_path(root, role_b).exists()
    assert all(
        item.capability_id != excel_uuid
        for item in store.load_personal_states().states
    )
    assert all(
        item.capability_id != excel_uuid
        for item in store.load_practices().practices
    )

    market = MarketOperations(root)
    role = next(item for item in market.view().roles if item.role_id == role_a)
    market.delete_role(
        role_a,
        confirmation=role.name,
        expected_sha256=market.view(role_a).roles_sha256,
    )
    assert not (root / "roles" / role_a).exists()
    assert store.load_roadmap_scope_snapshot(role_b_uuid)[0].excluded_capability_ids == []


def test_capability_delete_rolls_back_scope_cleanup_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "state"
    role_a, role_b, ids = _mapped_roles(root)
    learning = LearningOperations(root)
    store = learning.storage
    excel_uuid = learning._uuid(ids["Excel"], "capability_id")
    for role_id in (role_a, role_b):
        store.set_roadmap_scope_inclusion(
            learning._uuid(role_id, "role_id"),
            excel_uuid,
            False,
            expected_sha256=None,
        )
    store.set_current_level(excel_uuid, 2)
    store.add_practice(excel_uuid, "Keep on failure")
    scope_a = _scope_path(root, role_a)
    scope_b = _scope_path(root, role_b)
    paths = (
        store.catalog_path,
        store.personal_states_path,
        store.practices_path,
        scope_a,
        scope_b,
    )
    before = {path: path.read_bytes() for path in paths}
    real_unlink = Path.unlink
    failed = False

    def fail_second_scope_once(path: Path, *args: object, **kwargs: object) -> None:
        nonlocal failed
        if path == scope_b and not failed:
            failed = True
            raise OSError("simulated scope cleanup failure")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_second_scope_once)
    detail = CapabilityOperations(root).detail(role_a, ids["Excel"])
    with pytest.raises(ApplicationError) as error:
        CapabilityOperations(root).delete_capability(
            role_a,
            ids["Excel"],
            expected_catalog_sha256=detail.catalog_sha256,
            expected_personal_states_sha256=detail.personal_states_sha256,
            expected_practices_sha256=detail.practices_sha256,
            expected_knowledge_sha256=detail.knowledge.expected_sha256,
        )
    assert isinstance(error.value.__cause__, OSError)
    assert str(error.value.__cause__) == "simulated scope cleanup failure"
    assert {path: path.read_bytes() for path in paths} == before


def test_scope_changes_enter_stage_two_roadmap_input_and_fingerprint(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    role_a, _, ids = _mapped_roles(root)
    roadmaps = RoadmapOperations(root)
    learning = LearningOperations(root)
    before = roadmaps.generation_input(role_a)

    learning.set_roadmap_inclusion(
        role_a, ids["Python"], False, expected_sha256=None
    )

    after = roadmaps.generation_input(role_a)
    assert after["input_fingerprint"] != before["input_fingerprint"]
    assert "Python" in {item["name"] for item in before["capabilities"]}
    assert "Python" not in {item["name"] for item in after["capabilities"]}
