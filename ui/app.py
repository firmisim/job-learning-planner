from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from application.capabilities import CapabilityOperations
from application.errors import ApplicationError
from application.learning import LearningOperations
from application.market import MarketOperations
from application.roadmaps import RoadmapOperations
from application.settings import SettingsOperations
from ui.i18n import MessageCatalog, localize_system_message, request_locale
from ui.routes.pages import NAV_ITEMS, ROLE_COOKIE, router


UI_ROOT = Path(__file__).resolve().parent
DEFAULT_STORAGE_ROOT = UI_ROOT.parent / "state"
LOGGER = logging.getLogger(__name__)


def _shell_context(request: Request) -> dict[str, object]:
    view = request.app.state.market.view(request.cookies.get(ROLE_COOKIE))
    locale = request_locale(request)
    catalog: MessageCatalog = request.app.state.ui_messages

    def t(key: str, **params: object) -> str:
        return catalog.translate(locale, key, **params)

    def localize(message: str | None) -> str | None:
        return localize_system_message(catalog, locale, message)

    query = request.url.query
    return {
        "shell_roles": view.roles,
        "shell_current_role": view.current_role,
        "shell_roles_sha256": view.roles_sha256,
        "locale": locale,
        "locale_return_to": request.url.path + (f"?{query}" if query else ""),
        "t": t,
        "localize": localize,
        "js_messages": {"common.working": t("common.working")},
    }


def create_app(storage_root: Path | None = None) -> FastAPI:
    resolved_root = (storage_root or DEFAULT_STORAGE_ROOT).resolve()
    app = FastAPI(
        title="Job Learning Planner",
        docs_url=None,
        redoc_url=None,
    )
    app.state.market = MarketOperations(resolved_root)
    app.state.capabilities = CapabilityOperations(resolved_root)
    app.state.learning = LearningOperations(resolved_root)
    app.state.roadmaps = RoadmapOperations(resolved_root)
    app.state.settings = SettingsOperations(resolved_root)
    app.state.ui_messages = MessageCatalog.load(UI_ROOT / "i18n")
    app.state.templates = Jinja2Templates(
        directory=UI_ROOT / "templates",
        context_processors=[_shell_context],
    )
    app.mount("/static", StaticFiles(directory=UI_ROOT / "static"), name="static")
    app.include_router(router)

    @app.exception_handler(ApplicationError)
    async def application_error_handler(
        request: Request, exc: ApplicationError
    ) -> HTMLResponse:
        status_code = (
            422
            if exc.category == "validation"
            else 409 if exc.category == "conflict" else 500
        )
        locale = request_locale(request)
        catalog: MessageCatalog = app.state.ui_messages
        return app.state.templates.TemplateResponse(
            request=request,
            name="error.html",
            context={
                "page_title": catalog.translate(locale, f"error.{exc.category}_title"),
                "active_nav": (
                    "settings"
                    if request.url.path.startswith("/settings")
                    else "roadmaps"
                    if request.url.path.startswith("/roadmaps")
                    else "learning"
                    if request.url.path.startswith("/learning")
                    else "capabilities"
                    if request.url.path.startswith("/capabilities")
                    else "market"
                ),
                "navigation": NAV_ITEMS,
                "error_category": exc.category,
                "error_message": exc.public_message,
                "error_guidance": catalog.translate(
                    locale, f"error.guidance.{exc.category}"
                ),
                "recovery_path": (
                    "/settings"
                    if request.url.path.startswith("/settings")
                    else "/roadmaps"
                    if request.url.path.startswith("/roadmaps")
                    else "/learning"
                    if request.url.path.startswith("/learning")
                    else "/capabilities"
                    if request.url.path.startswith("/capabilities")
                    else "/market"
                ),
            },
            status_code=status_code,
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(
        request: Request, exc: Exception
    ) -> HTMLResponse:
        LOGGER.exception(
            "Unhandled UI error during %s %s", request.method, request.url.path
        )
        return app.state.templates.TemplateResponse(
            request=request,
            name="error.html",
            context={
                "page_title": app.state.ui_messages.translate(
                    request_locale(request), "error.system_title"
                ),
                "active_nav": (
                    "settings"
                    if request.url.path.startswith("/settings")
                    else "roadmaps"
                    if request.url.path.startswith("/roadmaps")
                    else "learning"
                    if request.url.path.startswith("/learning")
                    else "capabilities"
                    if request.url.path.startswith("/capabilities")
                    else "market"
                ),
                "navigation": NAV_ITEMS,
                "error_category": "system",
                "error_operation": "load current page",
                "error_message": app.state.ui_messages.translate(
                    request_locale(request), "error.unexpected"
                ),
                "error_guidance": app.state.ui_messages.translate(
                    request_locale(request), "error.guidance.system"
                ),
                "recovery_path": (
                    "/settings"
                    if request.url.path.startswith("/settings")
                    else "/roadmaps"
                    if request.url.path.startswith("/roadmaps")
                    else "/learning"
                    if request.url.path.startswith("/learning")
                    else "/capabilities"
                    if request.url.path.startswith("/capabilities")
                    else "/market"
                ),
            },
            status_code=500,
        )

    return app
