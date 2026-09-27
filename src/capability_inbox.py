from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from schemas.core import (
    Capability,
    CapabilityCatalogDocument,
    JD,
    JDAnalysis,
    SkippedCandidate,
)
from src.market import (
    AtomicSignalStatistic,
    SignalEvidence,
    build_atomic_market_statistics,
    normalize_atomic_expression,
)


@dataclass(frozen=True)
class CapabilityCandidate:
    candidate_fingerprint: str
    atomic_expression: str
    jd_count: int
    sample_size: int
    evidence: tuple[SignalEvidence, ...]


@dataclass(frozen=True)
class MappedCapability:
    capability: Capability
    atomic_expressions: tuple[str, ...]
    evidence: tuple[SignalEvidence, ...]


@dataclass(frozen=True)
class CapabilityDerivation:
    pending: tuple[CapabilityCandidate, ...]
    mapped: tuple[MappedCapability, ...]
    current_candidates: tuple[CapabilityCandidate, ...]


def candidate_fingerprint(role_id: UUID, statistic: AtomicSignalStatistic) -> str:
    payload = {
        "role_id": str(role_id),
        "atomic_expression": normalize_atomic_expression(statistic.atomic_expression),
        "evidence": sorted(
            (
                str(item.job_id),
                item.source_expression,
                item.evidence,
            )
            for item in statistic.evidence
        ),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def derive_capability_state(
    role_id: UUID,
    jobs: list[JD],
    analyses: list[JDAnalysis],
    catalog: CapabilityCatalogDocument,
    skipped: list[SkippedCandidate],
) -> CapabilityDerivation:
    capabilities = {item.capability_id: item for item in catalog.capabilities}
    mappings = {item.normalized_expression: item for item in catalog.source_mappings}
    skipped_keys = {item.candidate_fingerprint for item in skipped}
    statistics = build_atomic_market_statistics(jobs, analyses)
    current_candidates = tuple(
        CapabilityCandidate(
            candidate_fingerprint=candidate_fingerprint(role_id, statistic),
            atomic_expression=statistic.atomic_expression,
            jd_count=statistic.jd_count,
            sample_size=statistic.sample_size,
            evidence=statistic.evidence,
        )
        for statistic in statistics
    )
    pending: list[CapabilityCandidate] = []
    mapped_values: dict[UUID, dict[str, object]] = {}
    for candidate in current_candidates:
        if candidate.candidate_fingerprint in skipped_keys:
            continue
        mapping = mappings.get(normalize_atomic_expression(candidate.atomic_expression))
        if mapping is None:
            pending.append(candidate)
            continue
        capability = capabilities[mapping.capability_id]
        value = mapped_values.setdefault(
            capability.capability_id,
            {
                "capability": capability,
                "atomic_expressions": [],
                "evidence": [],
            },
        )
        expressions = value["atomic_expressions"]
        evidence = value["evidence"]
        assert isinstance(expressions, list) and isinstance(evidence, list)
        if candidate.atomic_expression not in expressions:
            expressions.append(candidate.atomic_expression)
        evidence.extend(candidate.evidence)
    mapped = tuple(
        MappedCapability(
            capability=value["capability"],
            atomic_expressions=tuple(value["atomic_expressions"]),
            evidence=tuple(value["evidence"]),
        )
        for value in mapped_values.values()
    )
    return CapabilityDerivation(
        pending=tuple(pending),
        mapped=tuple(
            sorted(
                mapped,
                key=lambda item: item.capability.name.casefold(),
            )
        ),
        current_candidates=current_candidates,
    )
