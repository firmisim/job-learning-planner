from __future__ import annotations

import hashlib
import html
import json
import re
from typing import Any
from uuid import UUID

from schemas.core import RoadmapVersion
from src.capability_inbox import MappedCapability, derive_capability_state
from src.core_storage import CoreStorage
from src.knowledge import derive_knowledge_state
from src.level_criteria import applicable_level_criteria
from src.market import analysis_is_current, build_atomic_market_statistics


def _fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def apply_roadmap_scope(
    storage: CoreStorage,
    role_id: UUID,
    mapped: tuple[MappedCapability, ...],
) -> tuple[MappedCapability, ...]:
    """Return the mapped working set selected for this Role's Roadmap."""

    scope, _ = storage.load_roadmap_scope_snapshot(role_id)
    excluded = set(scope.excluded_capability_ids)
    return tuple(
        item for item in mapped if item.capability.capability_id not in excluded
    )


def build_roadmap_generation_input(
    storage: CoreStorage, role_id: UUID
) -> dict[str, Any]:
    role = next(
        (item for item in storage.load_roles().roles if item.role_id == role_id), None
    )
    if role is None:
        raise ValueError("Role 不存在")
    jobs = storage.load_jds(role_id).jobs
    analyses = storage.load_jd_analyses(role_id).analyses
    analysis_by_job = {item.job_id: item for item in analyses}
    current_analyses = [
        analysis_by_job[job.job_id]
        for job in jobs
        if analysis_is_current(job, analysis_by_job.get(job.job_id))
    ]
    statistics = build_atomic_market_statistics(jobs, current_analyses)
    catalog = storage.load_catalog()
    skipped = storage.load_skipped_candidates(role_id).candidates
    derivation = derive_capability_state(
        role_id, jobs, current_analyses, catalog, skipped
    )
    selected_capabilities = apply_roadmap_scope(
        storage, role_id, derivation.mapped
    )
    selected_ids = {
        item.capability.capability_id for item in selected_capabilities
    }
    levels = {
        item.capability_id: item.current_level
        for item in storage.load_personal_states().states
        if item.capability_id in selected_ids
    }
    practices: dict[UUID, list[dict[str, str]]] = {}
    for item in storage.load_practices().practices:
        if item.capability_id not in selected_ids:
            continue
        practices.setdefault(item.capability_id, []).append(
            {
                "practice_id": str(item.practice_id),
                "description": item.description,
            }
        )

    capabilities: list[dict[str, Any]] = []
    for mapped in selected_capabilities:
        knowledge, _ = storage.load_knowledge_snapshot(
            mapped.capability.capability_id
        )
        knowledge_state = derive_knowledge_state(mapped.capability, knowledge)
        criteria_source, level_criteria = applicable_level_criteria(
            knowledge if knowledge_state.key == "available" else None
        )
        capabilities.append(
            {
                "capability_id": str(mapped.capability.capability_id),
                "name": mapped.capability.name,
                "market": {
                    "atomic_expressions": list(mapped.atomic_expressions),
                    "jd_count": len({item.job_id for item in mapped.evidence}),
                    "sample_size": len(current_analyses),
                    "evidence": [
                        {
                            "job_id": str(item.job_id),
                            "job_title": item.job_title,
                            "source_expression": item.source_expression,
                            "evidence": item.evidence,
                        }
                        for item in mapped.evidence
                    ],
                },
                "knowledge_status": knowledge_state.key,
                "guidance_mode": (
                    "knowledge-ready"
                    if knowledge_state.key == "available"
                    else "research-needed"
                ),
                "knowledge": (
                    knowledge.model_dump(mode="json")
                    if knowledge_state.key == "available" and knowledge is not None
                    else None
                ),
                "current_level": levels.get(mapped.capability.capability_id),
                "level_criteria": {
                    "source": criteria_source,
                    "levels": [
                        {"level": level, "criterion": criterion}
                        for level, criterion in enumerate(level_criteria)
                    ],
                },
                "practices": practices.get(mapped.capability.capability_id, []),
            }
        )

    facts: dict[str, Any] = {
        "schema_version": "1.0",
        "role": {"role_id": str(role.role_id), "name": role.name},
        "market": {
            "jd_count": len(jobs),
            "analyzed_jd_count": len(current_analyses),
            "atomic_signals": [
                {
                    "atomic_expression": item.atomic_expression,
                    "jd_count": item.jd_count,
                    "sample_size": item.sample_size,
                    "evidence": [
                        {
                            "job_id": str(evidence.job_id),
                            "job_title": evidence.job_title,
                            "source_expression": evidence.source_expression,
                            "evidence": evidence.evidence,
                        }
                        for evidence in item.evidence
                    ],
                }
                for item in statistics
            ],
        },
        "capabilities": capabilities,
    }
    return {**facts, "input_fingerprint": _fingerprint(facts)}


def roadmap_markdown_html(value: str) -> str:
    """Render a deliberately small escaped Markdown subset for local reading."""

    rendered: list[str] = []
    in_list = False
    for raw in value.splitlines():
        line = html.escape(raw.strip())
        if not line:
            if in_list:
                rendered.append("</ul>")
                in_list = False
            continue
        heading = re.match(r"^(#{1,4})\s+(.+)$", line)
        bullet = re.match(r"^[-*]\s+(.+)$", line)
        if heading:
            if in_list:
                rendered.append("</ul>")
                in_list = False
            rendered.append(
                f"<h{len(heading.group(1)) + 1}>{heading.group(2)}</h{len(heading.group(1)) + 1}>"
            )
        elif bullet:
            if not in_list:
                rendered.append("<ul>")
                in_list = True
            rendered.append(f"<li>{bullet.group(1)}</li>")
        else:
            if in_list:
                rendered.append("</ul>")
                in_list = False
            rendered.append(f"<p>{line}</p>")
    if in_list:
        rendered.append("</ul>")
    return "\n".join(rendered)


def latest_roadmap(versions: list[RoadmapVersion]) -> RoadmapVersion | None:
    return versions[-1] if versions else None
