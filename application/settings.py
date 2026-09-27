from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from application.errors import ApplicationError
from application.settings_models import SettingsView
from schemas.development_reset import DevelopmentResetManifest
from src.core_storage import CoreStorage
from src.development_reset import (
    build_development_reset_manifest,
    execute_development_reset,
)


class SettingsOperations:
    """Low-frequency diagnostics and explicit Development Reset boundary."""

    def __init__(self, storage_root: Path) -> None:
        self.storage_root = storage_root.resolve()
        self.project_root = self.storage_root.parent
        self.state_directory = self.storage_root.name
        self.storage = CoreStorage(self.storage_root)
        self.storage.initialize()

    def view(
        self, manifest: DevelopmentResetManifest | None = None
    ) -> SettingsView:
        roles = self.storage.load_roles().roles
        roadmap_count = sum(
            len(self.storage.list_roadmaps(role.role_id)) for role in roles
        )
        return SettingsView(
            len(roles),
            len(self.storage.load_catalog().capabilities),
            len(list(self.storage.knowledge_root.glob("*.json"))),
            roadmap_count,
            manifest.model_dump_json() if manifest is not None else None,
            manifest.reset_id if manifest is not None else None,
            (
                tuple((item.classification, item.path) for item in manifest.delete)
                if manifest is not None
                else ()
            ),
        )

    def preview_reset(self) -> SettingsView:
        manifest = build_development_reset_manifest(
            self.project_root,
            generated_at=datetime.now().astimezone(),
            state_directory=self.state_directory,
        )
        return self.view(manifest)

    def apply_reset(
        self,
        manifest_json: str,
        *,
        confirmation: str,
        risk_confirmation: str,
    ) -> int:
        try:
            manifest = DevelopmentResetManifest.model_validate_json(manifest_json)
            if confirmation != manifest.reset_id:
                raise ValueError("请输入 preview中的完整 Reset ID")
            if risk_confirmation != "FULL DEVELOPMENT RESET":
                raise ValueError("请输入 FULL DEVELOPMENT RESET 确认")
            deleted = execute_development_reset(
                self.project_root,
                manifest,
                state_directory=self.state_directory,
            )
            return len(deleted)
        except (ValueError, ValidationError) as exc:
            raise ApplicationError(
                "validation", "apply Full Development Reset", str(exc)
            ) from exc

