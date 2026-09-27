from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from application.capabilities import CapabilityOperations
from application.learning import LearningOperations
from application.market import MarketOperations
from application.roadmaps import RoadmapOperations
from schemas.core import AtomicMarketSignal, JDAnalysesDocument, JDAnalysis
from src.core_storage import CoreStorage
from src.development_reset import (
    build_development_reset_manifest,
    execute_development_reset,
)
from src.market import jd_source_fingerprint
from tests.test_application_knowledge import _knowledge_payload
from tests.test_application_roadmaps import _result


def _analyze(market: MarketOperations, role_id: str, expression: str) -> None:
    role_uuid = market._uuid(role_id, "role_id")
    job = market.storage.load_jds(role_uuid).jobs[0]
    result = JDAnalysesDocument(
        role_id=role_uuid,
        analyses=[
            JDAnalysis(
                job_id=job.job_id,
                role_id=role_uuid,
                source_fingerprint=jd_source_fingerprint(job),
                signals=[
                    AtomicMarketSignal(
                        source_expression=expression,
                        atomic_expression=expression,
                        evidence=job.jd_text,
                    )
                ],
            )
        ],
    )
    market.import_analyses(
        role_id,
        result.model_dump_json(),
        expected_sha256=market.view(role_id).analyses_sha256 or "",
    )


def _create_role_with_jd(
    market: MarketOperations, name: str, expression: str
) -> str:
    role_id, _ = market.create_role(name, market.view().roles_sha256)
    market.add_job(
        role_id,
        title=f"{name} Engineer",
        company="Example",
        jd_text=f"需要掌握 {expression}",
        source_url=None,
        expected_sha256=market.view(role_id).jds_sha256 or "",
    )
    _analyze(market, role_id, expression)
    return role_id


def test_reset_first_use_ongoing_learning_and_cross_role_e2e(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    legacy = project_root / "governance" / "audit.jsonl"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy\n", encoding="utf-8")
    manifest = build_development_reset_manifest(
        project_root, generated_at=datetime.now().astimezone()
    )
    execute_development_reset(project_root, manifest)
    root = project_root / "state"
    assert CoreStorage(root).load_roles().roles == []

    market = MarketOperations(root)
    role_a = _create_role_with_jd(market, "AI Application", "Docker")
    role_b = _create_role_with_jd(market, "Java Backend", "Docker")

    capabilities = CapabilityOperations(root)
    candidate = capabilities.workspace(role_a).pending_candidates[0]
    capabilities.add(
        role_a,
        candidate.candidate_fingerprint,
        "Docker",
        expected_catalog_sha256=capabilities.workspace(role_a).catalog_sha256,
    )
    capability_id = capabilities.workspace(role_a).current_capabilities[0].capability_id
    assert capabilities.workspace(role_b).pending_candidates == ()
    assert capabilities.workspace(role_b).current_capabilities[0].capability_id == (
        capability_id
    )

    research_input = capabilities.knowledge_research_input(role_a, capability_id)
    capabilities.save_knowledge_result(
        role_a,
        capability_id,
        _knowledge_payload(research_input),
        expected_knowledge_sha256=None,
    )
    assert capabilities.detail(role_b, capability_id).knowledge.value is not None

    learning = LearningOperations(root)
    learning.set_level(
        role_a,
        capability_id,
        2,
        expected_sha256=learning.view(role_a).personal_states_sha256,
    )
    learning.add_practice(
        role_a,
        capability_id,
        "Completed a Docker Compose service",
        expected_sha256=learning.view(role_a).practices_sha256,
    )
    shared_b = learning.view(role_b).capabilities[0]
    assert shared_b.current_level == 2
    assert shared_b.practices[0].description == "Completed a Docker Compose service"

    roadmaps = RoadmapOperations(root)
    input_a = roadmaps.generation_input(role_a)
    input_b = roadmaps.generation_input(role_b)
    assert input_a["input_fingerprint"] != input_b["input_fingerprint"]
    roadmaps.save_result(
        role_a,
        _result(str(input_a["input_fingerprint"]), "# AI Roadmap\n\n- Docker"),
    )
    roadmaps.save_result(
        role_b,
        _result(str(input_b["input_fingerprint"]), "# Java Roadmap\n\n- Docker"),
    )
    assert len(roadmaps.view(role_a).history) == 1
    assert len(roadmaps.view(role_b).history) == 1
    assert "AI Roadmap" in roadmaps.detail(
        role_a, roadmaps.view(role_a).history[0].roadmap_id
    ).html
    assert "Java Roadmap" in roadmaps.detail(
        role_b, roadmaps.view(role_b).history[0].roadmap_id
    ).html

    practice = learning.view(role_a).capabilities[0].practices[0]
    learning.edit_practice(
        role_a,
        capability_id,
        practice.practice_id,
        "Completed Docker Compose with health checks",
        expected_sha256=learning.view(role_a).practices_sha256,
    )
    learning.set_level(
        role_a,
        capability_id,
        3,
        expected_sha256=learning.view(role_a).personal_states_sha256,
    )
    assert roadmaps.view(role_a).state_key == "changed"
    next_input = roadmaps.generation_input(role_a)
    roadmaps.save_result(
        role_a,
        json.dumps(
            {
                "schema_version": "1.0",
                "input_fingerprint": next_input["input_fingerprint"],
                "content": "# AI Roadmap Updated\n\n- Diagnose container failures",
            }
        ),
    )
    assert len(roadmaps.view(role_a).history) == 2
    assert len(roadmaps.view(role_b).history) == 1
