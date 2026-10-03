from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from string import Formatter
from typing import Mapping

from fastapi import Request


SUPPORTED_LOCALES = ("zh-CN", "en")
FALLBACK_LOCALE = "zh-CN"
LOCALE_COOKIE = "job_learning_ui_locale"


class CatalogError(ValueError):
    """The centralized UI message catalogs do not satisfy their contract."""


class MissingTranslationError(CatalogError):
    """A requested UI message is absent from a validated catalog."""


@dataclass(frozen=True)
class MessageCatalog:
    messages: Mapping[str, Mapping[str, str]]

    @classmethod
    def load(cls, directory: Path) -> "MessageCatalog":
        loaded: dict[str, dict[str, str]] = {}
        for locale in SUPPORTED_LOCALES:
            path = directory / f"{locale}.json"
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise CatalogError(f"invalid UI message catalog: {path}") from exc
            if not isinstance(value, dict):
                raise CatalogError(f"UI message catalog must be an object: {path}")
            if not all(
                isinstance(key, str) and key and isinstance(message, str)
                for key, message in value.items()
            ):
                raise CatalogError(
                    f"UI message catalog keys and values must be strings: {path}"
                )
            loaded[locale] = value

        expected_keys = set(loaded[FALLBACK_LOCALE])
        for locale in SUPPORTED_LOCALES:
            actual_keys = set(loaded[locale])
            if actual_keys != expected_keys:
                missing = sorted(expected_keys - actual_keys)
                orphan = sorted(actual_keys - expected_keys)
                raise CatalogError(
                    f"UI message catalog key mismatch for {locale}; "
                    f"missing={missing}, orphan={orphan}"
                )
        return cls(loaded)

    def translate(self, locale: str, key: str, **params: object) -> str:
        if locale not in SUPPORTED_LOCALES:
            raise CatalogError(f"unsupported UI locale: {locale}")
        try:
            message = self.messages[locale][key]
        except KeyError as exc:
            raise MissingTranslationError(
                f"missing UI translation for locale={locale}, key={key}"
            ) from exc
        try:
            return message.format(**params)
        except (KeyError, ValueError) as exc:
            fields = sorted(
                field_name
                for _, field_name, _, _ in Formatter().parse(message)
                if field_name
            )
            raise CatalogError(
                f"invalid UI translation parameters for locale={locale}, "
                f"key={key}, expected={fields}"
            ) from exc


def _accept_language_locale(header: str | None) -> str | None:
    if not header:
        return None
    preferences: list[tuple[float, int, str]] = []
    for position, item in enumerate(header.split(",")):
        parts = [part.strip() for part in item.split(";")]
        language = parts[0].replace("_", "-").lower()
        if not language:
            continue
        quality = 1.0
        for parameter in parts[1:]:
            if not parameter.lower().startswith("q="):
                continue
            try:
                quality = float(parameter[2:])
            except ValueError:
                quality = -1.0
            break
        if not 0 < quality <= 1:
            continue
        preferences.append((-quality, position, language))

    for _, _, language in sorted(preferences):
        if language == "zh" or language.startswith("zh-"):
            return "zh-CN"
        if language == "en" or language.startswith("en-"):
            return "en"
    return None


def resolve_locale(cookie_locale: str | None, accept_language: str | None) -> str:
    if cookie_locale in SUPPORTED_LOCALES:
        return cookie_locale
    return _accept_language_locale(accept_language) or FALLBACK_LOCALE


def request_locale(request: Request) -> str:
    return resolve_locale(
        request.cookies.get(LOCALE_COOKIE),
        request.headers.get("accept-language"),
    )


def translate_request(request: Request, key: str, **params: object) -> str:
    catalog: MessageCatalog = request.app.state.ui_messages
    return catalog.translate(request_locale(request), key, **params)


_BATCH_KNOWLEDGE_GUIDANCE = (
    "Knowledge Research batch request is prepared. Research has not run for this "
    "batch yet. Next: run the `capability-knowledge-research` Agent Skill. One "
    "Skill run processes one batch. After it finishes, return to Capabilities "
    "to review progress; if items remain, run the same Skill again."
)
_BATCH_CAPABILITY_GUIDANCE = (
    "Capability Analysis batch request is prepared. Recommendations have not "
    "been generated for this batch yet. Next: run the `capability-analysis` "
    "Agent Skill. One Skill run processes one batch. After it finishes, return to "
    "Capability Inbox to review advice and make each Add, Merge, or Skip "
    "decision; if candidates remain, run the same Skill again."
)


_SYSTEM_MESSAGE_KEYS = {
    "Add at least one JD": "roadmap.blocker.add_jd",
    "Analyze at least one current JD": "roadmap.blocker.analyze_jd",
    "Resolve Capability Inbox": "roadmap.blocker.resolve_inbox",
    "Map at least one Capability": "roadmap.blocker.map_capability",
    "Include at least one Capability in Roadmap": "roadmap.blocker.include_capability",
    "Create a Role": "roadmap.blocker.create_role",
    "界面语言不受支持": "locale.invalid",
    "当前 Role 已切换": "feedback.role_switched",
    "Role 不存在": "message.role_missing",
    "Capability 不存在": "message.capability_missing",
    "Capability 不属于当前 Role": "message.capability_not_in_role",
    "Capability 仍有 SourceMapping，请先 Unmap 或 Reassign": "message.capability_has_mappings",
    "Capability name 已存在，请改为 Merge": "message.capability_name_exists",
    "当前 Role 没有 pending Candidate": "message.no_pending_candidate",
    "当前 Role 没有可准备的未分析 Candidate": "message.no_unanalyzed_candidate",
    "当前 Role 没有可准备的未研究 Capability": "message.no_unresearched_capability",
    "Candidate 已变化或已处理": "message.candidate_changed",
    "Candidate 已变化或已处理。": "message.candidate_changed",
    "Candidate 已 Skip，请先 Restore": "message.candidate_skipped",
    "Candidate 已映射，不能 Skip": "message.candidate_mapped",
    "请选择现有 Capability": "message.choose_capability",
    "只能选择当前 Role 中仍待处理且尚无 Recommendation 的 Candidate": "message.invalid_candidate_selection",
    "只能选择当前 Role 中尚无 Knowledge 的 Capability": "message.invalid_knowledge_selection",
    "当前没有可重试的失败项": "message.no_failed_items",
    "请先完成当前已准备的剩余批次": "message.finish_current_batch",
    "当前 Role 与 Capability Analysis batch 的准备 Role 不一致": "message.batch_role_mismatch",
    "当前 Role 与 Knowledge batch 的准备 Role 不一致": "message.batch_role_mismatch",
    "失败项已获得 Recommendation 或已处理，无需重试": "message.analysis_retry_stale",
    "失败项已研究或已不属于原 Role，无需重试": "message.knowledge_retry_stale",
    "Batch 已被替换": "message.batch_replaced",
    "Batch 已变化，请重新运行": "message.batch_changed",
    "Batch input 无效": "message.batch_invalid",
    "Capability 已变化，请重新准备。": "message.capability_changed",
    "数据已变化，请刷新后重试": "message.data_changed",
    "目标文件已发生变化，请刷新页面后重试": "message.data_changed",
    "本地持久化操作失败": "message.persistence_failed",
    "无法读取 Core storage": "message.storage_unreadable",
    "请输入完整 Role 名称确认删除": "message.role_confirmation_invalid",
    "相同 JD 已存在": "message.jd_duplicate",
    "Import mode 无效": "message.import_mode_invalid",
    "Analysis result 不属于当前 Role": "message.analysis_wrong_role",
    "Analysis result 引用了当前 Role 之外的 JD": "message.analysis_wrong_jd",
    "已有 JD Analysis 无法读取，必须重新分析当前 Role 的全部 JD": "message.analysis_unreadable",
    "当前 Role 没有可分析的 JD": "message.no_analyzable_jd",
    "current_level 必须是 0–5 的整数": "message.level_invalid",
    "Practice description 不能为空": "message.practice_required",
    "Practice 不属于当前 Capability": "message.practice_wrong_capability",
    "Roadmap version 不存在": "message.roadmap_missing",
    "请先完成页面列出的准备事项": "message.roadmap_not_ready",
    "当前 Role inputs 尚未满足 Roadmap generation 条件": "message.roadmap_not_ready",
    "Roadmap result schema_version 不受支持": "message.roadmap_schema_invalid",
    "Roadmap result input_fingerprint 已过期": "message.roadmap_stale",
    "Roadmap未保存；已有版本保持不变": "message.roadmap_not_saved",
    "请输入 preview中的完整 Reset ID": "message.reset_id_invalid",
    "请输入 FULL DEVELOPMENT RESET 确认": "message.reset_phrase_invalid",
    "请先创建 Role": "message.create_role_first",
    "请先选择 Role": "message.select_role_first",
    "当前 Role 已变化": "message.role_changed",
    "表单 Role 与当前 Role 不一致，请刷新页面后重试": "message.role_changed_refresh",
    "请求状态不可用，请重新运行。": "message.handoff_unavailable",
    "研究结果未通过现有 Knowledge 校验。": "message.knowledge_validation_failed",
    "Skipped Candidate 已恢复": "message.candidate_restored",
    "Candidate 已处于恢复状态": "message.candidate_already_restored",
    "Capability Knowledge 已移除；Level 与 Practice 保持不变": "message.knowledge_removed",
    "当前水平已保存": "message.level_saved",
    "已纳入当前 Role 的学习路线": "message.roadmap_scope_included",
    "已从当前 Role 的学习路线排除": "message.roadmap_scope_excluded",
    "Practice 已添加": "message.practice_added",
    "Practice 已移除": "message.practice_removed",
    "Practice 已更新": "message.practice_updated",
    "Roadmap version 已删除": "message.roadmap_deleted",
    "相同 Roadmap version 已存在": "message.roadmap_exists",
    "新 Roadmap version 已保存": "message.roadmap_saved",
    "当前 Role 的 Inbox 已处理完成": "message.inbox_complete",
    "JD Analysis request is prepared. Analysis has not run yet. Next: run the `jd-analysis` Agent Skill. After it finishes, return to Market to view the new Market Signals.": "handoff.jd_prepared",
    "Capability Analysis request is prepared. The recommendation has not been generated yet. Next: run the `capability-analysis` Agent Skill. After it finishes, return to this Capability Inbox candidate to view the advice and continue with Add, Merge, or Skip.": "handoff.capability_prepared",
    "Knowledge Research request is prepared. Research has not run yet. Next: run the `capability-knowledge-research` Agent Skill. After it finishes, return to Capability Detail to view the Knowledge.": "handoff.knowledge_prepared",
    "Roadmap Generation request is prepared. The Roadmap has not been generated yet. Next: run the `job-learning-roadmap` Agent Skill. After it finishes, return to Roadmap to view the latest version.": "handoff.roadmap_prepared",
    _BATCH_KNOWLEDGE_GUIDANCE: "handoff.knowledge_batch_prepared",
    _BATCH_CAPABILITY_GUIDANCE: "handoff.capability_batch_prepared",
    "Knowledge 研究结果未通过校验，已有内容未受影响。Run `capability-knowledge-research` again, then return to Capability Detail or Capabilities.": "handoff.knowledge_failed",
}

_SYSTEM_MESSAGE_PATTERNS = (
    (re.compile(r'^Role “(?P<name>.+)” 已创建$'), "message.role_created"),
    (re.compile(r'^Role 已重命名为 “(?P<name>.+)”$'), "message.role_renamed"),
    (re.compile(r'^Role “(?P<name>.+)” 及其 Role-specific 数据已删除$'), "message.role_deleted"),
    (re.compile(r'^JD “(?P<title>.+)” 已添加$'), "message.jd_added"),
    (re.compile(r'^当前 Role 的 JD 集合已替换为 (?P<count>\d+) 条$'), "message.jd_replaced"),
    (re.compile(r'^已导入 (?P<count>\d+) 条 JD$'), "message.jd_imported"),
    (re.compile(r'^已导入 (?P<count>\d+) 条 JD，跳过 (?P<duplicates>\d+) 条重复 JD$'), "message.jd_imported_duplicates"),
    (re.compile(r'^已删除 (?P<count>\d+) 条 JD$'), "message.jd_deleted"),
    (re.compile(r'^已验证并保存 (?P<count>\d+) 条 JD Analysis$'), "message.analysis_saved"),
    (re.compile(r'^已准备 (?P<count>\d+) 个 Candidate，共 (?P<batches>\d+) 批$'), "message.analysis_batch_prepared"),
    (re.compile(r'^已准备 (?P<count>\d+) 个 Capability，共 (?P<batches>\d+) 批$'), "message.knowledge_batch_prepared"),
    (re.compile(r'^第 (?P<current>\d+) / (?P<total>\d+) 批已准备。$'), "message.batch_prepared"),
    (re.compile(r'^本批 (?P<success>\d+) 项 Recommendation 成功，(?P<failed>\d+) 项失败$'), "message.analysis_batch_saved"),
    (re.compile(r'^本批 (?P<success>\d+) 项成功，(?P<failed>\d+) 项失败$'), "message.knowledge_batch_saved"),
    (re.compile(r'^已创建 Capability “(?P<name>.+)” 并建立 mapping$'), "message.capability_created"),
    (re.compile(r'^Capability “(?P<name>.+)” 的 mapping 已存在$'), "message.mapping_exists"),
    (re.compile(r'^已将 “(?P<source>.+)” Merge 到 “(?P<target>.+)”$'), "message.capability_merged"),
    (re.compile(r'^已在当前 Role Skip “(?P<source>.+)”$'), "message.candidate_skipped_now"),
    (re.compile(r'^“(?P<source>.+)” 已在当前 Role Skip$'), "message.candidate_already_skipped"),
    (re.compile(r'^Capability 已重命名为 “(?P<name>.+)”$'), "message.capability_renamed"),
    (re.compile(r'^已取消 “(?P<source>.+)” 的 Mapping$'), "message.mapping_unmapped"),
    (re.compile(r'^已将 “(?P<source>.+)” Reassign 到 “(?P<target>.+)”$'), "message.mapping_reassigned"),
    (re.compile(r'^Capability “(?P<name>.+)” 及其当前附属数据已删除$'), "message.capability_deleted"),
    (re.compile(r'^Capability “(?P<name>.+)” Knowledge 已是当前结果$'), "message.knowledge_current"),
    (re.compile(r'^Capability “(?P<name>.+)” Knowledge 已刷新$'), "message.knowledge_refreshed"),
    (re.compile(r'^Capability “(?P<name>.+)” Knowledge 已保存$'), "message.knowledge_saved"),
    (re.compile(r'^Full Development Reset完成：删除 (?P<count>\d+) 个业务文件$'), "message.reset_complete"),
)


_BATCH_COMPOSITE_PATTERNS = (
    (
        re.compile(
            r'^已准备 (?P<count>\d+) 个 Candidate，共 (?P<batches>\d+) 批'
            r'（(?P<sizes>\d+(?: / \d+)*)）。'
            + re.escape(_BATCH_CAPABILITY_GUIDANCE)
            + r'$'
        ),
        "message.analysis_batch_prepared_detailed",
        "handoff.capability_batch_prepared",
    ),
    (
        re.compile(
            r'^已准备 (?P<count>\d+) 个 Capability，共 (?P<batches>\d+) 批'
            r'（(?P<sizes>\d+(?: / \d+)*)）。'
            + re.escape(_BATCH_KNOWLEDGE_GUIDANCE)
            + r'$'
        ),
        "message.knowledge_batch_prepared_detailed",
        "handoff.knowledge_batch_prepared",
    ),
    (
        re.compile(
            r'^第 (?P<current>\d+) / (?P<total>\d+) 批已准备。'
            + re.escape(_BATCH_CAPABILITY_GUIDANCE)
            + r'$'
        ),
        "message.batch_prepared",
        "handoff.capability_batch_prepared",
    ),
    (
        re.compile(
            r'^第 (?P<current>\d+) / (?P<total>\d+) 批已准备。'
            + re.escape(_BATCH_KNOWLEDGE_GUIDANCE)
            + r'$'
        ),
        "message.batch_prepared",
        "handoff.knowledge_batch_prepared",
    ),
)


def localize_system_message(
    catalog: MessageCatalog, locale: str, message: str | None
) -> str | None:
    """Localize stable Web-facing results without passing locale into Core."""
    if message is None:
        return None
    key = _SYSTEM_MESSAGE_KEYS.get(message)
    if key is not None:
        return catalog.translate(locale, key)
    for pattern, summary_key, guidance_key in _BATCH_COMPOSITE_PATTERNS:
        match = pattern.fullmatch(message)
        if match is not None:
            summary = catalog.translate(locale, summary_key, **match.groupdict())
            guidance = catalog.translate(locale, guidance_key)
            return f"{summary} {guidance}"
    for pattern, pattern_key in _SYSTEM_MESSAGE_PATTERNS:
        match = pattern.fullmatch(message)
        if match is not None:
            return catalog.translate(locale, pattern_key, **match.groupdict())
    # ApplicationError.public_message and redirect notices are explicitly the
    # Web-safe boundary. If a new message has not been added to the translation
    # table yet, preserve its concrete reason instead of replacing it with an
    # ambiguous retry instruction that can misrepresent a successful action.
    return message


def localize_request_message(request: Request, message: str | None) -> str | None:
    catalog: MessageCatalog = request.app.state.ui_messages
    return localize_system_message(catalog, request_locale(request), message)
