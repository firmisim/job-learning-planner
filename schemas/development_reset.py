from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


ResetId = Annotated[str, StringConstraints(pattern=r"^reset-[0-9a-f]{16}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class ResetFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: Annotated[str, StringConstraints(min_length=1)]
    sha256: Sha256
    classification: Literal["LEGACY_BUSINESS_STATE", "NEW_CORE_STATE"]


class DevelopmentResetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    reset_id: ResetId
    generated_at: datetime
    delete: list[ResetFile] = Field(default_factory=list)

    @field_validator("generated_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at 必须包含时区")
        return value

    @model_validator(mode="after")
    def paths_are_unique(self) -> DevelopmentResetManifest:
        paths = [item.path for item in self.delete]
        if len(paths) != len(set(paths)):
            raise ValueError("Reset target 不能重复")
        return self
