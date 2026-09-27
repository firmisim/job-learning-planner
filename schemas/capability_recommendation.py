from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.core import NonEmptyText, Sha256


class CapabilityRecommendation(BaseModel):
    """Run-scoped semantic advice; never a persisted user decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_fingerprint: Sha256
    explanation: NonEmptyText
    learning_value: NonEmptyText
    recommended_action: Literal["add", "merge", "skip"]
    recommended_canonical_name: NonEmptyText | None = None
    recommended_merge_target: NonEmptyText | None = None
    rationale: NonEmptyText
    evidence_quotes: list[NonEmptyText] = Field(min_length=1)

    @model_validator(mode="after")
    def action_fields_match(self) -> CapabilityRecommendation:
        if self.recommended_action == "add" and not self.recommended_canonical_name:
            raise ValueError("Add recommendation 需要 canonical name")
        if self.recommended_action == "merge" and not self.recommended_merge_target:
            raise ValueError("Merge recommendation 需要 target name")
        return self
