from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from application.errors import ApplicationError
from application.market_models import AtomicEvidenceView, AtomicSignalView, SimpleRoleView, SourceJDView, StageBMarketView
from schemas.core import JD, JDAnalysesDocument
from src.core_storage import CoreStorage
from src.market import analysis_input_document, analysis_is_current, build_atomic_market_statistics, jd_duplicate_key, read_jds_workbook, validate_analysis_against_jd
from src.semantic_handoff import SemanticHandoffStore, prepared_handoff_message
from src.state_safety import StaleStateError


class MarketOperations:
    """Application-facing boundary for the Stage B Role and Market flow."""

    def __init__(self, storage_root: Path) -> None:
        self.storage = CoreStorage(storage_root)
        self.storage.initialize()
        self.handoffs = SemanticHandoffStore(storage_root)

    @staticmethod
    def _uuid(value: str | UUID, label: str) -> UUID:
        try:
            return value if isinstance(value, UUID) else UUID(value)
        except (ValueError, TypeError) as exc:
            raise ApplicationError("validation", "validate identity", f"{label} 无效") from exc

    def resolve_role(self, requested_role_id: str | None) -> UUID | None:
        roles = self.storage.load_roles().roles
        if not roles:
            return None
        if requested_role_id:
            try:
                selected = UUID(requested_role_id)
            except ValueError:
                selected = None
            if selected in {item.role_id for item in roles}:
                return selected
        return roles[0].role_id

    def resolve_role_name(self, requested_name: str) -> UUID:
        normalized = requested_name.strip().casefold()
        role = next(
            (
                item
                for item in self.storage.load_roles().roles
                if item.name.casefold() == normalized
            ),
            None,
        )
        if role is None:
            raise ApplicationError("validation", "switch Role", "Role 不存在")
        return role.role_id

    def view(self, role_id: str | UUID | None = None) -> StageBMarketView:
        try:
            roles_document, roles_sha256 = self.storage.load_roles_snapshot()
            selected = self.resolve_role(str(role_id) if role_id else None)
            roles = tuple(SimpleRoleView(str(item.role_id), item.name, item.role_id == selected) for item in roles_document.roles)
            if selected is None:
                return StageBMarketView(roles, None, (), (), 0, 0, 0, 0, roles_sha256, None, None, None, None)
            role = next(item for item in roles if item.current)
            jobs_document, jds_sha256 = self.storage.load_jds_snapshot(selected)
            analyses_document, analyses_sha256 = self.storage.load_jd_analyses_snapshot(selected)
            analyses_by_job = {item.job_id: item for item in analyses_document.analyses}
            current_analyses = [analyses_by_job[job.job_id] for job in jobs_document.jobs if analysis_is_current(job, analyses_by_job.get(job.job_id))]
            jobs = tuple(SourceJDView(str(item.job_id), item.title, item.company, item.jd_text, str(item.source_url) if item.source_url else None, analysis_is_current(item, analyses_by_job.get(item.job_id))) for item in jobs_document.jobs)
            signals = tuple(
                AtomicSignalView(
                    item.atomic_expression,
                    item.jd_count,
                    item.sample_size,
                    tuple(AtomicEvidenceView(str(e.job_id), e.job_title, e.source_expression, e.evidence) for e in item.evidence),
                )
                for item in build_atomic_market_statistics(jobs_document.jobs, current_analyses)
            )
            handoff_status = self.handoffs.status_for(
                "jd-analysis",
                context={
                    "role_id": str(selected),
                    "expected_sha256": analyses_sha256,
                },
            )
            return StageBMarketView(
                roles, role, jobs, signals, len(jobs), len(current_analyses), len(current_analyses), len(jobs) - len(current_analyses),
                roles_sha256, jds_sha256, analyses_sha256,
                handoff_status.state if handoff_status else None,
                handoff_status.message if handoff_status else None,
            )
        except ApplicationError:
            raise
        except (ValueError, ValidationError) as exc:
            raise ApplicationError("validation", "load Market", str(exc)) from exc
        except OSError as exc:
            raise ApplicationError("system", "load Market", "无法读取 Core storage") from exc

    def create_role(self, name: str, expected_sha256: str) -> tuple[str, str]:
        try:
            role = self.storage.create_role(name, expected_sha256=expected_sha256)
            return str(role.role_id), f"Role “{role.name}” 已创建"
        except Exception as exc:
            raise self._mutation_error("create Role", exc) from exc

    def rename_role(self, role_id: str, name: str, expected_sha256: str) -> str:
        try:
            role = self.storage.rename_role(self._uuid(role_id, "role_id"), name, expected_sha256=expected_sha256)
            return f"Role 已重命名为 “{role.name}”"
        except Exception as exc:
            raise self._mutation_error("rename Role", exc) from exc

    def delete_role(self, role_id: str, *, confirmation: str, expected_sha256: str) -> str:
        selected = self._uuid(role_id, "role_id")
        role = next((item for item in self.storage.load_roles().roles if item.role_id == selected), None)
        if role is None:
            raise ApplicationError("validation", "delete Role", "Role 不存在")
        if confirmation.strip() != role.name:
            raise ApplicationError("validation", "delete Role", "请输入完整 Role 名称确认删除")
        try:
            self.storage.delete_role(selected, expected_sha256=expected_sha256)
            return f"Role “{role.name}” 及其 Role-specific 数据已删除"
        except Exception as exc:
            raise self._mutation_error("delete Role", exc) from exc

    def add_job(self, role_id: str, *, title: str, jd_text: str, company: str | None, source_url: str | None, expected_sha256: str) -> str:
        selected = self._uuid(role_id, "role_id")
        try:
            current, _ = self.storage.load_jds_snapshot(selected)
            candidate = JD(role_id=selected, title=title, company=company, jd_text=jd_text, source_url=source_url)
            if jd_duplicate_key(candidate) in {jd_duplicate_key(item) for item in current.jobs}:
                raise ValueError("相同 JD 已存在")
            self.storage.replace_jds(selected, [*current.jobs, candidate], expected_sha256=expected_sha256)
            return f"JD “{candidate.title}” 已添加"
        except Exception as exc:
            raise self._mutation_error("add JD", exc) from exc

    def import_jobs(self, role_id: str, filename: str, content: bytes, *, mode: str, expected_sha256: str) -> str:
        if not filename.casefold().endswith(".xlsx"):
            raise ApplicationError("validation", "import JDs", "仅支持 .xlsx workbook")
        if mode not in {"append", "replace"}:
            raise ApplicationError("validation", "import JDs", "Import mode 无效")
        selected = self._uuid(role_id, "role_id")
        try:
            imported = read_jds_workbook(content, selected)
            current = self.storage.load_jds(selected).jobs
            if mode == "replace":
                result, duplicate_count = imported, 0
            else:
                known = {jd_duplicate_key(item) for item in current}
                novel = [item for item in imported if jd_duplicate_key(item) not in known]
                result, duplicate_count = [*current, *novel], len(imported) - len(novel)
            self.storage.replace_jds(selected, result, expected_sha256=expected_sha256)
            if mode == "replace":
                return f"当前 Role 的 JD 集合已替换为 {len(result)} 条"
            return f"已导入 {len(result) - len(current)} 条 JD" + (f"，跳过 {duplicate_count} 条重复 JD" if duplicate_count else "")
        except Exception as exc:
            raise self._mutation_error("import JDs", exc) from exc

    def delete_jobs(self, role_id: str, job_ids: list[str], *, expected_sha256: str) -> str:
        selected = self._uuid(role_id, "role_id")
        try:
            ids = {self._uuid(value, "job_id") for value in job_ids}
            count = self.storage.delete_jds(selected, ids, expected_sha256=expected_sha256)
            return f"已删除 {count} 条 JD"
        except Exception as exc:
            raise self._mutation_error("delete JDs", exc) from exc

    def import_analyses(self, role_id: str, result_json: str, *, expected_sha256: str) -> str:
        selected = self._uuid(role_id, "role_id")
        try:
            candidate = JDAnalysesDocument.model_validate_json(result_json)
            if candidate.role_id != selected:
                raise ValueError("Analysis result 不属于当前 Role")
            jobs = self.storage.load_jds(selected).jobs
            jobs_by_id = {item.job_id: item for item in jobs}
            for analysis in candidate.analyses:
                job = jobs_by_id.get(analysis.job_id)
                if job is None:
                    raise ValueError("Analysis result 引用了当前 Role 之外的 JD")
                validate_analysis_against_jd(job, analysis)
            imported_ids = {item.job_id for item in candidate.analyses}
            try:
                current = self.storage.load_jd_analyses(selected).analyses
            except ValueError:
                if imported_ids != set(jobs_by_id):
                    raise ValueError(
                        "已有 JD Analysis 无法读取，必须重新分析当前 Role 的全部 JD"
                    )
                merged = list(candidate.analyses)
            else:
                merged = [item for item in current if item.job_id in jobs_by_id and item.job_id not in imported_ids and analysis_is_current(jobs_by_id[item.job_id], item)]
                merged.extend(candidate.analyses)
            self.storage.replace_jd_analyses(selected, merged, expected_sha256=expected_sha256)
            return f"已验证并保存 {len(candidate.analyses)} 条 JD Analysis"
        except Exception as exc:
            raise self._mutation_error("import JD Analysis", exc) from exc

    def prepare_analysis(self, role_id: str) -> str:
        selected = self._uuid(role_id, "role_id")
        try:
            jobs = self.storage.load_jds(selected).jobs
            if not jobs:
                raise ValueError("当前 Role 没有可分析的 JD")
            analyses_sha256 = self.storage.jd_analyses_sha256(selected)
            self.handoffs.prepare(
                "jd-analysis",
                input_payload=json.loads(analysis_input_document(selected, jobs)),
                context={
                    "role_id": str(selected),
                    "expected_sha256": analyses_sha256,
                },
            )
            return prepared_handoff_message("jd-analysis")
        except Exception as exc:
            raise self._mutation_error("prepare JD Analysis", exc) from exc

    @staticmethod
    def _mutation_error(operation: str, exc: Exception) -> ApplicationError:
        if isinstance(exc, ApplicationError):
            return exc
        if isinstance(exc, StaleStateError):
            return ApplicationError("conflict", operation, "数据已变化，请刷新后重试")
        if isinstance(exc, (ValueError, ValidationError)):
            return ApplicationError("validation", operation, str(exc))
        return ApplicationError("system", operation, "本地持久化操作失败")
