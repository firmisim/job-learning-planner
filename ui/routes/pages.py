from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import quote, urlsplit, urlunsplit

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from application.capabilities import CapabilityOperations
from application.errors import ApplicationError
from application.learning import LearningOperations
from application.market import MarketOperations
from application.roadmaps import RoadmapOperations
from application.settings import SettingsOperations
from schemas.capability_recommendation import CapabilityRecommendation
from ui.i18n import (
    LOCALE_COOKIE,
    SUPPORTED_LOCALES,
    localize_request_message,
    translate_request,
)
from ui.interactions import redirect_with_notice
from ui.pagination import paginate


router = APIRouter()
NAV_ITEMS = (
    ("nav.market", "/market", "market"),
    ("nav.capabilities", "/capabilities", "capabilities"),
    ("nav.learning", "/learning", "learning"),
    ("nav.roadmaps", "/roadmaps", "roadmaps"),
    ("nav.settings", "/settings", "settings"),
)
ROLE_COOKIE = "job_learning_current_role"


def _market(request: Request) -> MarketOperations:
    return request.app.state.market


def _capabilities(request: Request) -> CapabilityOperations:
    return request.app.state.capabilities


def _learning(request: Request) -> LearningOperations:
    return request.app.state.learning


def _roadmaps(request: Request) -> RoadmapOperations:
    return request.app.state.roadmaps


def _settings(request: Request) -> SettingsOperations:
    return request.app.state.settings


def _selected_role(request: Request) -> str | None:
    selected = _market(request).resolve_role(request.cookies.get(ROLE_COOKIE))
    return str(selected) if selected else None


def _optional(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _notice(request: Request) -> str | None:
    return localize_request_message(request, request.query_params.get("notice"))


def _safe_locale_return_path(value: str) -> str:
    try:
        target = urlsplit(value)
    except ValueError:
        return "/market"
    if (
        not target.path.startswith("/")
        or target.path.startswith("//")
        or "\\" in target.path
        or target.scheme
        or target.netloc
        or any(ord(character) < 32 for character in value)
    ):
        return "/market"
    return urlunsplit(("", "", target.path, target.query, ""))


def _redirect(message: str, *, role_id: str | None = None) -> RedirectResponse:
    response = redirect_with_notice("/market", message)
    if role_id is not None:
        response.set_cookie(ROLE_COOKIE, role_id, httponly=True, samesite="lax")
    return response


def _redirect_to(
    path: str, message: str, *, role_id: str | None = None
) -> RedirectResponse:
    response = redirect_with_notice(path, message)
    if role_id is not None:
        response.set_cookie(ROLE_COOKIE, role_id, httponly=True, samesite="lax")
    return response


def _render(request: Request, view: Any) -> HTMLResponse:
    job_page = paginate(
        view.jobs,
        query=request.query_params.get("jd_query"),
        page=request.query_params.get("jd_page"),
        searchable_text=lambda item: " ".join(
            value
            for value in (item.title, item.company, item.jd_text, item.source_url)
            if value
        ),
    )
    signal_page = paginate(
        view.signals,
        query=request.query_params.get("signal_query"),
        page=request.query_params.get("signal_page"),
        searchable_text=lambda item: " ".join(
            [item.atomic_expression]
            + [
                f"{evidence.job_title} {evidence.source_expression} {evidence.evidence}"
                for evidence in item.evidence
            ]
        ),
    )
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="market.html",
        context={
            "page_title": "Market",
            "page_title_key": "page.market.title",
            "active_nav": "market",
            "navigation": NAV_ITEMS,
            "view": view,
            "job_page": job_page,
            "signal_page": signal_page,
            "notice": _notice(request),
            "notice_level": request.query_params.get("level", "success"),
        },
    )


@router.get("/health", name="health")
def health() -> dict[str, str]:
    return {"status": "ok", "stage": "clean-rebuild-complete"}


@router.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/market", status_code=307)


@router.post("/locale", name="locale_switch")
def locale_switch(
    request: Request,
    locale: Annotated[str, Form()],
    next: Annotated[str, Form()] = "/market",
) -> RedirectResponse:
    if locale not in SUPPORTED_LOCALES:
        raise ApplicationError(
            "validation",
            "switch UI locale",
            "界面语言不受支持",
        )
    response = RedirectResponse(_safe_locale_return_path(next), status_code=303)
    response.set_cookie(
        LOCALE_COOKIE,
        locale,
        max_age=31_536_000,
        path="/",
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/market", response_class=HTMLResponse, name="market")
def market(request: Request) -> HTMLResponse:
    return _render(request, _market(request).view(_selected_role(request)))


@router.post("/settings/roles", name="role_create")
def role_create(
    request: Request,
    name: Annotated[str, Form()],
    expected_sha256: Annotated[str, Form()],
) -> RedirectResponse:
    role_id, message = _market(request).create_role(name, expected_sha256)
    return _redirect_to("/settings", message, role_id=role_id)


@router.post("/roles/switch", name="role_switch")
def role_switch(
    request: Request,
    role_name: Annotated[str, Form()],
    return_to: Annotated[str, Form()] = "/market",
) -> RedirectResponse:
    selected = _market(request).resolve_role_name(role_name)
    return _redirect_to(
        return_to,
        "当前 Role 已切换",
        role_id=str(selected),
    )


@router.post("/settings/roles/rename", name="role_rename")
def role_rename(
    request: Request,
    role_id: Annotated[str, Form()],
    name: Annotated[str, Form()],
    expected_sha256: Annotated[str, Form()],
) -> RedirectResponse:
    return _redirect_to(
        "/settings",
        _market(request).rename_role(role_id, name, expected_sha256),
        role_id=role_id,
    )


@router.post("/settings/roles/delete", name="role_delete")
def role_delete(
    request: Request,
    role_id: Annotated[str, Form()],
    confirmation: Annotated[str, Form()],
    expected_sha256: Annotated[str, Form()],
) -> RedirectResponse:
    message = _market(request).delete_role(
        role_id,
        confirmation=confirmation,
        expected_sha256=expected_sha256,
    )
    next_role = _market(request).resolve_role(None)
    response = _redirect_to(
        "/settings", message, role_id=str(next_role) if next_role else None
    )
    if next_role is None:
        response.delete_cookie(ROLE_COOKIE)
    return response


@router.post("/market/jobs", name="job_create")
def job_create(
    request: Request,
    role_id: Annotated[str, Form()],
    title: Annotated[str, Form()],
    jd_text: Annotated[str, Form()],
    expected_sha256: Annotated[str, Form()],
    company: Annotated[str, Form()] = "",
    source_url: Annotated[str, Form()] = "",
) -> RedirectResponse:
    message = _market(request).add_job(
        role_id,
        title=title,
        company=_optional(company),
        jd_text=jd_text,
        source_url=_optional(source_url),
        expected_sha256=expected_sha256,
    )
    return _redirect(message, role_id=role_id)


@router.post("/market/jobs/delete", name="jobs_delete")
async def jobs_delete(request: Request) -> RedirectResponse:
    form = await request.form()
    role_id = str(form.get("role_id") or "")
    message = _market(request).delete_jobs(
        role_id,
        [str(value) for value in form.getlist("job_id")],
        expected_sha256=str(form.get("expected_sha256") or ""),
    )
    return _redirect_to(
        "/market?selection_cleared=market-jd#jd-list",
        message,
        role_id=role_id,
    )


@router.post("/market/import", name="jobs_import")
async def jobs_import(
    request: Request,
    workbook: Annotated[UploadFile, File()],
    role_id: Annotated[str, Form()],
    mode: Annotated[str, Form()],
    expected_sha256: Annotated[str, Form()],
) -> RedirectResponse:
    message = _market(request).import_jobs(
        role_id,
        workbook.filename or "",
        await workbook.read(),
        mode=mode,
        expected_sha256=expected_sha256,
    )
    return _redirect(message, role_id=role_id)


@router.post("/market/analysis", name="analysis_prepare")
def analysis_prepare(
    request: Request,
    role_id: Annotated[str, Form()],
) -> RedirectResponse:
    if role_id != _selected_role(request):
        raise ApplicationError("validation", "prepare JD Analysis", "当前 Role 已变化")
    message = _market(request).prepare_analysis(role_id)
    return _redirect(message, role_id=role_id)


def _render_capabilities(
    request: Request,
    *,
    status_code: int = 200,
    error_message: str | None = None,
) -> HTMLResponse:
    view = _capabilities(request).workspace(_selected_role(request))
    pending_page = paginate(
        view.pending_candidates,
        query=request.query_params.get("pending_query"),
        page=request.query_params.get("pending_page"),
        searchable_text=lambda item: " ".join(
            [item.atomic_expression]
            + [evidence.evidence for evidence in item.evidence]
        ),
    )
    current_page = paginate(
        view.current_capabilities,
        query=request.query_params.get("current_query"),
        page=request.query_params.get("current_page"),
        searchable_text=lambda item: " ".join((item.name, *item.atomic_expressions)),
    )
    missing_knowledge_page = paginate(
        view.missing_knowledge,
        query=request.query_params.get("knowledge_query"),
        page=request.query_params.get("knowledge_page"),
        searchable_text=lambda item: " ".join((item.name, *item.atomic_expressions)),
    )
    skipped_page = paginate(
        view.skipped_candidates,
        query=request.query_params.get("skipped_query"),
        page=request.query_params.get("skipped_page"),
        searchable_text=lambda item: item.atomic_expression,
    )
    all_page = paginate(
        view.global_capabilities,
        query=request.query_params.get("all_query"),
        page=request.query_params.get("all_page"),
        searchable_text=lambda item: " ".join((item.name, *item.atomic_expressions)),
    )
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="capabilities.html",
        context={
            "page_title": "Capabilities",
            "page_title_key": "page.capabilities.title",
            "active_nav": "capabilities",
            "navigation": NAV_ITEMS,
            "view": view,
            "pending_page": pending_page,
            "current_page": current_page,
            "missing_knowledge_page": missing_knowledge_page,
            "skipped_page": skipped_page,
            "all_page": all_page,
            "notice": _notice(request),
            "notice_level": request.query_params.get("level", "success"),
            "error_message": error_message,
        },
        status_code=status_code,
    )


def _render_inbox(
    request: Request,
    candidate_fingerprint: str,
    *,
    recommendation: CapabilityRecommendation | None = None,
    error_message: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    role_id = _selected_role(request)
    if role_id is None:
        raise ApplicationError("validation", "open Capability Inbox", "请先创建 Role")
    view = _capabilities(request).inbox(
        role_id,
        candidate_fingerprint,
        merge_query=request.query_params.get("merge_query"),
        recommendation=recommendation,
        error_message=error_message,
    )
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="capability_inbox.html",
        context={
            "page_title": "Capability Inbox",
            "page_title_key": "inbox.title",
            "active_nav": "capabilities",
            "navigation": NAV_ITEMS,
            "view": view,
            "notice": _notice(request),
            "notice_level": request.query_params.get("level", "success"),
        },
        status_code=status_code,
    )


def _inbox_error(
    request: Request, candidate_fingerprint: str, exc: ApplicationError
) -> HTMLResponse:
    status_code = 409 if exc.category == "conflict" else 422
    try:
        return _render_inbox(
            request,
            candidate_fingerprint,
            error_message=exc.public_message,
            status_code=status_code,
        )
    except ApplicationError:
        return _render_capabilities(
            request,
            error_message=exc.public_message,
            status_code=status_code,
        )


def _next_inbox_path(request: Request) -> str:
    workspace = _capabilities(request).workspace(_selected_role(request))
    if not workspace.pending_candidates:
        return "/capabilities"
    return (
        "/capabilities/inbox/" + workspace.pending_candidates[0].candidate_fingerprint
    )


def _render_learning(
    request: Request,
    *,
    status_code: int = 200,
    error_message: str | None = None,
) -> HTMLResponse:
    view = _learning(request).view(_selected_role(request))
    learning_page = paginate(
        view.capabilities,
        query=request.query_params.get("query"),
        page=request.query_params.get("page"),
        searchable_text=lambda item: item.name,
    )
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="learning.html",
        context={
            "page_title": "My Learning",
            "page_title_key": "page.learning.title",
            "active_nav": "learning",
            "navigation": NAV_ITEMS,
            "view": view,
            "learning_page": learning_page,
            "notice": _notice(request),
            "notice_level": request.query_params.get("level", "success"),
            "error_message": error_message,
        },
        status_code=status_code,
    )


def _render_learning_detail(
    request: Request,
    capability_id: str,
    *,
    status_code: int = 200,
    error_message: str | None = None,
) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="learning_detail.html",
        context={
            "page_title": "My Learning",
            "page_title_key": "page.learning.title",
            "active_nav": "learning",
            "navigation": NAV_ITEMS,
            "view": _learning(request).detail(
                _selected_role(request) or "", capability_id
            ),
            "notice": _notice(request),
            "notice_level": request.query_params.get("level", "success"),
            "error_message": error_message,
        },
        status_code=status_code,
    )


def _learning_detail_error(
    request: Request, capability_id: str, exc: ApplicationError
) -> HTMLResponse:
    try:
        return _render_learning_detail(
            request,
            capability_id,
            error_message=exc.public_message,
            status_code=409 if exc.category == "conflict" else 422,
        )
    except ApplicationError:
        return _render_learning(
            request,
            error_message=exc.public_message,
            status_code=409 if exc.category == "conflict" else 422,
        )


def _current_learning_role(request: Request, submitted_role_id: str) -> str:
    selected = _selected_role(request)
    if selected is None or selected != submitted_role_id:
        raise ApplicationError(
            "validation",
            "update My Learning",
            "表单 Role 与当前 Role 不一致，请刷新页面后重试",
        )
    return selected


@router.get("/learning", response_class=HTMLResponse, name="learning")
def learning(request: Request) -> HTMLResponse:
    return _render_learning(request)


@router.get(
    "/learning/capabilities/{capability_id}",
    response_class=HTMLResponse,
    name="learning_detail",
)
def learning_detail(request: Request, capability_id: str) -> HTMLResponse:
    return _render_learning_detail(request, capability_id)


@router.post(
    "/learning/capabilities/{capability_id}/roadmap-scope",
    name="learning_roadmap_scope_set",
)
def learning_roadmap_scope_set(
    request: Request,
    capability_id: str,
    role_id: Annotated[str, Form()],
    included: Annotated[bool, Form()],
    expected_sha256: Annotated[str | None, Form()] = None,
) -> Response:
    try:
        role_id = _current_learning_role(request, role_id)
        message = _learning(request).set_roadmap_inclusion(
            role_id,
            capability_id,
            included,
            expected_sha256=_optional(expected_sha256),
        )
    except ApplicationError as exc:
        return _learning_detail_error(request, capability_id, exc)
    return _redirect_to(
        f"/learning/capabilities/{capability_id}", message, role_id=role_id
    )


@router.post(
    "/learning/capabilities/{capability_id}/level", name="learning_level_set"
)
def learning_level_set(
    request: Request,
    capability_id: str,
    role_id: Annotated[str, Form()],
    current_level: Annotated[int, Form()],
    expected_sha256: Annotated[str, Form()],
) -> Response:
    try:
        role_id = _current_learning_role(request, role_id)
        message = _learning(request).set_level(
            role_id,
            capability_id,
            current_level,
            expected_sha256=expected_sha256,
        )
    except ApplicationError as exc:
        return _learning_detail_error(request, capability_id, exc)
    return _redirect_to(
        f"/learning/capabilities/{capability_id}", message, role_id=role_id
    )


@router.post(
    "/learning/capabilities/{capability_id}/practices",
    name="learning_practice_add",
)
def learning_practice_add(
    request: Request,
    capability_id: str,
    role_id: Annotated[str, Form()],
    description: Annotated[str, Form()],
    expected_sha256: Annotated[str, Form()],
) -> Response:
    try:
        role_id = _current_learning_role(request, role_id)
        message = _learning(request).add_practice(
            role_id,
            capability_id,
            description,
            expected_sha256=expected_sha256,
        )
    except ApplicationError as exc:
        return _learning_detail_error(request, capability_id, exc)
    return _redirect_to(
        f"/learning/capabilities/{capability_id}", message, role_id=role_id
    )


@router.post(
    "/learning/capabilities/{capability_id}/practices/{practice_id}/edit",
    name="learning_practice_edit",
)
def learning_practice_edit(
    request: Request,
    capability_id: str,
    practice_id: str,
    role_id: Annotated[str, Form()],
    expected_sha256: Annotated[str, Form()],
    description: Annotated[str, Form()] = "",
) -> Response:
    try:
        role_id = _current_learning_role(request, role_id)
        message = _learning(request).edit_practice(
            role_id,
            capability_id,
            practice_id,
            description,
            expected_sha256=expected_sha256,
        )
    except ApplicationError as exc:
        return _learning_detail_error(request, capability_id, exc)
    return _redirect_to(
        f"/learning/capabilities/{capability_id}", message, role_id=role_id
    )


def _render_roadmaps(
    request: Request,
    *,
    error_message: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    view = _roadmaps(request).view(_selected_role(request))
    history_page = paginate(
        view.history,
        query=None,
        page=request.query_params.get("history_page"),
        page_size=10,
    )
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="roadmaps.html",
        context={
            "page_title": "Roadmap",
            "page_title_key": "page.roadmaps.title",
            "active_nav": "roadmaps",
            "navigation": NAV_ITEMS,
            "view": view,
            "history_page": history_page,
            "notice": _notice(request),
            "notice_level": request.query_params.get("level", "success"),
            "error_message": error_message,
        },
        status_code=status_code,
    )


@router.get("/roadmaps", response_class=HTMLResponse, name="roadmaps")
def roadmaps(request: Request) -> HTMLResponse:
    return _render_roadmaps(request)


@router.post("/roadmaps", name="roadmap_prepare")
def roadmap_prepare(
    request: Request,
    role_id: Annotated[str, Form()],
) -> Response:
    try:
        role_id = _current_learning_role(request, role_id)
        message = _roadmaps(request).prepare_generation(role_id)
    except ApplicationError as exc:
        return _render_roadmaps(
            request,
            error_message=exc.public_message,
            status_code=409 if exc.category == "conflict" else 422,
        )
    return _redirect_to("/roadmaps", message, role_id=role_id)


@router.get(
    "/roadmaps/{roadmap_id}",
    response_class=HTMLResponse,
    name="roadmap_detail",
)
def roadmap_detail(request: Request, roadmap_id: str) -> HTMLResponse:
    role_id = _selected_role(request)
    if role_id is None:
        return _render_roadmaps(request, error_message="请先选择 Role", status_code=422)
    try:
        view = _roadmaps(request).detail(role_id, roadmap_id)
    except ApplicationError as exc:
        return _render_roadmaps(
            request,
            error_message=exc.public_message,
            status_code=409 if exc.category == "conflict" else 422,
        )
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="roadmap_detail.html",
        context={
            "page_title": "Roadmap Detail",
            "page_title_key": "roadmap.version",
            "active_nav": "roadmaps",
            "navigation": NAV_ITEMS,
            "view": view,
            "notice": _notice(request),
            "notice_level": request.query_params.get("level", "success"),
        },
    )


@router.get("/roadmaps/{roadmap_id}/export", name="roadmap_export")
def roadmap_export(request: Request, roadmap_id: str) -> Response:
    role_id = _selected_role(request)
    if role_id is None:
        return Response(
            translate_request(request, "message.select_role_first"),
            status_code=422,
            media_type="text/plain",
        )
    try:
        filename, content = _roadmaps(request).export_markdown(role_id, roadmap_id)
    except ApplicationError as exc:
        return Response(exc.public_message, status_code=422, media_type="text/plain")
    encoded_filename = quote(filename)
    headers = {
        "Content-Disposition": (
            'attachment; filename="roadmap.md"; '
            f"filename*=UTF-8''{encoded_filename}"
        )
    }
    return Response(
        content,
        media_type="text/markdown",
        headers=headers,
    )


@router.post("/roadmaps/{roadmap_id}/delete", name="roadmap_delete")
def roadmap_delete(
    request: Request,
    roadmap_id: str,
    role_id: Annotated[str, Form()],
) -> Response:
    try:
        role_id = _current_learning_role(request, role_id)
        message = _roadmaps(request).delete(role_id, roadmap_id)
    except ApplicationError as exc:
        return _render_roadmaps(
            request,
            error_message=exc.public_message,
            status_code=409 if exc.category == "conflict" else 422,
        )
    return _redirect_to("/roadmaps", message, role_id=role_id)


def _render_settings(
    request: Request,
    view: object | None = None,
    *,
    error_message: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "page_title": "Settings",
            "page_title_key": "page.settings.title",
            "active_nav": "settings",
            "navigation": NAV_ITEMS,
            "view": view or _settings(request).view(),
            "notice": _notice(request),
            "notice_level": request.query_params.get("level", "success"),
            "error_message": error_message,
        },
        status_code=status_code,
    )


@router.get("/settings", response_class=HTMLResponse, name="settings")
def settings(request: Request) -> HTMLResponse:
    return _render_settings(request)


@router.post(
    "/settings/development-reset/preview",
    response_class=HTMLResponse,
    name="settings_reset_preview",
)
def settings_reset_preview(request: Request) -> HTMLResponse:
    return _render_settings(request, _settings(request).preview_reset())


@router.post(
    "/settings/development-reset/apply", name="settings_reset_apply"
)
def settings_reset_apply(
    request: Request,
    manifest_json: Annotated[str, Form()],
    confirmation: Annotated[str, Form()],
    risk_confirmation: Annotated[str, Form()],
) -> Response:
    try:
        count = _settings(request).apply_reset(
            manifest_json,
            confirmation=confirmation,
            risk_confirmation=risk_confirmation,
        )
    except ApplicationError as exc:
        return _render_settings(
            request,
            error_message=exc.public_message,
            status_code=422,
        )
    response = _redirect_to("/settings", f"Full Development Reset完成：删除 {count} 个业务文件")
    response.delete_cookie(ROLE_COOKIE)
    return response


@router.get("/capabilities", response_class=HTMLResponse, name="capabilities")
def capabilities(request: Request) -> HTMLResponse:
    return _render_capabilities(request)


@router.get("/capabilities/inbox", name="capability_inbox_start")
def capability_inbox_start(request: Request) -> RedirectResponse:
    workspace = _capabilities(request).workspace(_selected_role(request))
    if not workspace.pending_candidates:
        return _redirect_to("/capabilities", "当前 Role 的 Inbox 已处理完成")
    return RedirectResponse(
        "/capabilities/inbox/" + workspace.pending_candidates[0].candidate_fingerprint,
        status_code=303,
    )


@router.get(
    "/capabilities/inbox/{candidate_fingerprint}",
    response_class=HTMLResponse,
    name="capability_inbox",
)
def capability_inbox(request: Request, candidate_fingerprint: str) -> HTMLResponse:
    return _render_inbox(request, candidate_fingerprint)


@router.post(
    "/capabilities/inbox/{candidate_fingerprint}/recommendation",
    name="capability_recommendation_prepare",
)
def capability_recommendation_prepare(
    request: Request,
    candidate_fingerprint: str,
) -> Response:
    role_id = _selected_role(request)
    if role_id is None:
        raise ApplicationError("validation", "prepare recommendation", "请先创建 Role")
    try:
        message = _capabilities(request).prepare_recommendation(
            role_id, candidate_fingerprint
        )
    except ApplicationError as exc:
        return _inbox_error(request, candidate_fingerprint, exc)
    return _redirect_to(
        f"/capabilities/inbox/{candidate_fingerprint}", message, role_id=role_id
    )


@router.post(
    "/capabilities/analysis/batch/selected", name="capability_analysis_batch_selected"
)
async def capability_analysis_batch_selected(request: Request) -> Response:
    form = await request.form()
    role_id = str(form.get("role_id") or "")
    try:
        role_id = _current_learning_role(request, role_id)
        message = _capabilities(request).prepare_capability_analysis_batch(
            role_id,
            [str(value) for value in form.getlist("candidate_fingerprint")],
        )
    except ApplicationError as exc:
        return _render_capabilities(
            request,
            error_message=exc.public_message,
            status_code=409 if exc.category == "conflict" else 422,
        )
    return _redirect_to(
        "/capabilities?selection_cleared=analysis#pending-candidates",
        message,
        role_id=role_id,
    )


@router.post(
    "/capabilities/analysis/batch/all", name="capability_analysis_batch_all"
)
def capability_analysis_batch_all(
    request: Request, role_id: Annotated[str, Form()]
) -> Response:
    try:
        role_id = _current_learning_role(request, role_id)
        message = _capabilities(request).prepare_capability_analysis_batch(role_id)
    except ApplicationError as exc:
        return _render_capabilities(
            request,
            error_message=exc.public_message,
            status_code=409 if exc.category == "conflict" else 422,
        )
    return _redirect_to(
        "/capabilities?selection_cleared=analysis#pending-candidates",
        message,
        role_id=role_id,
    )


@router.post(
    "/capabilities/analysis/batch/retry", name="capability_analysis_batch_retry"
)
def capability_analysis_batch_retry(
    request: Request, role_id: Annotated[str, Form()]
) -> Response:
    try:
        role_id = _current_learning_role(request, role_id)
        message = _capabilities(request).retry_failed_capability_analysis_batch(role_id)
    except ApplicationError as exc:
        return _render_capabilities(
            request,
            error_message=exc.public_message,
            status_code=409 if exc.category == "conflict" else 422,
        )
    return _redirect_to(
        "/capabilities#pending-candidates",
        message,
        role_id=role_id,
    )


@router.post(
    "/capabilities/inbox/{candidate_fingerprint}/add",
    name="capability_add",
)
def capability_add(
    request: Request,
    candidate_fingerprint: str,
    role_id: Annotated[str, Form()],
    canonical_name: Annotated[str, Form()],
    expected_catalog_sha256: Annotated[str, Form()],
) -> Response:
    try:
        message = _capabilities(request).add(
            role_id,
            candidate_fingerprint,
            canonical_name,
            expected_catalog_sha256=expected_catalog_sha256,
        )
    except ApplicationError as exc:
        return _inbox_error(request, candidate_fingerprint, exc)
    return _redirect_to(_next_inbox_path(request), message, role_id=role_id)


@router.post(
    "/capabilities/inbox/{candidate_fingerprint}/merge",
    name="capability_merge",
)
def capability_merge(
    request: Request,
    candidate_fingerprint: str,
    role_id: Annotated[str, Form()],
    capability_name: Annotated[str, Form()],
    expected_catalog_sha256: Annotated[str, Form()],
) -> Response:
    try:
        message = _capabilities(request).merge_by_name(
            role_id,
            candidate_fingerprint,
            capability_name,
            expected_catalog_sha256=expected_catalog_sha256,
        )
    except ApplicationError as exc:
        return _inbox_error(request, candidate_fingerprint, exc)
    return _redirect_to(_next_inbox_path(request), message, role_id=role_id)


@router.post(
    "/capabilities/inbox/{candidate_fingerprint}/skip",
    name="capability_skip",
)
def capability_skip(
    request: Request,
    candidate_fingerprint: str,
    role_id: Annotated[str, Form()],
    expected_skipped_sha256: Annotated[str, Form()],
) -> Response:
    try:
        message = _capabilities(request).skip(
            role_id,
            candidate_fingerprint,
            expected_skipped_sha256=expected_skipped_sha256,
        )
    except ApplicationError as exc:
        return _inbox_error(request, candidate_fingerprint, exc)
    return _redirect_to(_next_inbox_path(request), message, role_id=role_id)


@router.post(
    "/capabilities/skipped/{candidate_fingerprint}/restore",
    name="capability_restore",
)
def capability_restore(
    request: Request,
    candidate_fingerprint: str,
    role_id: Annotated[str, Form()],
    expected_skipped_sha256: Annotated[str, Form()],
) -> RedirectResponse:
    message = _capabilities(request).restore(
        role_id,
        candidate_fingerprint,
        expected_skipped_sha256=expected_skipped_sha256,
    )
    workspace = _capabilities(request).workspace(role_id)
    restored_pending = any(
        item.candidate_fingerprint == candidate_fingerprint
        for item in workspace.pending_candidates
    )
    path = (
        f"/capabilities/inbox/{candidate_fingerprint}"
        if restored_pending
        else "/capabilities"
    )
    return _redirect_to(path, message, role_id=role_id)


@router.get(
    "/capabilities/{capability_id}",
    response_class=HTMLResponse,
    name="capability_detail",
)
def capability_detail(request: Request, capability_id: str) -> HTMLResponse:
    return _render_capability_detail(request, capability_id)


def _render_capability_detail(
    request: Request,
    capability_id: str,
    *,
    error_message: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    role_id = _selected_role(request)
    if role_id is None:
        raise ApplicationError("validation", "open Capability", "请先创建 Role")
    view = _capabilities(request).detail(
        role_id,
        capability_id,
        reassign_expression=request.query_params.get("reassign_expression"),
        reassign_query=request.query_params.get("reassign_query"),
    )
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="capability_detail.html",
        context={
            "page_title": view.capability.name,
            "active_nav": "capabilities",
            "navigation": NAV_ITEMS,
            "view": view,
            "notice": _notice(request),
            "notice_level": request.query_params.get("level", "success"),
            "error_message": error_message,
        },
        status_code=status_code,
    )


@router.post(
    "/capabilities/{capability_id}/knowledge",
    name="capability_knowledge_prepare",
)
def capability_knowledge_prepare(
    request: Request,
    capability_id: str,
) -> Response:
    role_id = _selected_role(request)
    if role_id is None:
        raise ApplicationError(
            "validation", "save Capability Knowledge", "请先创建 Role"
        )
    try:
        message = _capabilities(request).prepare_knowledge_research(
            role_id, capability_id
        )
    except ApplicationError as exc:
        return _render_capability_detail(
            request,
            capability_id,
            error_message=exc.public_message,
            status_code=409 if exc.category == "conflict" else 422,
        )
    return _redirect_to(f"/capabilities/{capability_id}", message)


@router.post("/capabilities/knowledge/batch/selected", name="knowledge_batch_selected")
async def knowledge_batch_selected(request: Request) -> Response:
    form = await request.form()
    role_id = str(form.get("role_id") or "")
    try:
        role_id = _current_learning_role(request, role_id)
        message = _capabilities(request).prepare_knowledge_batch(
            role_id, [str(value) for value in form.getlist("capability_id")]
        )
    except ApplicationError as exc:
        return _render_capabilities(
            request,
            error_message=exc.public_message,
            status_code=409 if exc.category == "conflict" else 422,
        )
    return _redirect_to(
        "/capabilities?selection_cleared=knowledge#knowledge-research",
        message,
        role_id=role_id,
    )


@router.post("/capabilities/knowledge/batch/all", name="knowledge_batch_all")
def knowledge_batch_all(
    request: Request,
    role_id: Annotated[str, Form()],
) -> Response:
    try:
        role_id = _current_learning_role(request, role_id)
        message = _capabilities(request).prepare_knowledge_batch(role_id)
    except ApplicationError as exc:
        return _render_capabilities(
            request,
            error_message=exc.public_message,
            status_code=409 if exc.category == "conflict" else 422,
        )
    return _redirect_to(
        "/capabilities?selection_cleared=knowledge#knowledge-research",
        message,
        role_id=role_id,
    )


@router.post("/capabilities/knowledge/batch/retry", name="knowledge_batch_retry")
def knowledge_batch_retry(
    request: Request, role_id: Annotated[str, Form()]
) -> Response:
    try:
        role_id = _current_learning_role(request, role_id)
        message = _capabilities(request).retry_failed_knowledge_batch(role_id)
    except ApplicationError as exc:
        return _render_capabilities(
            request,
            error_message=exc.public_message,
            status_code=409 if exc.category == "conflict" else 422,
        )
    return _redirect_to(
        "/capabilities#knowledge-research",
        message,
        role_id=role_id,
    )


@router.post("/capabilities/{capability_id}/rename", name="capability_rename")
def capability_rename(
    request: Request,
    capability_id: str,
    role_id: Annotated[str, Form()],
    name: Annotated[str, Form()],
    expected_catalog_sha256: Annotated[str, Form()],
) -> Response:
    try:
        role_id = _current_learning_role(request, role_id)
        message = _capabilities(request).rename(
            role_id,
            capability_id,
            name,
            expected_catalog_sha256=expected_catalog_sha256,
        )
    except ApplicationError as exc:
        return _render_capability_detail(
            request, capability_id, error_message=exc.public_message,
            status_code=409 if exc.category == "conflict" else 422,
        )
    return _redirect_to(f"/capabilities/{capability_id}", message)


@router.post("/capabilities/{capability_id}/mappings/unmap", name="mapping_unmap")
def mapping_unmap(
    request: Request,
    capability_id: str,
    role_id: Annotated[str, Form()],
    source_expression: Annotated[str, Form()],
    expected_catalog_sha256: Annotated[str, Form()],
) -> Response:
    try:
        role_id = _current_learning_role(request, role_id)
        message = _capabilities(request).unmap(
            role_id, capability_id, source_expression,
            expected_catalog_sha256=expected_catalog_sha256,
        )
    except ApplicationError as exc:
        return _render_capability_detail(
            request, capability_id, error_message=exc.public_message,
            status_code=409 if exc.category == "conflict" else 422,
        )
    return _redirect_to(f"/capabilities/{capability_id}", message)


@router.post("/capabilities/{capability_id}/mappings/reassign", name="mapping_reassign")
def mapping_reassign(
    request: Request,
    capability_id: str,
    role_id: Annotated[str, Form()],
    source_expression: Annotated[str, Form()],
    capability_name: Annotated[str, Form()],
    expected_catalog_sha256: Annotated[str, Form()],
) -> Response:
    try:
        role_id = _current_learning_role(request, role_id)
        message = _capabilities(request).reassign(
            role_id, capability_id, source_expression, capability_name,
            expected_catalog_sha256=expected_catalog_sha256,
        )
    except ApplicationError as exc:
        return _render_capability_detail(
            request, capability_id, error_message=exc.public_message,
            status_code=409 if exc.category == "conflict" else 422,
        )
    return _redirect_to(f"/capabilities/{capability_id}", message)


@router.post("/capabilities/{capability_id}/knowledge/remove", name="knowledge_remove")
def knowledge_remove(
    request: Request,
    capability_id: str,
    role_id: Annotated[str, Form()],
    expected_knowledge_sha256: Annotated[str, Form()],
) -> Response:
    try:
        role_id = _current_learning_role(request, role_id)
        message = _capabilities(request).remove_knowledge(
            role_id, capability_id,
            expected_knowledge_sha256=expected_knowledge_sha256,
        )
    except ApplicationError as exc:
        return _render_capability_detail(
            request, capability_id, error_message=exc.public_message,
            status_code=409 if exc.category == "conflict" else 422,
        )
    return _redirect_to(f"/capabilities/{capability_id}#knowledge", message)


@router.post("/capabilities/{capability_id}/delete", name="capability_delete")
def capability_delete(
    request: Request,
    capability_id: str,
    role_id: Annotated[str, Form()],
    expected_catalog_sha256: Annotated[str, Form()],
    expected_personal_states_sha256: Annotated[str, Form()],
    expected_practices_sha256: Annotated[str, Form()],
    expected_knowledge_sha256: Annotated[str, Form()] = "",
) -> Response:
    try:
        role_id = _current_learning_role(request, role_id)
        message = _capabilities(request).delete_capability(
            role_id, capability_id,
            expected_catalog_sha256=expected_catalog_sha256,
            expected_personal_states_sha256=expected_personal_states_sha256,
            expected_practices_sha256=expected_practices_sha256,
            expected_knowledge_sha256=_optional(expected_knowledge_sha256),
        )
    except ApplicationError as exc:
        return _render_capability_detail(
            request, capability_id, error_message=exc.public_message,
            status_code=409 if exc.category == "conflict" else 422,
        )
    return _redirect_to("/capabilities#all-capabilities", message)
