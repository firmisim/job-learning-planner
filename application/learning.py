from __future__ import annotations

from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from application.capabilities import CapabilityOperations
from application.errors import ApplicationError
from application.learning_models import (
    LearningDetailView,
    LearningCapabilityView,
    LevelCriterionView,
    MyLearningView,
    PracticeView,
)
from src.core_storage import CoreStorage
from src.level_criteria import applicable_level_criteria
from src.state_safety import StaleStateError


class LearningOperations:
    """Application boundary for global personal facts in a Role-scoped view."""

    def __init__(self, storage_root: Path) -> None:
        self.storage = CoreStorage(storage_root)
        self.storage.initialize()
        self.capabilities = CapabilityOperations(storage_root)

    @staticmethod
    def _uuid(value: str, label: str) -> UUID:
        try:
            return UUID(value)
        except (TypeError, ValueError) as exc:
            raise ApplicationError(
                "validation", "update My Learning", f"{label} 无效"
            ) from exc

    def view(self, role_id: str | None) -> MyLearningView:
        workspace = self.capabilities.workspace(role_id)
        states, states_sha256 = self.storage.load_personal_states_snapshot()
        practices, practices_sha256 = self.storage.load_practices_snapshot()
        scope_sha256: str | None = None
        excluded_capability_ids: set[UUID] = set()
        if role_id is not None:
            selected_role = self._uuid(role_id, "role_id")
            scope, scope_sha256 = self.storage.load_roadmap_scope_snapshot(
                selected_role
            )
            excluded_capability_ids = set(scope.excluded_capability_ids)
        levels = {item.capability_id: item.current_level for item in states.states}
        practices_by_capability: dict[UUID, list[PracticeView]] = {}
        for item in practices.practices:
            practices_by_capability.setdefault(item.capability_id, []).append(
                PracticeView(str(item.practice_id), item.description)
            )
        return MyLearningView(
            workspace.current_role,
            tuple(
                LearningCapabilityView(
                    item.capability_id,
                    item.name,
                    levels.get(UUID(item.capability_id)),
                    tuple(practices_by_capability.get(UUID(item.capability_id), [])),
                    item.knowledge_status,
                    UUID(item.capability_id) not in excluded_capability_ids,
                )
                for item in workspace.current_capabilities
            ),
            states_sha256,
            practices_sha256,
            scope_sha256,
        )

    def detail(self, role_id: str, capability_id: str) -> LearningDetailView:
        selected, item = self._require_current_capability(role_id, capability_id)
        capability_detail = self.capabilities.detail(role_id, str(selected))
        knowledge = capability_detail.knowledge.value
        usable_knowledge = (
            knowledge
            if capability_detail.knowledge.status_key == "available"
            else None
        )
        criteria_source, criteria = applicable_level_criteria(usable_knowledge)
        view = self.view(role_id)
        assert view.current_role is not None
        return LearningDetailView(
            view.current_role,
            item,
            criteria_source,
            tuple(
                LevelCriterionView(level, criterion)
                for level, criterion in enumerate(criteria)
            ),
            tuple(value.text for value in knowledge.prerequisites) if knowledge else (),
            tuple(value.text for value in knowledge.core_topics) if knowledge else (),
            tuple(value.text for value in knowledge.useful_practices) if knowledge else (),
            tuple(value.text for value in knowledge.acceptance_criteria) if knowledge else (),
            capability_detail.knowledge.status_key,
            view.personal_states_sha256,
            view.practices_sha256,
            view.roadmap_scope_sha256,
        )

    def _require_current_capability(
        self, role_id: str, capability_id: str
    ) -> tuple[UUID, LearningCapabilityView]:
        selected = self._uuid(capability_id, "capability_id")
        item = next(
            (
                item
                for item in self.view(role_id).capabilities
                if item.capability_id == str(selected)
            ),
            None,
        )
        if item is None:
            raise ApplicationError(
                "validation",
                "update My Learning",
                "Capability 不属于当前 Role",
            )
        return selected, item

    @staticmethod
    def _error(operation: str, exc: Exception) -> ApplicationError:
        category = "conflict" if isinstance(exc, StaleStateError) else "validation"
        return ApplicationError(category, operation, str(exc))

    def set_level(
        self,
        role_id: str,
        capability_id: str,
        current_level: int,
        *,
        expected_sha256: str,
    ) -> str:
        selected, _ = self._require_current_capability(role_id, capability_id)
        if type(current_level) is not int or not 0 <= current_level <= 5:
            raise ApplicationError(
                "validation",
                "set current level",
                "current_level 必须是 0–5 的整数",
            )
        try:
            self.storage.set_current_level(
                selected,
                current_level,
                expected_sha256=expected_sha256,
            )
        except (ValidationError, ValueError, StaleStateError) as exc:
            raise self._error("set current level", exc) from exc
        return "当前水平已保存"

    def set_roadmap_inclusion(
        self,
        role_id: str,
        capability_id: str,
        included: bool,
        *,
        expected_sha256: str | None,
    ) -> str:
        selected, _ = self._require_current_capability(role_id, capability_id)
        if type(included) is not bool:
            raise ApplicationError(
                "validation", "set Roadmap Scope", "included 必须是 boolean"
            )
        try:
            self.storage.set_roadmap_scope_inclusion(
                self._uuid(role_id, "role_id"),
                selected,
                included,
                expected_sha256=expected_sha256,
            )
        except (ValidationError, ValueError, StaleStateError) as exc:
            raise self._error("set Roadmap Scope", exc) from exc
        return (
            "已纳入当前 Role 的学习路线"
            if included
            else "已从当前 Role 的学习路线排除"
        )

    def add_practice(
        self,
        role_id: str,
        capability_id: str,
        description: str,
        *,
        expected_sha256: str,
    ) -> str:
        selected, _ = self._require_current_capability(role_id, capability_id)
        if not description.strip():
            raise ApplicationError(
                "validation", "add Practice", "Practice description 不能为空"
            )
        try:
            self.storage.add_practice(
                selected,
                description,
                expected_sha256=expected_sha256,
            )
        except (ValidationError, ValueError, StaleStateError) as exc:
            raise self._error("add Practice", exc) from exc
        return "Practice 已添加"

    def edit_practice(
        self,
        role_id: str,
        capability_id: str,
        practice_id: str,
        description: str,
        *,
        expected_sha256: str,
    ) -> str:
        _, capability = self._require_current_capability(role_id, capability_id)
        selected_practice = self._uuid(practice_id, "practice_id")
        if all(item.practice_id != practice_id for item in capability.practices):
            raise ApplicationError(
                "validation", "edit Practice", "Practice 不属于当前 Capability"
            )
        try:
            if not description.strip():
                self.storage.delete_practice(
                    selected_practice,
                    expected_sha256=expected_sha256,
                )
                return "Practice 已移除"
            self.storage.edit_practice(
                selected_practice,
                description,
                expected_sha256=expected_sha256,
            )
        except (ValidationError, ValueError, StaleStateError) as exc:
            raise self._error("edit Practice", exc) from exc
        return "Practice 已更新"

    def stage_f_input(self, role_id: str) -> dict[str, object]:
        view = self.view(role_id)
        if view.current_role is None:
            raise ApplicationError(
                "validation", "prepare personal Roadmap input", "Role 不存在"
            )
        return {
            "role_id": view.current_role.role_id,
            "capabilities": [
                {
                    "capability_id": item.capability_id,
                    "name": item.name,
                    "current_level": item.current_level,
                    "practices": [
                        {
                            "practice_id": practice.practice_id,
                            "description": practice.description,
                        }
                        for practice in item.practices
                    ],
                }
                for item in view.capabilities
            ],
        }
