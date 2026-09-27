from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import application.learning as learning_module
from application.errors import ApplicationError
from application.learning import LearningOperations
from application.market import MarketOperations
from application.capabilities import CapabilityOperations
from src.core_storage import CoreStorage
from tests.test_application_capabilities import _role_with_signals
from tests.test_application_knowledge import _knowledge_payload


def _mapped_roles(root: Path) -> tuple[str, str, dict[str, str]]:
    market = MarketOperations(root)
    role_a = _role_with_signals(market, "Role A", ["Python", "Docker"])
    role_b = _role_with_signals(market, "Role B", ["Java", "Docker"])
    store = CoreStorage(root)
    capabilities: dict[str, str] = {}
    for name in ("Python", "Docker", "Java", "Excel"):
        capability = store.create_capability(name)
        capabilities[name] = str(capability.capability_id)
        if name != "Excel":
            store.add_source_mapping(name, capability.capability_id)
    return role_a, role_b, capabilities


def test_unset_and_zero_are_distinct_and_level_is_global_across_roles(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    role_a, role_b, ids = _mapped_roles(root)
    operations = LearningOperations(root)

    before = operations.view(role_a)
    assert {item.name: item.current_level for item in before.capabilities} == {
        "Docker": None,
        "Python": None,
    }
    operations.set_level(
        role_a,
        ids["Python"],
        0,
        expected_sha256=before.personal_states_sha256,
    )
    current = operations.view(role_a)
    assert {item.name: item.current_level for item in current.capabilities} == {
        "Docker": None,
        "Python": 0,
    }
    operations.set_level(
        role_a,
        ids["Docker"],
        3,
        expected_sha256=current.personal_states_sha256,
    )
    assert next(
        item for item in operations.view(role_b).capabilities if item.name == "Docker"
    ).current_level == 3
    assert len(operations.storage.load_personal_states().states) == 2


@pytest.mark.parametrize("value", [-1, 6, 2.5, True])
def test_invalid_levels_are_rejected(tmp_path: Path, value: object) -> None:
    root = tmp_path / "state"
    role_a, _, ids = _mapped_roles(root)
    operations = LearningOperations(root)
    with pytest.raises(ApplicationError):
        operations.set_level(
            role_a,
            ids["Python"],
            value,  # type: ignore[arg-type]
            expected_sha256=operations.view(role_a).personal_states_sha256,
        )
    assert operations.storage.load_personal_states().states == []


def test_role_scope_shared_practice_crud_and_fact_independence(tmp_path: Path) -> None:
    root = tmp_path / "state"
    role_a, role_b, ids = _mapped_roles(root)
    operations = LearningOperations(root)

    view_a = operations.view(role_a)
    assert [item.name for item in view_a.capabilities] == ["Docker", "Python"]
    assert [item.name for item in operations.view(role_b).capabilities] == [
        "Docker",
        "Java",
    ]
    operations.add_practice(
        role_a,
        ids["Docker"],
        "完成 Docker Compose 多服务项目",
        expected_sha256=view_a.practices_sha256,
    )
    shared = next(
        item for item in operations.view(role_b).capabilities if item.name == "Docker"
    )
    assert [item.description for item in shared.practices] == [
        "完成 Docker Compose 多服务项目"
    ]
    practice_id = shared.practices[0].practice_id
    assert shared.current_level is None

    operations.edit_practice(
        role_b,
        ids["Docker"],
        practice_id,
        "完成 Docker Compose 与健康检查项目",
        expected_sha256=operations.view(role_b).practices_sha256,
    )
    assert operations.storage.load_practices().practices[0].description.endswith(
        "健康检查项目"
    )
    assert operations.storage.load_personal_states().states == []

    operations.set_level(
        role_a,
        ids["Docker"],
        2,
        expected_sha256=operations.view(role_a).personal_states_sha256,
    )
    assert len(operations.storage.load_practices().practices) == 1
    operations.edit_practice(
        role_a,
        ids["Docker"],
        practice_id,
        "   ",
        expected_sha256=operations.view(role_a).practices_sha256,
    )
    assert operations.storage.load_practices().practices == []


def test_unrelated_global_facts_are_hidden_and_stage_f_input_is_minimal(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    role_a, _, ids = _mapped_roles(root)
    operations = LearningOperations(root)
    store = operations.storage
    excel_id = operations._uuid(ids["Excel"], "capability_id")
    store.set_current_level(excel_id, 5)
    store.add_practice(excel_id, "Built an unrelated workbook")
    python_id = operations._uuid(ids["Python"], "capability_id")
    store.set_current_level(python_id, 1)

    view = operations.view(role_a)
    assert "Excel" not in [item.name for item in view.capabilities]
    payload = operations.stage_f_input(role_a)
    assert [item["name"] for item in payload["capabilities"]] == [  # type: ignore[index]
        "Docker",
        "Python",
    ]
    python = payload["capabilities"][1]  # type: ignore[index]
    assert python["current_level"] == 1
    assert python["practices"] == []
    assert not {
        "assessment",
        "target_level",
        "gap",
        "learning_state",
        "evidence",
        "progress",
    } & set(python)
    assert not (root / "capability_assessment.yaml").exists()
    assert not (root / "gap_analysis.json").exists()
    assert not (root / "learning_state.yaml").exists()
    assert not (root / "practice_evidence.yaml").exists()
    assert not (root / "capability_progress.jsonl").exists()


def test_new_learning_path_has_no_legacy_personal_dependencies() -> None:
    source = inspect.getsource(learning_module)
    prohibited = (
        "capability_assessment",
        "gap_analysis",
        "learning_state",
        "practice_evidence",
        "capability_progress",
    )
    assert not any(value in source for value in prohibited)


def test_detail_uses_generic_then_shared_specific_criteria_without_scoring(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    role_a, role_b, ids = _mapped_roles(root)
    learning = LearningOperations(root)

    generic = learning.detail(role_a, ids["Docker"])
    assert generic.criteria_source == "generic"
    assert [item.level for item in generic.level_criteria] == list(range(6))
    assert generic.capability.current_level is None

    capabilities = CapabilityOperations(root)
    research_input = capabilities.knowledge_research_input(role_a, ids["Docker"])
    before_states = learning.storage.load_personal_states()
    before_practices = learning.storage.load_practices()
    capabilities.save_knowledge_result(
        role_a,
        ids["Docker"],
        _knowledge_payload(research_input, level_prefix="Docker"),
        expected_knowledge_sha256=None,
    )

    specific_a = learning.detail(role_a, ids["Docker"])
    specific_b = learning.detail(role_b, ids["Docker"])
    assert specific_a.criteria_source == "capability-specific"
    assert specific_a.level_criteria == specific_b.level_criteria
    assert specific_a.level_criteria[3].text == "Docker Level 3: observable task 3"
    assert learning.storage.load_personal_states() == before_states
    assert learning.storage.load_practices() == before_practices
