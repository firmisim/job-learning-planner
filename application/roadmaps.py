from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from application.capabilities import CapabilityOperations
from application.errors import ApplicationError
from application.market import MarketOperations
from application.roadmap_models import (
    RoadmapDetailView,
    RoadmapHistoryItemView,
    RoadmapWorkspaceView,
)
from schemas.core import RoadmapVersion
from schemas.roadmap_generation import RoadmapGenerationResult
from src.core_storage import CoreStorage, MAX_ROADMAP_VERSIONS_PER_ROLE
from src.roadmap import (
    build_roadmap_generation_input,
    latest_roadmap,
    roadmap_markdown_html,
)
from src.semantic_handoff import SemanticHandoffStore, prepared_handoff_message


class RoadmapOperations:
    """Role-scoped Roadmap input, validation and immutable history boundary."""

    def __init__(self, storage_root: Path) -> None:
        self.storage = CoreStorage(storage_root)
        self.storage.initialize()
        self.market = MarketOperations(storage_root)
        self.capabilities = CapabilityOperations(storage_root)
        self.handoffs = SemanticHandoffStore(storage_root)

    @staticmethod
    def _uuid(value: str, label: str) -> UUID:
        try:
            return UUID(value)
        except (TypeError, ValueError) as exc:
            raise ApplicationError(
                "validation", "load Roadmap", f"{label} 无效"
            ) from exc

    def generation_input(self, role_id: str) -> dict[str, object]:
        selected = self._uuid(role_id, "role_id")
        try:
            return build_roadmap_generation_input(self.storage, selected)
        except (ValueError, ValidationError) as exc:
            raise ApplicationError(
                "validation", "prepare Roadmap input", str(exc)
            ) from exc

    def _blockers(
        self, role_id: str, selected_capability_count: int
    ) -> tuple[tuple[str, str], ...]:
        market = self.market.view(role_id)
        capabilities = self.capabilities.workspace(role_id)
        blockers: list[tuple[str, str]] = []
        if not market.jobs:
            blockers.append(("Add at least one JD", "/market"))
        elif market.current_analysis_count == 0:
            blockers.append(("Analyze at least one current JD", "/market#analysis"))
        if capabilities.pending_candidates:
            blockers.append(("Resolve Capability Inbox", "/capabilities/inbox"))
        if not capabilities.current_capabilities:
            blockers.append(("Map at least one Capability", "/capabilities"))
        elif selected_capability_count == 0:
            blockers.append(
                ("Include at least one Capability in Roadmap", "/learning")
            )
        return tuple(blockers)

    def view(self, role_id: str | None) -> RoadmapWorkspaceView:
        if role_id is None:
            return RoadmapWorkspaceView(
                None,
                "no-role",
                "No Role",
                "Create a Role before generating a Roadmap.",
                None,
                False,
                "Generate Roadmap",
                (("Create a Role", "/market"),),
                (),
            )
        market = self.market.view(role_id)
        if market.current_role is None:
            raise ApplicationError("validation", "load Roadmap", "Role 不存在")
        selected_role = self._uuid(role_id, "role_id")
        generation_input = self.generation_input(role_id)
        fingerprint = str(generation_input["input_fingerprint"])
        capability_inputs = generation_input["capabilities"]
        assert isinstance(capability_inputs, list)
        knowledge_ready_count = sum(
            1
            for item in capability_inputs
            if isinstance(item, dict) and item.get("guidance_mode") == "knowledge-ready"
        )
        selected_capability_count = len(capability_inputs)
        relevant_capability_count = len(
            self.capabilities.workspace(role_id).current_capabilities
        )
        knowledge_missing_count = selected_capability_count - knowledge_ready_count
        blockers = self._blockers(role_id, selected_capability_count)
        versions = self.storage.list_roadmaps(selected_role)
        latest = latest_roadmap(versions)
        if blockers:
            state_key, state_label = "blocked", "Inputs incomplete"
            summary = "Complete the current Role inputs before generation."
        elif latest is None:
            state_key, state_label = "missing", "No Roadmap"
            summary = "Current inputs are ready for the first Roadmap."
        elif latest.input_fingerprint != fingerprint:
            state_key, state_label = "changed", "Inputs changed"
            summary = "Current facts differ from the latest Roadmap. Regeneration is recommended."
        else:
            state_key, state_label = "current", "Current"
            summary = "The latest Roadmap matches the current input facts."
        history = tuple(
            RoadmapHistoryItemView(
                str(item.roadmap_id),
                item.generated_at.isoformat(),
                item == latest,
                item.input_fingerprint == fingerprint,
            )
            for item in reversed(versions)
        )
        handoff_status = self.handoffs.status_for(
            "job-learning-roadmap",
            context={
                "role_id": role_id,
                "input_fingerprint": fingerprint,
            },
        )
        return RoadmapWorkspaceView(
            market.current_role,
            state_key,
            state_label,
            summary,
            fingerprint,
            not blockers,
            "Generate Roadmap" if latest is None else "Regenerate Roadmap",
            blockers,
            history,
            handoff_status.state if handoff_status else None,
            handoff_status.message if handoff_status else None,
            relevant_capability_count,
            selected_capability_count,
            knowledge_ready_count,
            knowledge_missing_count,
            MAX_ROADMAP_VERSIONS_PER_ROLE,
        )

    def _roadmap_for_role(self, role_id: str, roadmap_id: str) -> RoadmapVersion:
        selected_role = self._uuid(role_id, "role_id")
        target_id = self._uuid(roadmap_id, "roadmap_id")
        roadmap = next(
            (
                item
                for item in self.storage.list_roadmaps(selected_role)
                if item.roadmap_id == target_id
            ),
            None,
        )
        if roadmap is None:
            raise ApplicationError(
                "validation", "load Roadmap history", "Roadmap version 不存在"
            )
        return roadmap

    def detail(self, role_id: str, roadmap_id: str) -> RoadmapDetailView:
        market = self.market.view(role_id)
        if market.current_role is None:
            raise ApplicationError("validation", "load Roadmap", "Role 不存在")
        roadmap = self._roadmap_for_role(role_id, roadmap_id)
        versions = self.storage.list_roadmaps(self._uuid(role_id, "role_id"))
        latest = latest_roadmap(versions)
        fingerprint = str(self.generation_input(role_id)["input_fingerprint"])
        return RoadmapDetailView(
            current_role=market.current_role,
            roadmap_id=str(roadmap.roadmap_id),
            generated_at=roadmap.generated_at.isoformat(),
            latest=roadmap == latest,
            matches_current_inputs=roadmap.input_fingerprint == fingerprint,
            html=roadmap_markdown_html(roadmap.content),
        )

    @staticmethod
    def _export_filename(role_name: str, generated_at: datetime) -> str:
        safe_role = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", role_name)
        safe_role = "_".join(safe_role.split()).strip(" ._") or "role"
        return f"{safe_role[:80]}_roadmap_{generated_at.strftime('%Y%m%d_%H%M%S')}.md"

    def export_markdown(self, role_id: str, roadmap_id: str) -> tuple[str, bytes]:
        market = self.market.view(role_id)
        if market.current_role is None:
            raise ApplicationError("validation", "export Roadmap", "Role 不存在")
        roadmap = self._roadmap_for_role(role_id, roadmap_id)
        return (
            self._export_filename(market.current_role.name, roadmap.generated_at),
            roadmap.content.encode("utf-8"),
        )

    def delete(self, role_id: str, roadmap_id: str) -> str:
        selected_role = self._uuid(role_id, "role_id")
        roadmap = self._roadmap_for_role(role_id, roadmap_id)
        try:
            self.storage.delete_roadmap(selected_role, roadmap.roadmap_id)
        except (ValueError, OSError) as exc:
            raise ApplicationError(
                "validation", "delete Roadmap", str(exc)
            ) from exc
        return "Roadmap version 已删除"

    def prepare_generation(self, role_id: str) -> str:
        view = self.view(role_id)
        if not view.can_generate or view.current_input_fingerprint is None:
            raise ApplicationError(
                "validation",
                "prepare Roadmap",
                "请先完成页面列出的准备事项",
            )
        self.handoffs.prepare(
            "job-learning-roadmap",
            input_payload=self.generation_input(role_id),
            context={
                "role_id": role_id,
                "input_fingerprint": view.current_input_fingerprint,
            },
        )
        return prepared_handoff_message("job-learning-roadmap")

    def save_result(self, role_id: str, payload: str) -> str:
        selected_role = self._uuid(role_id, "role_id")
        try:
            view = self.view(role_id)
            if not view.can_generate:
                raise ValueError("当前 Role inputs 尚未满足 Roadmap generation 条件")
            result = RoadmapGenerationResult.model_validate_json(payload)
            if result.schema_version != "1.0":
                raise ValueError("Roadmap result schema_version 不受支持")
            if result.input_fingerprint != view.current_input_fingerprint:
                raise ValueError("Roadmap result input_fingerprint 已过期")
            versions = self.storage.list_roadmaps(selected_role)
            latest = latest_roadmap(versions)
            if (
                latest is not None
                and latest.input_fingerprint == result.input_fingerprint
                and latest.content == result.content
            ):
                return "相同 Roadmap version 已存在"
            roadmap = RoadmapVersion(
                role_id=selected_role,
                generated_at=datetime.now().astimezone(),
                input_fingerprint=result.input_fingerprint,
                content=result.content,
            )
            self.storage.append_roadmap(roadmap)
            self.storage.enforce_roadmap_retention(
                selected_role,
                preserve_roadmap_id=roadmap.roadmap_id,
            )
            return "新 Roadmap version 已保存"
        except ApplicationError:
            raise
        except (ValueError, ValidationError) as exc:
            raise ApplicationError(
                "validation", "save Roadmap", str(exc)
            ) from exc
        except OSError as exc:
            raise ApplicationError(
                "system", "save Roadmap", "Roadmap未保存；已有版本保持不变"
            ) from exc
