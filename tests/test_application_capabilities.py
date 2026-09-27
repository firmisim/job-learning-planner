from __future__ import annotations

import inspect
import json
from pathlib import Path
from uuid import uuid4

import pytest

from application.capabilities import CapabilityOperations
from application.errors import ApplicationError
from application.market import MarketOperations
from schemas.core import AtomicMarketSignal, JDAnalysesDocument, JDAnalysis
from src.market import jd_source_fingerprint


def _role_with_signals(
    market: MarketOperations,
    name: str,
    expressions: list[str],
) -> str:
    role_id, _ = market.create_role(name, market.view().roles_sha256)
    text = "；".join(expressions)
    market.add_job(
        role_id,
        title=f"{name} JD",
        company=None,
        jd_text=text,
        source_url=None,
        expected_sha256=market.view(role_id).jds_sha256 or "",
    )
    role_uuid = market._uuid(role_id, "role_id")
    job = market.storage.load_jds(role_uuid).jobs[0]
    analysis = JDAnalysesDocument(
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
                        evidence=expression,
                    )
                    for expression in expressions
                ],
            )
        ],
    )
    market.import_analyses(
        role_id,
        analysis.model_dump_json(),
        expected_sha256=market.view(role_id).analyses_sha256 or "",
    )
    return role_id


def test_candidate_derivation_mapping_reuse_and_role_specific_skip(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    market = MarketOperations(root)
    role_a = _role_with_signals(market, "Role A", ["Fast API", "Teamwork"])
    role_b = _role_with_signals(market, "Role B", ["Fast API", "Teamwork"])
    capabilities = CapabilityOperations(root)

    target = capabilities.storage.create_capability("FastAPI")
    candidate_a = next(
        item
        for item in capabilities.workspace(role_a).pending_candidates
        if item.atomic_expression == "Fast API"
    )
    capabilities.merge(
        role_a,
        candidate_a.candidate_fingerprint,
        str(target.capability_id),
        expected_catalog_sha256=capabilities.workspace(role_a).catalog_sha256,
    )
    assert [
        item.name for item in capabilities.workspace(role_a).current_capabilities
    ] == ["FastAPI"]
    assert [
        item.name for item in capabilities.workspace(role_b).current_capabilities
    ] == ["FastAPI"]
    assert all(
        item.atomic_expression != "Fast API"
        for item in capabilities.workspace(role_b).pending_candidates
    )

    teamwork_a = next(
        item
        for item in capabilities.workspace(role_a).pending_candidates
        if item.atomic_expression == "Teamwork"
    )
    capabilities.skip(
        role_a,
        teamwork_a.candidate_fingerprint,
        expected_skipped_sha256=capabilities.workspace(role_a).skipped_sha256 or "",
    )
    assert not capabilities.workspace(role_a).pending_candidates
    assert [
        item.atomic_expression
        for item in capabilities.workspace(role_b).pending_candidates
    ] == ["Teamwork"]
    assert not capabilities.workspace(role_b).skipped_candidates


def test_add_is_atomic_idempotent_and_duplicate_name_blocks_without_partial_write(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    market = MarketOperations(root)
    role_id = _role_with_signals(market, "AI", ["LLM API使用", "Generative API"])
    operations = CapabilityOperations(root)
    first = next(
        item
        for item in operations.workspace(role_id).pending_candidates
        if item.atomic_expression == "LLM API使用"
    )
    original_token = operations.workspace(role_id).catalog_sha256
    operations.add(
        role_id,
        first.candidate_fingerprint,
        "LLM API",
        expected_catalog_sha256=original_token,
    )
    catalog = operations.storage.load_catalog()
    assert len(catalog.capabilities) == 1
    assert len(catalog.source_mappings) == 1
    capability_id = catalog.capabilities[0].capability_id

    repeated = operations.add(
        role_id,
        first.candidate_fingerprint,
        "LLM API",
        expected_catalog_sha256=original_token,
    )
    assert "已存在" in repeated
    assert operations.storage.load_catalog() == catalog

    second = next(
        item
        for item in operations.workspace(role_id).pending_candidates
        if item.atomic_expression == "Generative API"
    )
    before = operations.storage.load_catalog_snapshot()
    with pytest.raises(ApplicationError, match="Merge"):
        operations.add(
            role_id,
            second.candidate_fingerprint,
            "LLM API",
            expected_catalog_sha256=before[1],
        )
    assert operations.storage.load_catalog_snapshot() == before

    operations.rename(
        role_id,
        str(capability_id),
        "LLM Application API",
        expected_catalog_sha256=before[1],
    )
    assert (
        operations.storage.load_catalog().capabilities[0].capability_id == capability_id
    )
    unrelated_role = _role_with_signals(market, "Unrelated", ["Java"])
    operations.rename(
        unrelated_role,
        str(capability_id),
        "Hidden rename",
        expected_catalog_sha256=operations.workspace(unrelated_role).catalog_sha256,
    )
    assert operations.detail(unrelated_role, str(capability_id)).in_current_role is False


def test_merge_validates_target_conflict_and_does_not_create_capability(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    market = MarketOperations(root)
    role_id = _role_with_signals(market, "Backend", ["FastAPI"])
    operations = CapabilityOperations(root)
    python = operations.storage.create_capability("Python Web Development")
    other = operations.storage.create_capability("Other")
    candidate = operations.workspace(role_id).pending_candidates[0]
    count = len(operations.storage.load_catalog().capabilities)

    with pytest.raises(ApplicationError, match="不存在"):
        operations.merge(
            role_id,
            candidate.candidate_fingerprint,
            str(uuid4()),
            expected_catalog_sha256=operations.workspace(role_id).catalog_sha256,
        )
    assert len(operations.storage.load_catalog().capabilities) == count

    token = operations.workspace(role_id).catalog_sha256
    operations.merge(
        role_id,
        candidate.candidate_fingerprint,
        str(python.capability_id),
        expected_catalog_sha256=token,
    )
    assert len(operations.storage.load_catalog().capabilities) == count
    operations.merge(
        role_id,
        candidate.candidate_fingerprint,
        str(python.capability_id),
        expected_catalog_sha256=token,
    )
    with pytest.raises(ApplicationError, match="不同 Capability"):
        operations.merge(
            role_id,
            candidate.candidate_fingerprint,
            str(other.capability_id),
            expected_catalog_sha256=operations.workspace(role_id).catalog_sha256,
        )


def test_skip_restore_reenters_pending_when_source_is_current(tmp_path: Path) -> None:
    root = tmp_path / "state"
    market = MarketOperations(root)
    role_id = _role_with_signals(market, "Backend", ["Observability"])
    operations = CapabilityOperations(root)
    candidate = operations.workspace(role_id).pending_candidates[0]
    token = operations.workspace(role_id).skipped_sha256 or ""
    operations.skip(
        role_id, candidate.candidate_fingerprint, expected_skipped_sha256=token
    )
    assert not operations.workspace(role_id).pending_candidates
    assert not operations.storage.load_catalog().capabilities
    assert not operations.storage.load_catalog().source_mappings

    operations.restore(
        role_id,
        candidate.candidate_fingerprint,
        expected_skipped_sha256=operations.workspace(role_id).skipped_sha256 or "",
    )
    assert (
        operations.workspace(role_id).pending_candidates[0].candidate_fingerprint
        == candidate.candidate_fingerprint
    )


def test_user_choice_is_not_constrained_by_codex_recommendation(tmp_path: Path) -> None:
    root = tmp_path / "state"
    market = MarketOperations(root)
    role_id = _role_with_signals(market, "AI", ["Prompt APIs", "Agent APIs"])
    operations = CapabilityOperations(root)
    target = operations.storage.create_capability("AI API Development")
    first = next(
        item
        for item in operations.workspace(role_id).pending_candidates
        if item.atomic_expression == "Prompt APIs"
    )
    recommendation_add = json.dumps(
        {
            "candidate_fingerprint": first.candidate_fingerprint,
            "explanation": "An API-oriented market signal.",
            "learning_value": "Useful for application integration.",
            "recommended_action": "add",
            "recommended_canonical_name": "Prompt API",
            "rationale": "It can be learned as a durable object.",
            "evidence_quotes": ["Prompt APIs"],
        }
    )
    assert (
        operations.parse_recommendation(
            role_id, first.candidate_fingerprint, recommendation_add
        ).recommended_action
        == "add"
    )
    operations.merge(
        role_id,
        first.candidate_fingerprint,
        str(target.capability_id),
        expected_catalog_sha256=operations.workspace(role_id).catalog_sha256,
    )
    operations.storage.add_source_mapping(
        "Agent APIs platform", target.capability_id
    )

    second = next(
        item
        for item in operations.workspace(role_id).pending_candidates
        if item.atomic_expression == "Agent APIs"
    )
    recommendation_merge = json.dumps(
        {
            "candidate_fingerprint": second.candidate_fingerprint,
            "explanation": "Another API signal.",
            "learning_value": "Useful for agent integration.",
            "recommended_action": "merge",
            "recommended_merge_target": "AI API Development",
            "rationale": "The existing object is related.",
            "evidence_quotes": ["Agent APIs"],
        }
    )
    assert (
        operations.parse_recommendation(
            role_id, second.candidate_fingerprint, recommendation_merge
        ).recommended_action
        == "merge"
    )
    operations.add(
        role_id,
        second.candidate_fingerprint,
        "Agent API Engineering",
        expected_catalog_sha256=operations.workspace(role_id).catalog_sha256,
    )
    assert {
        item.name for item in operations.workspace(role_id).current_capabilities
    } == {"AI API Development", "Agent API Engineering"}


def test_new_capability_flow_has_no_legacy_governance_dependency() -> None:
    import application.capabilities as application_module
    import schemas.core as schema_module
    import src.capability_inbox as core_module

    source = inspect.getsource(application_module) + inspect.getsource(core_module)
    prohibited = ("governance", "finalize", "impact", "revision", "audit", "taxonomy")
    assert not any(value in source.casefold() for value in prohibited)
    assert not hasattr(schema_module, "Alias")
    assert not hasattr(schema_module, "RecallResult")
    assert not hasattr(schema_module, "MergeCandidateState")


def test_capability_analysis_skill_is_advice_only() -> None:
    repository = Path(__file__).resolve().parents[1]
    skill = (
        repository / ".agents" / "skills" / "capability-analysis" / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "The recommendation is not a formal decision" in skill
    assert '"recommended_action": "add | merge | skip"' in skill
    assert "the user may choose any action" in skill.casefold()
    assert "an empty `merge_candidates` list is valid" in skill.casefold()
    assert "never invent an unlisted merge target" in skill.casefold()


def test_exact_source_mapping_reuses_capability_without_inbox_or_analysis(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    market = MarketOperations(root)
    role_id = _role_with_signals(market, "Known", ["FastAPI"])
    operations = CapabilityOperations(root)
    capability = operations.storage.create_capability("FastAPI")
    operations.storage.add_source_mapping("FastAPI", capability.capability_id)

    workspace = operations.workspace(role_id)

    assert workspace.pending_candidates == ()
    assert [item.capability_id for item in workspace.current_capabilities] == [
        str(capability.capability_id)
    ]
    assert not operations.handoffs.request_path("capability-analysis").exists()


def test_capability_analysis_input_uses_only_bounded_recall(tmp_path: Path) -> None:
    root = tmp_path / "state"
    market = MarketOperations(root)
    role_id = _role_with_signals(market, "Recall", ["Fast-API development"])
    operations = CapabilityOperations(root)
    target = operations.storage.create_capability("Web Backend Integration")
    operations.storage.add_source_mapping("Fast API", target.capability_id)
    for index in range(20):
        operations.storage.create_capability(f"Unrelated Capability {index:02d}")
    candidate = operations.workspace(role_id).pending_candidates[0]

    operations.prepare_recommendation(role_id, candidate.candidate_fingerprint)
    payload = operations.handoffs.load_request("capability-analysis")["input"]

    assert "existing_capabilities" not in payload
    assert len(payload["merge_candidates"]) <= 5
    assert payload["merge_candidates"][0]["name"] == "Web Backend Integration"
    assert payload["merge_candidates"][0]["historical_expressions"] == ["Fast API"]
    assert not any(
        item["name"].startswith("Unrelated")
        for item in payload["merge_candidates"]
    )


def test_confirmed_merge_becomes_recall_memory_for_later_expression(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    market = MarketOperations(root)
    first_role = _role_with_signals(market, "First", ["Fast API"])
    operations = CapabilityOperations(root)
    target = operations.storage.create_capability("Web Backend Integration")
    first_candidate = operations.workspace(first_role).pending_candidates[0]
    operations.merge(
        first_role,
        first_candidate.candidate_fingerprint,
        str(target.capability_id),
        expected_catalog_sha256=operations.workspace(first_role).catalog_sha256,
    )

    later_role = _role_with_signals(market, "Later", ["Fast-API development"])
    later_candidate = operations.workspace(later_role).pending_candidates[0]
    inbox = operations.inbox(later_role, later_candidate.candidate_fingerprint)

    assert [item.name for item in inbox.merge_candidates] == [
        "Web Backend Integration"
    ]
    assert inbox.merge_candidates[0].historical_expressions == ("Fast API",)


def test_empty_recall_is_valid_and_cannot_validate_invented_merge(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    market = MarketOperations(root)
    role_id = _role_with_signals(market, "Empty Recall", ["Quantum payroll law"])
    operations = CapabilityOperations(root)
    operations.storage.create_capability("Docker")
    candidate = operations.workspace(role_id).pending_candidates[0]

    operations.prepare_recommendation(role_id, candidate.candidate_fingerprint)
    payload = operations.handoffs.load_request("capability-analysis")["input"]
    assert payload["merge_candidates"] == []

    with pytest.raises(ApplicationError, match="recalled candidates"):
        operations.parse_recommendation(
            role_id,
            candidate.candidate_fingerprint,
            json.dumps(
                {
                    "candidate_fingerprint": candidate.candidate_fingerprint,
                    "explanation": "Unrelated signal.",
                    "learning_value": "Needs a user decision.",
                    "recommended_action": "merge",
                    "recommended_merge_target": "Docker",
                    "rationale": "Invented target.",
                    "evidence_quotes": ["Quantum payroll law"],
                }
            ),
        )


def test_jd_analysis_skill_keeps_semantic_atomic_expression_ownership() -> None:
    repository = Path(__file__).resolve().parents[1]
    skill = (repository / ".agents" / "skills" / "jd-analysis" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "minimum complete learning unit" in skill
    assert "Atomic does not mean the smallest noun" in skill
    assert "stable" in skill and "Knowledge-bearing" in skill
    assert "independently plannable" in skill and "professionally bounded" in skill
    assert "omit its signal rather than forcing an output" in skill
    assert "Python calculates Market frequency" in skill


def test_jd_analysis_skill_covers_representative_admission_fixtures() -> None:
    repository = Path(__file__).resolve().parents[1]
    skill = (repository / ".agents" / "skills" / "jd-analysis" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    exclusions = (
        "3年以上项目经验",
        "有大型 SaaS 项目经历",
        "能够独立交付可上线 MVP",
        "团队合作",
        "责任心",
        "抗压能力",
    )
    consolidations = (
        "信度、效度、难度、区分度分析",
        "PDF / Word / Excel / LaTeX 文档解析",
        "设计 RBAC 多角色多级/多版本权限体系",
    )
    preserved = (
        "需求访谈",
        "跨部门需求澄清",
        "Python、Java或者C/C++",
        "Spring Boot 或 FastAPI",
        "医学影像 DICOM 去标识化",
        "Redis 缓存设计",
        "使用 LaTeX 构建复杂数学试卷模板",
    )

    for evidence in (*exclusions, *consolidations, *preserved):
        assert evidence in skill
    assert "not four noun-level signals" in skill
    assert "one multi-format document-parsing capability" in skill
    assert "one appropriate access-control or permission-model capability" in skill
    assert "remain separate" in skill
