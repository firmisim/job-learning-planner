from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from application.capability_models import (
    CapabilityAnalysisBatchFailureView,
    CapabilityAnalysisBatchView,
    CapabilityDetailView,
    CapabilityInboxView,
    CapabilityListItemView,
    CapabilityWorkspaceView,
    InboxCandidateView,
    KnowledgeBatchFailureView,
    KnowledgeBatchView,
    KnowledgeView,
    MergeTargetView,
    RecommendationView,
    SkippedCandidateView,
    SourceMappingDetailView,
)
from application.errors import ApplicationError
from application.market_models import AtomicEvidenceView, SimpleRoleView
from schemas.capability_recommendation import CapabilityRecommendation
from schemas.core import (
    Capability,
    CapabilityCatalogDocument,
    CapabilityKnowledge,
    SkippedCandidate,
    normalize_source_expression,
)
from src.capability_inbox import (
    CapabilityCandidate,
    CapabilityDerivation,
    derive_capability_state,
)
from src.capability_analysis_batch import (
    CAPABILITY_ANALYSIS_BATCH_SIZE,
    CapabilityAnalysisBatchStore,
)
from src.capability_recall import recall_merge_candidates, search_capabilities
from src.core_storage import CoreStorage
from src.knowledge import derive_knowledge_state, knowledge_input_fingerprint
from src.knowledge_batch import KNOWLEDGE_BATCH_SIZE, KnowledgeBatchStore
from src.market import normalize_atomic_expression
from src.semantic_handoff import SemanticHandoffStore, prepared_handoff_message
from src.state_safety import StaleStateError


class CapabilityOperations:
    """Application boundary for derived Inbox and direct user choices."""

    def __init__(self, storage_root: Path) -> None:
        self.storage = CoreStorage(storage_root)
        self.storage.initialize()
        self.handoffs = SemanticHandoffStore(storage_root)
        self.analysis_batches = CapabilityAnalysisBatchStore(storage_root)
        self.knowledge_batches = KnowledgeBatchStore(storage_root)

    @staticmethod
    def _uuid(value: str, label: str) -> UUID:
        try:
            return UUID(value)
        except (ValueError, TypeError) as exc:
            raise ApplicationError(
                "validation", "validate capability input", f"{label} 无效"
            ) from exc

    def _role(self, role_id: str) -> tuple[UUID, SimpleRoleView]:
        selected = self._uuid(role_id, "role_id")
        role = next(
            (
                item
                for item in self.storage.load_roles().roles
                if item.role_id == selected
            ),
            None,
        )
        if role is None:
            raise ApplicationError("validation", "load Capabilities", "Role 不存在")
        return selected, SimpleRoleView(str(role.role_id), role.name, True)

    def _derive(
        self, role_id: UUID
    ) -> tuple[CapabilityDerivation, CapabilityCatalogDocument, str, str]:
        jobs = self.storage.load_jds(role_id).jobs
        analyses = self.storage.load_jd_analyses(role_id).analyses
        catalog, catalog_sha256 = self.storage.load_catalog_snapshot()
        skipped, skipped_sha256 = self.storage.load_skipped_candidates_snapshot(role_id)
        return (
            derive_capability_state(
                role_id,
                jobs,
                analyses,
                catalog,
                skipped.candidates,
            ),
            catalog,
            catalog_sha256,
            skipped_sha256,
        )

    @staticmethod
    def _evidence(candidate: CapabilityCandidate) -> tuple[AtomicEvidenceView, ...]:
        return tuple(
            AtomicEvidenceView(
                str(item.job_id),
                item.job_title,
                item.source_expression,
                item.evidence,
            )
            for item in candidate.evidence
        )

    @classmethod
    def _candidate_view(
        cls, candidate: CapabilityCandidate, *, recommendation_available: bool = False
    ) -> InboxCandidateView:
        return InboxCandidateView(
            candidate.candidate_fingerprint,
            candidate.atomic_expression,
            candidate.jd_count,
            candidate.sample_size,
            cls._evidence(candidate),
            recommendation_available,
        )

    def _knowledge_view(self, capability: Capability, role_id: UUID) -> KnowledgeView:
        knowledge, expected_sha256 = self.storage.load_knowledge_snapshot(
            capability.capability_id
        )
        state = derive_knowledge_state(capability, knowledge)
        context = {
            "role_id": str(role_id),
            "capability_id": str(capability.capability_id),
            "input_fingerprint": knowledge_input_fingerprint(capability),
            "expected_knowledge_sha256": expected_sha256,
        }
        handoff_status = self.handoffs.status_for(
            "capability-knowledge-research", context=context
        )
        return KnowledgeView(
            state.key,
            state.label,
            state.summary,
            knowledge,
            expected_sha256,
            handoff_status.state if handoff_status else None,
            handoff_status.message if handoff_status else None,
        )

    @staticmethod
    def _manifest_role_id(manifest: dict[str, object]) -> str | None:
        role = manifest.get("role")
        if not isinstance(role, dict):
            return None
        role_id = role.get("role_id")
        return role_id if isinstance(role_id, str) else None

    def _knowledge_batch_view(
        self, current_role_id: str
    ) -> KnowledgeBatchView | None:
        try:
            manifest, _ = self.knowledge_batches.load_snapshot()
        except ValueError:
            return None
        if manifest is None:
            return None
        if self._manifest_role_id(manifest) != current_role_id:
            return None
        role = manifest.get("role")
        selected = manifest.get("selected")
        batches = manifest.get("batches")
        failed_items = manifest.get("failed_items")
        if not (
            isinstance(role, dict)
            and isinstance(selected, list)
            and isinstance(batches, list)
            and isinstance(failed_items, dict)
        ):
            return None
        selected_items = [item for item in selected if isinstance(item, dict)]
        available: set[str] = set()
        names: dict[str, str] = {}
        for item in selected_items:
            capability_id = item.get("capability_id")
            name = item.get("canonical_name")
            if not isinstance(capability_id, str) or not isinstance(name, str):
                continue
            names[capability_id] = name
            try:
                knowledge, _ = self.storage.load_knowledge_snapshot(UUID(capability_id))
            except (OSError, ValueError):
                knowledge = None
            if knowledge is not None:
                available.add(capability_id)
        unresolved_failures = {
            capability_id: str(message)
            for capability_id, message in failed_items.items()
            if isinstance(capability_id, str) and capability_id not in available
        }
        total = len(names)
        succeeded = len(available)
        failed = len(unresolved_failures)
        remaining = max(0, total - succeeded - failed)
        next_index = manifest.get("next_batch_index", 0)
        batches_completed = next_index if isinstance(next_index, int) else 0
        state_key = "in-progress" if remaining else "attention" if failed else "complete"
        return KnowledgeBatchView(
            str(role.get("role_id", "")),
            str(role.get("name", "Unknown Role")),
            total,
            succeeded,
            failed,
            remaining,
            KNOWLEDGE_BATCH_SIZE,
            min(batches_completed, len(batches)),
            len(batches),
            state_key,
            tuple(
                KnowledgeBatchFailureView(
                    names.get(capability_id, "Unavailable Capability"), message
                )
                for capability_id, message in unresolved_failures.items()
            ),
        )

    def _recommendation_payloads(
        self, role_id: str, candidates: tuple[InboxCandidateView, ...]
    ) -> dict[str, dict[str, object]]:
        try:
            payloads: dict[str, dict[str, object]] = dict(
                self.analysis_batches.load_recommendations()
            )
        except ValueError:
            payloads = {}
        for candidate in candidates:
            context = {
                "role_id": role_id,
                "candidate_fingerprint": candidate.candidate_fingerprint,
            }
            try:
                output = self.handoffs.output_for(
                    "capability-analysis", context=context
                )
                if output is not None:
                    recommendation = CapabilityRecommendation.model_validate(output)
                    if (
                        recommendation.candidate_fingerprint
                        == candidate.candidate_fingerprint
                    ):
                        payloads[candidate.candidate_fingerprint] = (
                            recommendation.model_dump(mode="json")
                        )
            except (OSError, ValueError):
                continue
        return payloads

    def _analysis_batch_view(
        self,
        current_role_id: str,
        pending: tuple[InboxCandidateView, ...],
        recommendation_payloads: dict[str, dict[str, object]],
    ) -> CapabilityAnalysisBatchView | None:
        try:
            manifest, _ = self.analysis_batches.load_manifest()
        except ValueError:
            return None
        if manifest is None:
            return None
        if self._manifest_role_id(manifest) != current_role_id:
            return None
        role = manifest.get("role")
        selected = manifest.get("selected")
        batches = manifest.get("batches")
        failed_items = manifest.get("failed_items")
        if not (
            isinstance(role, dict)
            and isinstance(selected, list)
            and isinstance(batches, list)
            and isinstance(failed_items, dict)
        ):
            return None
        selected_items = [item for item in selected if isinstance(item, dict)]
        names = {
            str(item.get("candidate_fingerprint")): str(
                item.get("atomic_expression", "Unavailable Candidate")
            )
            for item in selected_items
            if isinstance(item.get("candidate_fingerprint"), str)
        }
        pending_ids = {item.candidate_fingerprint for item in pending}
        succeeded_ids = set(names) & set(recommendation_payloads)
        skipped_ids = set(manifest.get("skipped_candidate_fingerprints", []))
        skipped_ids.update(set(names) - pending_ids - succeeded_ids)
        unresolved_failures = {
            fingerprint: str(message)
            for fingerprint, message in failed_items.items()
            if (
                isinstance(fingerprint, str)
                and fingerprint in pending_ids
                and fingerprint not in succeeded_ids
            )
        }
        total = len(names)
        succeeded = len(succeeded_ids)
        skipped = len(skipped_ids & set(names))
        failed = len(unresolved_failures)
        remaining = max(0, total - succeeded - skipped - failed)
        next_index = manifest.get("next_batch_index", 0)
        batches_completed = next_index if isinstance(next_index, int) else 0
        state_key = "in-progress" if remaining else "attention" if failed else "complete"
        return CapabilityAnalysisBatchView(
            str(role.get("role_id", "")),
            str(role.get("name", "Unknown Role")),
            total,
            succeeded,
            failed,
            skipped,
            remaining,
            CAPABILITY_ANALYSIS_BATCH_SIZE,
            min(batches_completed, len(batches)),
            len(batches),
            state_key,
            tuple(
                CapabilityAnalysisBatchFailureView(
                    names.get(fingerprint, "Unavailable Candidate"), message
                )
                for fingerprint, message in unresolved_failures.items()
            ),
        )

    def workspace(self, role_id: str | None) -> CapabilityWorkspaceView:
        if role_id is None:
            catalog, catalog_sha256 = self.storage.load_catalog_snapshot()
            return CapabilityWorkspaceView(
                None,
                (),
                tuple(
                    CapabilityListItemView(str(item.capability_id), item.name, (), 0)
                    for item in sorted(
                        catalog.capabilities, key=lambda value: value.name.casefold()
                    )
                ),
                (),
                (),
                catalog_sha256,
                None,
            )
        selected, role = self._role(role_id)
        derivation, catalog, catalog_sha256, skipped_sha256 = self._derive(selected)
        mappings_by_capability: dict[UUID, list[str]] = {}
        for mapping in catalog.source_mappings:
            mappings_by_capability.setdefault(mapping.capability_id, []).append(
                mapping.source_expression
            )
        current = tuple(
            CapabilityListItemView(
                str(item.capability.capability_id),
                item.capability.name,
                item.atomic_expressions,
                len(item.evidence),
                self._knowledge_view(item.capability, selected).status_key,
            )
            for item in derivation.mapped
        )
        global_items = tuple(
            CapabilityListItemView(
                str(item.capability_id),
                item.name,
                tuple(
                    sorted(
                        mappings_by_capability.get(item.capability_id, []),
                        key=str.casefold,
                    )
                ),
                0,
            )
            for item in sorted(
                catalog.capabilities, key=lambda value: value.name.casefold()
            )
        )
        present = {item.candidate_fingerprint for item in derivation.current_candidates}
        skipped_document = self.storage.load_skipped_candidates(selected)
        pending_without_status = tuple(
            self._candidate_view(item) for item in derivation.pending
        )
        recommendation_payloads = self._recommendation_payloads(
            role_id, pending_without_status
        )
        pending = tuple(
            InboxCandidateView(
                item.candidate_fingerprint,
                item.atomic_expression,
                item.jd_count,
                item.sample_size,
                item.evidence,
                item.candidate_fingerprint in recommendation_payloads,
            )
            for item in pending_without_status
        )
        unanalyzed = tuple(
            item for item in pending if not item.recommendation_available
        )
        return CapabilityWorkspaceView(
            role,
            current,
            global_items,
            pending,
            tuple(
                SkippedCandidateView(
                    item.candidate_fingerprint,
                    item.atomic_expression,
                    item.candidate_fingerprint in present,
                )
                for item in skipped_document.candidates
            ),
            catalog_sha256,
            skipped_sha256,
            tuple(item for item in current if item.knowledge_status == "missing"),
            self._knowledge_batch_view(role_id),
            unanalyzed,
            self._analysis_batch_view(role_id, pending, recommendation_payloads),
        )

    def inbox(
        self,
        role_id: str,
        candidate_fingerprint: str | None = None,
        *,
        merge_query: str | None = None,
        recommendation: CapabilityRecommendation | None = None,
        error_message: str | None = None,
    ) -> CapabilityInboxView:
        workspace = self.workspace(role_id)
        candidates = workspace.pending_candidates
        if not candidates:
            raise ApplicationError(
                "validation",
                "open Capability Inbox",
                "当前 Role 没有 pending Candidate",
            )
        if candidate_fingerprint is None:
            candidate = candidates[0]
        else:
            candidate = next(
                (
                    item
                    for item in candidates
                    if item.candidate_fingerprint == candidate_fingerprint
                ),
                None,
            )
            if candidate is None:
                raise ApplicationError(
                    "conflict", "open Capability Inbox", "Candidate 已变化或已处理"
                )
        position = candidates.index(candidate) + 1
        catalog = self.storage.load_catalog()
        merge_candidates = tuple(
            MergeTargetView(
                str(item.capability_id),
                item.canonical_name,
                item.historical_expressions,
            )
            for item in recall_merge_candidates(candidate.atomic_expression, catalog)
        )
        recalled_ids = {item.capability_id for item in merge_candidates}
        normalized_merge_query = (merge_query or "").strip()
        merge_search_results = tuple(
            MergeTargetView(
                str(item.capability_id),
                item.canonical_name,
                item.historical_expressions,
            )
            for item in search_capabilities(normalized_merge_query, catalog)
            if str(item.capability_id) not in recalled_ids
        )
        context = {
            "role_id": role_id,
            "candidate_fingerprint": candidate.candidate_fingerprint,
        }
        if recommendation is None:
            try:
                output = self.analysis_batches.load_recommendations().get(
                    candidate.candidate_fingerprint
                )
                cached = output is not None
                if output is None:
                    output = self.handoffs.output_for(
                        "capability-analysis", context=context
                    )
                if output is not None:
                    recommendation = self._validate_recommendation_candidate(
                        candidate, json.dumps(output, ensure_ascii=False)
                    )
                    if not cached:
                        recommendation = self._validate_recommendation(
                            workspace,
                            candidate,
                            json.dumps(output, ensure_ascii=False),
                            merge_target_names={item.name for item in merge_candidates},
                        )
            except (ApplicationError, OSError, ValueError):
                recommendation = None
        recommendation_view = (
            self._recommendation_view(workspace, recommendation)
            if recommendation is not None
            else None
        )
        handoff_status = self.handoffs.status_for(
            "capability-analysis", context=context
        )
        return CapabilityInboxView(
            workspace,
            candidate,
            position,
            len(candidates),
            merge_candidates,
            normalized_merge_query,
            merge_search_results,
            recommendation_view,
            handoff_status.state if handoff_status else None,
            handoff_status.message if handoff_status else None,
            error_message,
        )

    @staticmethod
    def _recommendation_input_for_candidate(
        candidate: InboxCandidateView, catalog: CapabilityCatalogDocument
    ) -> dict[str, object]:
        recalled = recall_merge_candidates(candidate.atomic_expression, catalog)
        return {
            "schema_version": "1.0",
            "candidate": {
                "candidate_fingerprint": candidate.candidate_fingerprint,
                "atomic_expression": candidate.atomic_expression,
                "jd_count": candidate.jd_count,
                "sample_size": candidate.sample_size,
                "evidence": [item.__dict__ for item in candidate.evidence],
            },
            "merge_candidates": [
                {
                    "name": item.canonical_name,
                    "historical_expressions": list(item.historical_expressions),
                }
                for item in recalled
            ],
        }

    def _recommendation_input(
        self, view: CapabilityInboxView
    ) -> dict[str, object]:
        return self._recommendation_input_for_candidate(
            view.candidate, self.storage.load_catalog()
        )

    def prepare_recommendation(
        self, role_id: str, candidate_fingerprint: str
    ) -> str:
        view = self.inbox(role_id, candidate_fingerprint)
        self.handoffs.prepare(
            "capability-analysis",
            input_payload=self._recommendation_input(view),
            context={
                "role_id": role_id,
                "candidate_fingerprint": candidate_fingerprint,
            },
        )
        return prepared_handoff_message("capability-analysis")

    def parse_recommendation(
        self, role_id: str, candidate_fingerprint: str, payload: str
    ) -> CapabilityRecommendation:
        try:
            workspace = self.workspace(role_id)
            candidate = next(
                (
                    item
                    for item in workspace.pending_candidates
                    if item.candidate_fingerprint == candidate_fingerprint
                ),
                None,
            )
            if candidate is None:
                raise ValueError("Candidate 已变化或已处理")
            recalled = recall_merge_candidates(
                candidate.atomic_expression, self.storage.load_catalog()
            )
            return self._validate_recommendation(
                workspace,
                candidate,
                payload,
                merge_target_names={item.canonical_name for item in recalled},
            )
        except Exception as exc:
            raise self._mutation_error(
                "validate Capability recommendation", exc
            ) from exc

    @staticmethod
    def _validate_recommendation_candidate(
        candidate: InboxCandidateView, payload: str
    ) -> CapabilityRecommendation:
        recommendation = CapabilityRecommendation.model_validate_json(payload)
        if recommendation.candidate_fingerprint != candidate.candidate_fingerprint:
            raise ValueError("Recommendation 不属于当前 Candidate")
        evidence = {item.evidence for item in candidate.evidence}
        if any(
            not any(quote in item for item in evidence)
            for quote in recommendation.evidence_quotes
        ):
            raise ValueError("Recommendation evidence 必须来自当前 Candidate")
        return recommendation

    @staticmethod
    def _validate_recommendation(
        workspace: CapabilityWorkspaceView,
        candidate: InboxCandidateView,
        payload: str,
        merge_target_names: set[str] | None = None,
    ) -> CapabilityRecommendation:
        recommendation = CapabilityOperations._validate_recommendation_candidate(
            candidate, payload
        )
        allowed_merge_targets = (
            merge_target_names
            if merge_target_names is not None
            else {item.name for item in workspace.global_capabilities}
        )
        if (
            recommendation.recommended_action == "merge"
            and recommendation.recommended_merge_target
            and not any(
                normalize_source_expression(item)
                == normalize_source_expression(
                    recommendation.recommended_merge_target
                )
                for item in allowed_merge_targets
            )
        ):
            raise ValueError("Recommendation merge target 不在当前 recalled candidates 中")
        return recommendation

    def save_recommendation_result(
        self, role_id: str, candidate_fingerprint: str, payload: str
    ) -> CapabilityRecommendation:
        recommendation = self.parse_recommendation(
            role_id, candidate_fingerprint, payload
        )
        try:
            self.analysis_batches.save_recommendation(recommendation)
        except Exception as exc:
            raise self._mutation_error("save Capability recommendation", exc) from exc
        return recommendation

    @staticmethod
    def _recommendation_view(
        workspace: CapabilityWorkspaceView,
        recommendation: CapabilityRecommendation,
    ) -> RecommendationView:
        target = next(
            (
                item
                for item in workspace.global_capabilities
                if normalize_source_expression(item.name)
                == normalize_source_expression(
                    recommendation.recommended_merge_target or "__missing__"
                )
            ),
            None,
        )
        return RecommendationView(
            recommendation.explanation,
            recommendation.learning_value,
            recommendation.recommended_action,
            recommendation.recommended_canonical_name,
            recommendation.recommended_merge_target,
            target.capability_id if target else None,
            recommendation.rationale,
            tuple(recommendation.evidence_quotes),
        )

    def prepare_capability_analysis_batch(
        self, role_id: str, candidate_fingerprints: list[str] | None = None
    ) -> str:
        _, role = self._role(role_id)
        workspace = self.workspace(role_id)
        eligible = {
            item.candidate_fingerprint: item
            for item in workspace.unanalyzed_candidates
        }
        requested = (
            list(eligible)
            if candidate_fingerprints is None
            else list(dict.fromkeys(candidate_fingerprints))
        )
        if not requested:
            raise ApplicationError(
                "validation",
                "prepare Capability Analysis batch",
                "当前 Role 没有可准备的未分析 Candidate",
            )
        invalid = [item for item in requested if item not in eligible]
        if invalid:
            raise ApplicationError(
                "validation",
                "prepare Capability Analysis batch",
                "只能选择当前 Role 中仍待处理且尚无 Recommendation 的 Candidate",
            )
        selected = [
            {
                "candidate_fingerprint": fingerprint,
                "atomic_expression": eligible[fingerprint].atomic_expression,
            }
            for fingerprint in requested
        ]
        try:
            manifest = self.analysis_batches.prepare(
                role_id=role_id,
                role_name=role.name,
                candidates=selected,
            )
            self.prepare_next_capability_analysis_batch_request()
        except Exception as exc:
            raise self._mutation_error(
                "prepare Capability Analysis batch", exc
            ) from exc
        sizes = " / ".join(str(len(batch)) for batch in manifest["batches"])
        return (
            f"已准备 {len(selected)} 个 Candidate，共 {len(manifest['batches'])} 批"
            f"（{sizes}）。{prepared_handoff_message('capability-analysis', batch=True)}"
        )

    def retry_failed_capability_analysis_batch(self, current_role_id: str) -> str:
        try:
            manifest, _ = self.analysis_batches.load_manifest()
            if manifest is None or not isinstance(manifest.get("failed_items"), dict):
                raise ValueError("当前没有可重试的失败项")
            role = manifest.get("role")
            if not isinstance(role, dict) or not isinstance(role.get("role_id"), str):
                raise ValueError("Capability Analysis batch Role 无效")
            if role["role_id"] != current_role_id:
                raise ValueError("当前 Role 与 Capability Analysis batch 的准备 Role 不一致")
            batches = manifest.get("batches")
            next_index = manifest.get("next_batch_index")
            if not (
                isinstance(batches, list)
                and isinstance(next_index, int)
                and next_index == len(batches)
            ):
                raise ValueError("请先完成当前已准备的剩余批次")
            eligible = {
                item.candidate_fingerprint
                for item in self.workspace(role["role_id"]).unanalyzed_candidates
            }
            retry = [
                item for item in manifest["failed_items"] if item in eligible
            ]
            if not retry:
                raise ValueError("失败项已获得 Recommendation 或已处理，无需重试")
            return self.prepare_capability_analysis_batch(role["role_id"], retry)
        except Exception as exc:
            raise self._mutation_error(
                "retry Capability Analysis batch", exc
            ) from exc

    def prepare_next_capability_analysis_batch_request(self) -> str | None:
        while True:
            manifest, expected_sha256 = self.analysis_batches.load_manifest()
            if manifest is None:
                return None
            role = manifest.get("role")
            batches = manifest.get("batches")
            next_index = manifest.get("next_batch_index")
            selected = manifest.get("selected")
            if not (
                isinstance(role, dict)
                and isinstance(role.get("role_id"), str)
                and isinstance(batches, list)
                and isinstance(next_index, int)
                and 0 <= next_index <= len(batches)
                and isinstance(selected, list)
            ):
                raise ValueError("Capability Analysis batch manifest is invalid")
            if next_index == len(batches):
                return None
            batch = batches[next_index]
            if not isinstance(batch, list):
                raise ValueError("Capability Analysis batch manifest is invalid")
            selected_ids = {
                str(item.get("candidate_fingerprint"))
                for item in selected
                if isinstance(item, dict)
            }
            workspace = self.workspace(role["role_id"])
            current = {
                item.candidate_fingerprint: item
                for item in workspace.pending_candidates
            }
            recommendations = self._recommendation_payloads(
                role["role_id"], workspace.pending_candidates
            )
            completed = set(manifest.get("completed_candidate_fingerprints", []))
            skipped = set(manifest.get("skipped_candidate_fingerprints", []))
            failures = dict(manifest.get("failed_items", {}))
            catalog = self.storage.load_catalog()
            inputs: list[dict[str, object]] = []
            for fingerprint in batch:
                if not isinstance(fingerprint, str) or fingerprint not in selected_ids:
                    continue
                candidate = current.get(fingerprint)
                if candidate is None:
                    skipped.add(fingerprint)
                    failures.pop(fingerprint, None)
                    continue
                if fingerprint in recommendations:
                    completed.add(fingerprint)
                    failures.pop(fingerprint, None)
                    continue
                inputs.append(
                    self._recommendation_input_for_candidate(candidate, catalog)
                )
            manifest["completed_candidate_fingerprints"] = sorted(completed)
            manifest["skipped_candidate_fingerprints"] = sorted(skipped)
            manifest["failed_items"] = failures
            if not inputs:
                manifest["next_batch_index"] = next_index + 1
                self.analysis_batches.replace_manifest(
                    manifest, expected_sha256=expected_sha256
                )
                continue
            self.analysis_batches.replace_manifest(
                manifest, expected_sha256=expected_sha256
            )
            self.handoffs.prepare(
                "capability-analysis",
                input_payload={
                    "schema_version": "1.0",
                    "mode": "batch",
                    "batch_index": next_index,
                    "batch_count": len(batches),
                    "candidates": inputs,
                },
                context={
                    "role_id": role["role_id"],
                    "batch_manifest_id": str(manifest["manifest_id"]),
                    "batch_index": next_index,
                },
            )
            return (
                f"第 {next_index + 1} / {len(batches)} 批已准备。"
                f"{prepared_handoff_message('capability-analysis', batch=True)}"
            )

    def save_capability_analysis_batch_results(
        self,
        context: dict[str, object],
        input_payload: dict[str, object],
        output: dict[str, object],
    ) -> str:
        manifest, expected_sha256 = self.analysis_batches.load_manifest()
        if manifest is None:
            raise ApplicationError(
                "conflict", "save Capability Analysis batch", "Batch 已被替换"
            )
        next_index = manifest.get("next_batch_index")
        if (
            context.get("batch_manifest_id") != manifest.get("manifest_id")
            or context.get("role_id") != manifest.get("role", {}).get("role_id")
            or context.get("batch_index") != next_index
        ):
            raise ApplicationError(
                "conflict", "save Capability Analysis batch", "Batch 已变化，请重新运行"
            )
        inputs = input_payload.get("candidates")
        if not isinstance(inputs, list):
            raise ApplicationError(
                "validation", "save Capability Analysis batch", "Batch input 无效"
            )
        raw_results = output.get("results")
        results = raw_results if isinstance(raw_results, list) else []
        result_by_fingerprint: dict[str, dict[str, object]] = {}
        duplicates: set[str] = set()
        for result in results:
            if not isinstance(result, dict) or not isinstance(
                result.get("candidate_fingerprint"), str
            ):
                continue
            fingerprint = result["candidate_fingerprint"]
            if fingerprint in result_by_fingerprint:
                duplicates.add(fingerprint)
            result_by_fingerprint[fingerprint] = result
        workspace = self.workspace(str(context["role_id"]))
        current = {
            item.candidate_fingerprint: item for item in workspace.pending_candidates
        }
        completed = set(manifest.get("completed_candidate_fingerprints", []))
        skipped = set(manifest.get("skipped_candidate_fingerprints", []))
        failures = dict(manifest.get("failed_items", {}))
        success_count = 0
        failure_count = 0
        for item in inputs:
            if not isinstance(item, dict):
                continue
            candidate_payload = item.get("candidate")
            if not isinstance(candidate_payload, dict) or not isinstance(
                candidate_payload.get("candidate_fingerprint"), str
            ):
                continue
            fingerprint = candidate_payload["candidate_fingerprint"]
            candidate = current.get(fingerprint)
            if candidate is None:
                skipped.add(fingerprint)
                failures.pop(fingerprint, None)
                continue
            try:
                existing = self.analysis_batches.load_recommendations()
                if fingerprint in existing:
                    completed.add(fingerprint)
                    failures.pop(fingerprint, None)
                    success_count += 1
                    continue
                result = result_by_fingerprint.get(fingerprint)
                if result is None or fingerprint in duplicates:
                    raise ValueError("未返回唯一的 Candidate Recommendation")
                merge_candidates = item.get("merge_candidates")
                if not isinstance(merge_candidates, list):
                    raise ValueError("Candidate merge candidates 无效")
                allowed_targets = {
                    str(target.get("name"))
                    for target in merge_candidates
                    if isinstance(target, dict) and isinstance(target.get("name"), str)
                }
                recommendation = self._validate_recommendation(
                    workspace,
                    candidate,
                    json.dumps(result, ensure_ascii=False),
                    merge_target_names=allowed_targets,
                )
                self.analysis_batches.save_recommendation(recommendation)
                completed.add(fingerprint)
                failures.pop(fingerprint, None)
                success_count += 1
            except Exception as exc:
                error = self._mutation_error(
                    "save Capability recommendation", exc
                )
                failures[fingerprint] = (
                    "Candidate 已变化或已处理。"
                    if error.category == "conflict"
                    else "Recommendation 未通过现有 Candidate 校验。"
                )
                failure_count += 1
        manifest["completed_candidate_fingerprints"] = sorted(completed)
        manifest["skipped_candidate_fingerprints"] = sorted(skipped)
        manifest["failed_items"] = failures
        manifest["next_batch_index"] = int(next_index) + 1
        self.analysis_batches.replace_manifest(
            manifest, expected_sha256=expected_sha256
        )
        return f"本批 {success_count} 项 Recommendation 成功，{failure_count} 项失败"

    def _current_candidate(
        self, role_id: UUID, candidate_fingerprint: str
    ) -> tuple[CapabilityCandidate, CapabilityDerivation]:
        derivation, _, _, _ = self._derive(role_id)
        candidate = next(
            (
                item
                for item in derivation.current_candidates
                if item.candidate_fingerprint == candidate_fingerprint
            ),
            None,
        )
        if candidate is None:
            raise ValueError("Candidate source 已变化或不存在")
        return candidate, derivation

    def add(
        self,
        role_id: str,
        candidate_fingerprint: str,
        canonical_name: str,
        *,
        expected_catalog_sha256: str,
    ) -> str:
        selected, _ = self._role(role_id)
        try:
            candidate, _ = self._current_candidate(selected, candidate_fingerprint)
            skipped = {
                item.candidate_fingerprint
                for item in self.storage.load_skipped_candidates(selected).candidates
            }
            if candidate_fingerprint in skipped:
                raise ValueError("Candidate 已 Skip，请先 Restore")
            capability, _, created = self.storage.create_capability_with_mapping(
                canonical_name,
                candidate.atomic_expression,
                expected_sha256=expected_catalog_sha256,
            )
            return (
                f"已创建 Capability “{capability.name}” 并建立 mapping"
                if created
                else f"Capability “{capability.name}” 的 mapping 已存在"
            )
        except Exception as exc:
            raise self._mutation_error("Add Capability", exc) from exc

    def merge(
        self,
        role_id: str,
        candidate_fingerprint: str,
        capability_id: str,
        *,
        expected_catalog_sha256: str,
    ) -> str:
        selected, _ = self._role(role_id)
        target_id = self._uuid(capability_id, "Capability target")
        try:
            candidate, _ = self._current_candidate(selected, candidate_fingerprint)
            if candidate_fingerprint in {
                item.candidate_fingerprint
                for item in self.storage.load_skipped_candidates(selected).candidates
            }:
                raise ValueError("Candidate 已 Skip，请先 Restore")
            mapping = self.storage.add_source_mapping(
                candidate.atomic_expression,
                target_id,
                expected_sha256=expected_catalog_sha256,
            )
            target = next(
                item
                for item in self.storage.load_catalog().capabilities
                if item.capability_id == mapping.capability_id
            )
            return f"已将 “{candidate.atomic_expression}” Merge 到 “{target.name}”"
        except Exception as exc:
            raise self._mutation_error("Merge Capability", exc) from exc

    def merge_by_name(
        self,
        role_id: str,
        candidate_fingerprint: str,
        capability_name: str,
        *,
        expected_catalog_sha256: str,
    ) -> str:
        normalized = normalize_source_expression(capability_name)
        target = next(
            (
                item
                for item in self.storage.load_catalog().capabilities
                if normalize_source_expression(item.name) == normalized
            ),
            None,
        )
        if target is None:
            raise ApplicationError(
                "validation", "Merge Capability", "请选择现有 Capability"
            )
        return self.merge(
            role_id,
            candidate_fingerprint,
            str(target.capability_id),
            expected_catalog_sha256=expected_catalog_sha256,
        )

    def skip(
        self,
        role_id: str,
        candidate_fingerprint: str,
        *,
        expected_skipped_sha256: str,
    ) -> str:
        selected, _ = self._role(role_id)
        try:
            candidate, _ = self._current_candidate(selected, candidate_fingerprint)
            mapping_keys = {
                item.normalized_expression
                for item in self.storage.load_catalog().source_mappings
            }
            if normalize_atomic_expression(candidate.atomic_expression) in mapping_keys:
                raise ValueError("Candidate 已映射，不能 Skip")
            created = self.storage.skip_candidate(
                SkippedCandidate(
                    role_id=selected,
                    candidate_fingerprint=candidate.candidate_fingerprint,
                    atomic_expression=candidate.atomic_expression,
                ),
                expected_sha256=expected_skipped_sha256,
            )
            return (
                f"已在当前 Role Skip “{candidate.atomic_expression}”"
                if created
                else f"“{candidate.atomic_expression}” 已在当前 Role Skip"
            )
        except Exception as exc:
            raise self._mutation_error("Skip Candidate", exc) from exc

    def restore(
        self,
        role_id: str,
        candidate_fingerprint: str,
        *,
        expected_skipped_sha256: str,
    ) -> str:
        selected, _ = self._role(role_id)
        try:
            restored = self.storage.restore_skipped_candidate(
                selected,
                candidate_fingerprint,
                expected_sha256=expected_skipped_sha256,
            )
            return (
                "Skipped Candidate 已恢复" if restored else "Candidate 已处于恢复状态"
            )
        except Exception as exc:
            raise self._mutation_error("Restore Candidate", exc) from exc

    def rename(
        self,
        role_id: str,
        capability_id: str,
        name: str,
        *,
        expected_catalog_sha256: str,
    ) -> str:
        try:
            self.detail(role_id, capability_id)
            capability = self.storage.rename_capability(
                self._uuid(capability_id, "capability_id"),
                name,
                expected_sha256=expected_catalog_sha256,
            )
            return f"Capability 已重命名为 “{capability.name}”"
        except Exception as exc:
            raise self._mutation_error("Rename Capability", exc) from exc

    def _role_usage(
        self, capability_id: UUID, *, source_expression: str | None = None
    ) -> tuple[str, ...]:
        expected_expression = (
            normalize_source_expression(source_expression)
            if source_expression is not None
            else None
        )
        names: list[str] = []
        for role in self.storage.load_roles().roles:
            derivation, _, _, _ = self._derive(role.role_id)
            for mapped in derivation.mapped:
                if mapped.capability.capability_id != capability_id:
                    continue
                if expected_expression is not None and all(
                    normalize_source_expression(value) != expected_expression
                    for value in mapped.atomic_expressions
                ):
                    continue
                names.append(role.name)
                break
        return tuple(sorted(names, key=str.casefold))

    def detail(
        self,
        role_id: str,
        capability_id: str,
        *,
        reassign_expression: str | None = None,
        reassign_query: str | None = None,
    ) -> CapabilityDetailView:
        selected, role = self._role(role_id)
        target_id = self._uuid(capability_id, "capability_id")
        workspace = self.workspace(role_id)
        item = next(
            (
                value
                for value in workspace.global_capabilities
                if value.capability_id == capability_id
            ),
            None,
        )
        if item is None:
            raise ApplicationError(
                "validation",
                "open Capability detail",
                "Capability 不存在",
            )
        derivation, catalog, _, _ = self._derive(selected)
        mapping_values = tuple(
            mapping
            for mapping in catalog.source_mappings
            if mapping.capability_id == target_id
        )
        mappings = tuple(
            SourceMappingDetailView(
                mapping.source_expression,
                self._role_usage(
                    target_id, source_expression=mapping.source_expression
                ),
            )
            for mapping in mapping_values
        )
        mapped = next(
            (
                value
                for value in derivation.mapped
                if value.capability.capability_id == target_id
            ),
            None,
        )
        evidence = tuple(
            AtomicEvidenceView(
                str(value.job_id),
                value.job_title,
                value.source_expression,
                value.evidence,
            )
            for value in (mapped.evidence if mapped is not None else ())
        )
        capability = next(
            value for value in catalog.capabilities if value.capability_id == target_id
        )
        states, states_sha256 = self.storage.load_personal_states_snapshot()
        practices, practices_sha256 = self.storage.load_practices_snapshot()
        state = next(
            (value for value in states.states if value.capability_id == target_id), None
        )
        normalized_expression = (reassign_expression or "").strip()
        normalized_query = (reassign_query or "").strip()
        reassign_results = tuple(
            MergeTargetView(
                str(value.capability_id),
                value.canonical_name,
                value.historical_expressions,
            )
            for value in search_capabilities(normalized_query, catalog)
            if value.capability_id != target_id
        )
        return CapabilityDetailView(
            role,
            item,
            mappings,
            evidence,
            workspace.catalog_sha256,
            self._knowledge_view(capability, selected),
            mapped is not None,
            self._role_usage(target_id),
            state.current_level if state is not None else None,
            sum(1 for value in practices.practices if value.capability_id == target_id),
            states_sha256,
            practices_sha256,
            normalized_expression,
            normalized_query,
            reassign_results,
        )

    def unmap(
        self,
        role_id: str,
        capability_id: str,
        source_expression: str,
        *,
        expected_catalog_sha256: str,
    ) -> str:
        try:
            self._role(role_id)
            target_id = self._uuid(capability_id, "capability_id")
            mapping = self.storage.remove_source_mapping(
                source_expression,
                target_id,
                expected_sha256=expected_catalog_sha256,
            )
            return f"已取消 “{mapping.source_expression}” 的 Mapping"
        except Exception as exc:
            raise self._mutation_error("Unmap SourceMapping", exc) from exc

    def reassign(
        self,
        role_id: str,
        capability_id: str,
        source_expression: str,
        capability_name: str,
        *,
        expected_catalog_sha256: str,
    ) -> str:
        try:
            self._role(role_id)
            current_id = self._uuid(capability_id, "capability_id")
            normalized_name = normalize_source_expression(capability_name)
            catalog = self.storage.load_catalog()
            target = next(
                (
                    value
                    for value in catalog.capabilities
                    if normalize_source_expression(value.name) == normalized_name
                ),
                None,
            )
            if target is None:
                raise ValueError("请选择现有 Capability")
            mapping = self.storage.reassign_source_mapping(
                source_expression,
                current_id,
                target.capability_id,
                expected_sha256=expected_catalog_sha256,
            )
            return f"已将 “{mapping.source_expression}” Reassign 到 “{target.name}”"
        except Exception as exc:
            raise self._mutation_error("Reassign SourceMapping", exc) from exc

    def remove_knowledge(
        self,
        role_id: str,
        capability_id: str,
        *,
        expected_knowledge_sha256: str,
    ) -> str:
        try:
            self._role(role_id)
            target_id = self._uuid(capability_id, "capability_id")
            self.storage.remove_knowledge(
                target_id, expected_sha256=expected_knowledge_sha256
            )
            return "Capability Knowledge 已移除；Level 与 Practice 保持不变"
        except Exception as exc:
            raise self._mutation_error("Remove Capability Knowledge", exc) from exc

    def delete_capability(
        self,
        role_id: str,
        capability_id: str,
        *,
        expected_catalog_sha256: str,
        expected_personal_states_sha256: str,
        expected_practices_sha256: str,
        expected_knowledge_sha256: str | None,
    ) -> str:
        try:
            self._role(role_id)
            deleted = self.storage.delete_capability(
                self._uuid(capability_id, "capability_id"),
                expected_catalog_sha256=expected_catalog_sha256,
                expected_personal_states_sha256=expected_personal_states_sha256,
                expected_practices_sha256=expected_practices_sha256,
                expected_knowledge_sha256=expected_knowledge_sha256,
            )
            return f"Capability “{deleted.name}” 及其当前附属数据已删除"
        except Exception as exc:
            raise self._mutation_error("Delete Capability", exc) from exc

    def knowledge_research_input(
        self, role_id: str, capability_id: str
    ) -> dict[str, object]:
        detail = self.detail(role_id, capability_id)
        target_id = self._uuid(capability_id, "capability_id")
        capability = next(
            item
            for item in self.storage.load_catalog().capabilities
            if item.capability_id == target_id
        )
        return {
            "schema_version": "1.0",
            "mode": "refresh" if detail.knowledge.value is not None else "research",
            "capability": {
                "capability_id": capability_id,
                "canonical_name": capability.name,
                "input_fingerprint": knowledge_input_fingerprint(capability),
            },
            "existing_knowledge": (
                detail.knowledge.value.model_dump(mode="json")
                if detail.knowledge.value is not None
                else None
            ),
        }

    def prepare_knowledge_batch(
        self, role_id: str, capability_ids: list[str] | None = None
    ) -> str:
        _, role = self._role(role_id)
        workspace = self.workspace(role_id)
        missing = {
            item.capability_id: item
            for item in workspace.current_capabilities
            if item.knowledge_status == "missing"
        }
        requested = list(missing) if capability_ids is None else list(dict.fromkeys(capability_ids))
        if not requested:
            raise ApplicationError(
                "validation", "prepare Knowledge batch", "当前 Role 没有可准备的未研究 Capability"
            )
        invalid = [capability_id for capability_id in requested if capability_id not in missing]
        if invalid:
            raise ApplicationError(
                "validation",
                "prepare Knowledge batch",
                "只能选择当前 Role 中尚无 Knowledge 的 Capability",
            )
        selected = [
            {
                "capability_id": capability_id,
                "canonical_name": missing[capability_id].name,
                "input_fingerprint": knowledge_input_fingerprint(
                    next(
                        item
                        for item in self.storage.load_catalog().capabilities
                        if str(item.capability_id) == capability_id
                    )
                ),
            }
            for capability_id in requested
        ]
        try:
            manifest = self.knowledge_batches.prepare(
                role_id=role_id,
                role_name=role.name,
                capabilities=selected,
            )
            self.prepare_next_knowledge_batch_request()
        except Exception as exc:
            raise self._mutation_error("Prepare Knowledge batch", exc) from exc
        batch_count = len(manifest["batches"])
        sizes = " / ".join(str(len(batch)) for batch in manifest["batches"])
        return (
            f"已准备 {len(selected)} 个 Capability，共 {batch_count} 批"
            f"（{sizes}）。{prepared_handoff_message('capability-knowledge-research', batch=True)}"
        )

    def retry_failed_knowledge_batch(self, current_role_id: str) -> str:
        try:
            manifest, _ = self.knowledge_batches.load_snapshot()
            if manifest is None or not isinstance(manifest.get("failed_items"), dict):
                raise ValueError("当前没有可重试的失败项")
            role = manifest.get("role")
            if not isinstance(role, dict) or not isinstance(role.get("role_id"), str):
                raise ValueError("Knowledge batch Role 无效")
            if role["role_id"] != current_role_id:
                raise ValueError("当前 Role 与 Knowledge batch 的准备 Role 不一致")
            failed_ids = list(manifest["failed_items"])
            workspace = self.workspace(role["role_id"])
            missing_ids = {
                item.capability_id
                for item in workspace.current_capabilities
                if item.knowledge_status == "missing"
            }
            retry_ids = [item for item in failed_ids if item in missing_ids]
            if not retry_ids:
                raise ValueError("失败项已研究或已不属于原 Role，无需重试")
            return self.prepare_knowledge_batch(role["role_id"], retry_ids)
        except Exception as exc:
            raise self._mutation_error("Retry Knowledge batch", exc) from exc

    def prepare_next_knowledge_batch_request(self) -> str | None:
        while True:
            manifest, expected_sha256 = self.knowledge_batches.load_snapshot()
            if manifest is None:
                return None
            role = manifest.get("role")
            batches = manifest.get("batches")
            next_index = manifest.get("next_batch_index")
            if not (
                isinstance(role, dict)
                and isinstance(role.get("role_id"), str)
                and isinstance(batches, list)
                and isinstance(next_index, int)
                and 0 <= next_index <= len(batches)
            ):
                raise ValueError("Knowledge batch manifest is invalid")
            if next_index == len(batches):
                return None
            batch = batches[next_index]
            selected = manifest.get("selected")
            if not isinstance(batch, list) or not isinstance(selected, list):
                raise ValueError("Knowledge batch manifest is invalid")
            selected_by_id = {
                str(item.get("capability_id")): item
                for item in selected
                if isinstance(item, dict)
            }
            try:
                current = {
                    item.capability_id: item
                    for item in self.workspace(role["role_id"]).current_capabilities
                }
            except ApplicationError:
                current = {}
            completed = set(manifest.get("completed_capability_ids", []))
            failures = dict(manifest.get("failed_items", {}))
            inputs: list[dict[str, object]] = []
            for capability_id in batch:
                if not isinstance(capability_id, str):
                    continue
                item = current.get(capability_id)
                if item is None or capability_id not in selected_by_id:
                    failures[capability_id] = (
                        "Capability 已不属于准备该任务时的 Role working set。"
                    )
                    continue
                detail = self.detail(role["role_id"], capability_id)
                if detail.knowledge.value is not None:
                    completed.add(capability_id)
                    failures.pop(capability_id, None)
                    continue
                inputs.append(self.knowledge_research_input(role["role_id"], capability_id))
            manifest["completed_capability_ids"] = sorted(completed)
            manifest["failed_items"] = failures
            if not inputs:
                manifest["next_batch_index"] = next_index + 1
                self.knowledge_batches.replace(
                    manifest, expected_sha256=expected_sha256
                )
                continue
            self.knowledge_batches.replace(manifest, expected_sha256=expected_sha256)
            self.handoffs.prepare(
                "capability-knowledge-research",
                input_payload={
                    "schema_version": "1.0",
                    "mode": "batch",
                    "batch_index": next_index,
                    "batch_count": len(batches),
                    "capabilities": inputs,
                },
                context={
                    "role_id": role["role_id"],
                    "batch_manifest_id": str(manifest["manifest_id"]),
                    "batch_index": next_index,
                },
            )
            return (
                f"第 {next_index + 1} / {len(batches)} 批已准备。"
                f"{prepared_handoff_message('capability-knowledge-research', batch=True)}"
            )

    def save_knowledge_batch_results(
        self,
        context: dict[str, object],
        input_payload: dict[str, object],
        output: dict[str, object],
    ) -> str:
        manifest, expected_sha256 = self.knowledge_batches.load_snapshot()
        if manifest is None:
            raise ApplicationError("conflict", "save Knowledge batch", "Batch 已被替换")
        next_index = manifest.get("next_batch_index")
        if (
            context.get("batch_manifest_id") != manifest.get("manifest_id")
            or context.get("role_id") != manifest.get("role", {}).get("role_id")
            or context.get("batch_index") != next_index
        ):
            raise ApplicationError("conflict", "save Knowledge batch", "Batch 已变化，请重新运行")
        inputs = input_payload.get("capabilities")
        if not isinstance(inputs, list):
            raise ApplicationError("validation", "save Knowledge batch", "Batch input 无效")
        raw_results = output.get("results")
        results = raw_results if isinstance(raw_results, list) else []
        result_by_id: dict[str, dict[str, object]] = {}
        duplicates: set[str] = set()
        for result in results:
            if not isinstance(result, dict) or not isinstance(result.get("capability_id"), str):
                continue
            capability_id = result["capability_id"]
            if capability_id in result_by_id:
                duplicates.add(capability_id)
            result_by_id[capability_id] = result
        completed = set(manifest.get("completed_capability_ids", []))
        failures = dict(manifest.get("failed_items", {}))
        success_count = 0
        failure_count = 0
        role_id = str(context["role_id"])
        for item in inputs:
            if not isinstance(item, dict):
                continue
            capability = item.get("capability")
            if not isinstance(capability, dict) or not isinstance(
                capability.get("capability_id"), str
            ):
                continue
            capability_id = capability["capability_id"]
            try:
                detail = self.detail(role_id, capability_id)
                if detail.knowledge.value is not None:
                    completed.add(capability_id)
                    failures.pop(capability_id, None)
                    success_count += 1
                    continue
                result = result_by_id.get(capability_id)
                if result is None or capability_id in duplicates:
                    raise ValueError("未返回唯一的 Capability Knowledge 结果")
                self.save_knowledge_result(
                    role_id,
                    capability_id,
                    json.dumps(result, ensure_ascii=False),
                    expected_knowledge_sha256=None,
                )
                completed.add(capability_id)
                failures.pop(capability_id, None)
                success_count += 1
            except Exception as exc:
                error = self._mutation_error("Save Capability Knowledge", exc)
                failures[capability_id] = (
                    "Capability 已变化，请重新准备。"
                    if error.category == "conflict"
                    else "研究结果未通过现有 Knowledge 校验。"
                )
                failure_count += 1
        manifest["completed_capability_ids"] = sorted(completed)
        manifest["failed_items"] = failures
        manifest["next_batch_index"] = int(next_index) + 1
        self.knowledge_batches.replace(manifest, expected_sha256=expected_sha256)
        return f"本批 {success_count} 项成功，{failure_count} 项失败"

    def prepare_knowledge_research(
        self, role_id: str, capability_id: str
    ) -> str:
        detail = self.detail(role_id, capability_id)
        input_payload = self.knowledge_research_input(role_id, capability_id)
        capability = input_payload["capability"]
        assert isinstance(capability, dict)
        self.handoffs.prepare(
            "capability-knowledge-research",
            input_payload=input_payload,
            context={
                "role_id": role_id,
                "capability_id": capability_id,
                "input_fingerprint": str(capability["input_fingerprint"]),
                "expected_knowledge_sha256": detail.knowledge.expected_sha256,
            },
        )
        return prepared_handoff_message("capability-knowledge-research")

    def save_knowledge_result(
        self,
        role_id: str,
        capability_id: str,
        payload: str,
        *,
        expected_knowledge_sha256: str | None,
    ) -> str:
        target_id = self._uuid(capability_id, "capability_id")
        try:
            self.detail(role_id, capability_id)
            capability = next(
                item
                for item in self.storage.load_catalog().capabilities
                if item.capability_id == target_id
            )
            knowledge = CapabilityKnowledge.model_validate_json(payload)
            if knowledge.capability_id != target_id:
                raise ValueError("Knowledge 必须锚定当前 Capability")
            if knowledge.input_fingerprint != knowledge_input_fingerprint(capability):
                raise ValueError("Knowledge input fingerprint 与当前 Capability 不匹配")
            current, _ = self.storage.load_knowledge_snapshot(target_id)
            if current == knowledge:
                return f"Capability “{capability.name}” Knowledge 已是当前结果"
            if current is not None and knowledge.generated_at <= current.generated_at:
                raise ValueError("Refresh generated_at 必须晚于现有 Knowledge")
            self.storage.save_knowledge(
                knowledge,
                expected_sha256=expected_knowledge_sha256,
            )
            return (
                f"Capability “{capability.name}” Knowledge 已刷新"
                if current is not None
                else f"Capability “{capability.name}” Knowledge 已保存"
            )
        except Exception as exc:
            raise self._mutation_error("Save Capability Knowledge", exc) from exc

    @staticmethod
    def _mutation_error(operation: str, exc: Exception) -> ApplicationError:
        if isinstance(exc, ApplicationError):
            return exc
        if isinstance(exc, StaleStateError):
            return ApplicationError("conflict", operation, "数据已变化，请刷新后重试")
        if isinstance(exc, (ValueError, ValidationError, StopIteration)):
            return ApplicationError("validation", operation, str(exc))
        return ApplicationError("system", operation, "本地持久化操作失败")
