from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from schemas.core import NonEmptyText, Sha256


class RoadmapGenerationResult(BaseModel):
    """Run-scoped Codex output; Python owns version identity and timestamps."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    input_fingerprint: Sha256
    content: NonEmptyText
