from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from schemas.core import Capability, CapabilityKnowledge


@dataclass(frozen=True)
class KnowledgeState:
    key: str
    label: str
    summary: str


def knowledge_input_fingerprint(capability: Capability) -> str:
    payload = {
        "capability_id": str(capability.capability_id),
        "canonical_name": capability.name,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def derive_knowledge_state(
    capability: Capability,
    knowledge: CapabilityKnowledge | None,
) -> KnowledgeState:
    if knowledge is None:
        return KnowledgeState(
            "missing",
            "Not researched",
            "No reusable Knowledge has been saved for this Capability.",
        )
    if knowledge.input_fingerprint != knowledge_input_fingerprint(capability):
        return KnowledgeState(
            "refresh-suggested",
            "Refresh suggested",
            "The canonical Capability input changed after this Knowledge was generated.",
        )
    return KnowledgeState(
        "available",
        "Available",
        "Reusable Knowledge is available for this Capability.",
    )
