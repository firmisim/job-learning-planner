from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_application_capability_analysis_batch import _pending
from tests.test_application_capabilities import _role_with_signals
from tests.test_application_knowledge_batch import _mapped_missing
from tests.test_application_roadmaps import _ready_role, _result
from ui.app import create_app
from ui.i18n import (
    CatalogError,
    LOCALE_COOKIE,
    MessageCatalog,
    MissingTranslationError,
    localize_system_message,
    resolve_locale,
)


CATALOG_ROOT = Path(__file__).parents[1] / "ui" / "i18n"


@pytest.mark.parametrize(
    ("cookie", "header", "expected"),
    [
        (None, "zh-CN", "zh-CN"),
        (None, "zh-TW", "zh-CN"),
        (None, "en", "en"),
        (None, "en-US", "en"),
        (None, "fr", "zh-CN"),
        (None, None, "zh-CN"),
        (None, "zh;q=0.9,en;q=0.8", "zh-CN"),
        ("en", "zh-CN", "en"),
        ("zh-CN", "en", "zh-CN"),
        ("invalid", "en", "en"),
        ("invalid", ";;;", "zh-CN"),
    ],
)
def test_locale_resolution_cookie_then_browser_then_fallback(
    cookie: str | None, header: str | None, expected: str
) -> None:
    assert resolve_locale(cookie, header) == expected


def _write_catalogs(
    root: Path, zh_cn: object, en: object
) -> None:
    root.mkdir()
    (root / "zh-CN.json").write_text(
        json.dumps(zh_cn, ensure_ascii=False), encoding="utf-8"
    )
    (root / "en.json").write_text(
        json.dumps(en, ensure_ascii=False), encoding="utf-8"
    )


def test_catalogs_have_string_values_equal_keys_and_strict_lookup(
    tmp_path: Path,
) -> None:
    catalog = MessageCatalog.load(CATALOG_ROOT)
    assert set(catalog.messages["zh-CN"]) == set(catalog.messages["en"])
    assert catalog.translate("en", "locale.switch_title", language="中文") == (
        "Switch interface language to 中文"
    )
    with pytest.raises(MissingTranslationError, match="missing UI translation"):
        catalog.translate("en", "missing.key")
    with pytest.raises(CatalogError, match="parameters"):
        catalog.translate("en", "locale.switch_title")

    mismatched = tmp_path / "mismatched"
    _write_catalogs(mismatched, {"common.save": "保存"}, {"common.cancel": "Cancel"})
    with pytest.raises(CatalogError, match="key mismatch"):
        MessageCatalog.load(mismatched)

    invalid = tmp_path / "invalid"
    _write_catalogs(invalid, {"common.save": 3}, {"common.save": "Save"})
    with pytest.raises(CatalogError, match="must be strings"):
        MessageCatalog.load(invalid)


def test_all_static_template_keys_exist_and_system_messages_localize() -> None:
    catalog = MessageCatalog.load(CATALOG_ROOT)
    keys: set[str] = set()
    template_root = Path(__file__).parents[1] / "ui" / "templates"
    for template in template_root.rglob("*.html"):
        keys.update(
            re.findall(r"t\(['\"]([^'\"]+)", template.read_text(encoding="utf-8"))
        )
    static_keys = {key for key in keys if not key.endswith(".")}
    assert static_keys <= set(catalog.messages["en"])
    assert localize_system_message(catalog, "en", "当前水平已保存") == (
        "Current level saved"
    )
    assert localize_system_message(catalog, "en", "Role “中文角色” 已创建") == (
        "Role “中文角色” created"
    )
    assert localize_system_message(catalog, "zh-CN", "Role “English Role” 已创建") == (
        "Role“English Role”已创建"
    )
    assert localize_system_message(catalog, "en", "safe public reason") == (
        "safe public reason"
    )


@pytest.mark.parametrize(
    ("locale", "expected"),
    [
        ("zh-CN", "已切换当前 Role"),
        ("en", "Current Role switched"),
    ],
)
def test_role_switch_success_keeps_a_specific_localized_notice(
    tmp_path: Path, locale: str, expected: str
) -> None:
    client = TestClient(
        create_app(tmp_path / locale / "state"),
        headers={"Accept-Language": locale},
    )
    market = client.app.state.market
    role_id, _ = market.create_role("Target Role", market.view().roles_sha256)

    response = client.post(
        "/roles/switch",
        data={"role_name": "Target Role", "return_to": "/market"},
    )

    assert response.status_code == 200
    assert expected in response.text
    assert client.cookies.get("job_learning_current_role") == role_id
    assert "此处不展示的技术详情" not in response.text
    assert "technical detail that is not shown here" not in response.text


def test_validation_error_shows_reason_and_explains_why_change_stopped(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(tmp_path / "state"), headers={"Accept-Language": "zh-CN"}
    )

    response = client.post("/locale", data={"locale": "unsupported"})

    assert response.status_code == 422
    assert "不支持所选界面语言" in response.text
    assert "系统没有执行这项更改" in response.text
    assert "请检查操作" not in response.text
    assert "此处不展示的技术详情" not in response.text


@pytest.mark.parametrize(
    ("flow", "locale", "summary", "skill"),
    [
        ("knowledge", "zh-CN", "已准备 5 个能力，共 2 批", "capability-knowledge-research"),
        ("knowledge", "en", "Prepared Capabilities: 5; batches: 2", "capability-knowledge-research"),
        ("analysis", "zh-CN", "已准备 2 个候选项，共 1 批", "capability-analysis"),
        ("analysis", "en", "Prepared candidates: 2; batches: 1", "capability-analysis"),
    ],
)
def test_application_batch_messages_localize_with_exact_handoff_guidance(
    tmp_path: Path,
    flow: str,
    locale: str,
    summary: str,
    skill: str,
) -> None:
    catalog = MessageCatalog.load(CATALOG_ROOT)
    if flow == "knowledge":
        operations, role_id, ids = _mapped_missing(
            tmp_path / flow / locale, "Knowledge Localize", 5
        )
        message = operations.prepare_knowledge_batch(role_id, ids)
        next_message = operations.prepare_next_knowledge_batch_request()
    else:
        operations, role_id, fingerprints = _pending(
            tmp_path / flow / locale, "Analysis Localize", 2
        )
        message = operations.prepare_capability_analysis_batch(
            role_id, fingerprints
        )
        next_message = operations.prepare_next_capability_analysis_batch_request()

    localized = localize_system_message(catalog, locale, message)
    localized_next = localize_system_message(catalog, locale, next_message)
    assert localized is not None
    assert localized_next is not None
    assert summary in localized
    assert skill in localized
    assert "technical detail that is not shown here" not in localized
    assert "此处不展示的技术详情" not in localized
    assert skill in localized_next
    assert "technical detail that is not shown here" not in localized_next
    assert "此处不展示的技术详情" not in localized_next
    assert ("第 1 /" in localized_next) if locale == "zh-CN" else (
        "Batch 1 of" in localized_next
    )


def _js_messages(html: str) -> dict[str, str]:
    match = re.search(
        r'<script id="ui-messages" type="application/json">(.*?)</script>', html
    )
    assert match is not None
    value = json.loads(match.group(1))
    assert isinstance(value, dict)
    return value


def test_jinja_uses_locale_for_html_catalog_js_and_representative_ui(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(tmp_path / "state"), raise_server_exceptions=False)
    role_id, _ = client.app.state.market.create_role(
        "Representative Role", client.app.state.market.view().roles_sha256
    )
    client.cookies.set(
        "job_learning_current_role", role_id, domain="testserver.local", path="/"
    )

    zh_page = client.get("/market", headers={"Accept-Language": "zh-CN"})
    assert zh_page.status_code == 200
    assert '<html lang="zh-CN">' in zh_page.text
    assert "<title>市场 · Job Learning Planner</title>" in zh_page.text
    assert ">市场</span>" in zh_page.text
    assert 'aria-label="主导航"' in zh_page.text
    assert 'placeholder="例如：后端工程师"' in zh_page.text
    assert ">添加 JD</button>" in zh_page.text
    assert "暂无 JD" in zh_page.text
    assert _js_messages(zh_page.text)["common.working"] == "处理中…"

    en_page = client.get("/market", headers={"Accept-Language": "en"})
    assert en_page.status_code == 200
    assert '<html lang="en">' in en_page.text
    assert "<title>Market · Job Learning Planner</title>" in en_page.text
    assert ">Market</span>" in en_page.text
    assert 'aria-label="Primary navigation"' in en_page.text
    assert 'placeholder="For example: Backend Engineer"' in en_page.text
    assert ">Add JD</button>" in en_page.text
    assert "No JDs yet" in en_page.text
    assert _js_messages(en_page.text)["common.working"] == "Working…"

    javascript = (Path(__file__).parents[1] / "ui" / "static" / "app.js").read_text(
        encoding="utf-8"
    )
    assert 'uiMessage("common.working")' in javascript
    assert '|| "Working…"' not in javascript


@pytest.mark.parametrize(
    ("next_path", "expected_location"),
    [
        ("/market?jd_page=2", "/market?jd_page=2"),
        ("https://example.com/escape", "/market"),
        ("//example.com/escape", "/market"),
        ("http://[", "/market"),
        ("/market\\escape", "/market"),
    ],
)
def test_locale_switch_sets_only_valid_cookie_and_uses_safe_redirect(
    tmp_path: Path, next_path: str, expected_location: str
) -> None:
    client = TestClient(create_app(tmp_path / "state"), raise_server_exceptions=False)
    response = client.post(
        "/locale",
        data={"locale": "en", "next": next_path},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == expected_location
    assert response.cookies[LOCALE_COOKIE] == "en"
    set_cookie = response.headers["set-cookie"].lower()
    assert "path=/" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert '<html lang="en">' in client.get("/market").text

    invalid = client.post(
        "/locale",
        data={"locale": "fr", "next": "/settings"},
        follow_redirects=False,
    )
    assert invalid.status_code == 422
    assert LOCALE_COOKIE not in invalid.cookies
    assert client.cookies.get(LOCALE_COOKIE) == "en"


def _state_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_locale_role_and_mixed_language_content_are_independent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    roadmaps, _, english_role_id, _ = _ready_role(root)
    generation_input = roadmaps.generation_input(english_role_id)
    roadmaps.save_result(
        english_role_id,
        _result(str(generation_input["input_fingerprint"]), "# English Roadmap"),
    )
    chinese_role_id = _role_with_signals(
        roadmaps.market,
        "中文角色",
        ["Redis缓存设计"],
    )
    client = TestClient(create_app(root), raise_server_exceptions=False)
    client.cookies.set(
        "job_learning_current_role",
        chinese_role_id,
        domain="testserver.local",
        path="/",
    )
    before = _state_snapshot(root)

    switched_locale = client.post(
        "/locale",
        data={"locale": "en", "next": "/market"},
        follow_redirects=False,
    )
    assert switched_locale.status_code == 303
    assert client.cookies.get("job_learning_current_role") == chinese_role_id
    english_ui = client.get("/market")
    assert '<html lang="en">' in english_ui.text
    assert ">Market</span>" in english_ui.text
    assert "中文角色 JD" in english_ui.text
    assert "Redis缓存设计" in english_ui.text

    switched_role = client.post(
        "/roles/switch",
        data={"role_name": "API Engineering", "return_to": "/market"},
        follow_redirects=False,
    )
    assert switched_role.status_code == 303
    assert client.cookies.get(LOCALE_COOKIE) == "en"
    english_role_page = client.get(switched_role.headers["location"])
    assert '<html lang="en">' in english_role_page.text
    assert "API Engineering JD" in english_role_page.text
    assert "Current Role switched" in english_role_page.text
    assert "technical detail that is not shown here" not in english_role_page.text

    client.post(
        "/locale",
        data={"locale": "zh-CN", "next": "/market"},
        follow_redirects=False,
    )
    chinese_ui = client.get("/market")
    assert '<html lang="zh-CN">' in chinese_ui.text
    assert ">市场</span>" in chinese_ui.text
    assert "API Engineering JD" in chinese_ui.text
    assert client.cookies.get("job_learning_current_role") == english_role_id
    assert _state_snapshot(root) == before


@pytest.mark.parametrize("locale", ["zh-CN", "en"])
def test_core_surfaces_render_with_the_same_business_state(
    tmp_path: Path, locale: str
) -> None:
    root = tmp_path / locale / "state"
    roadmaps, _, role_id, capability_id = _ready_role(root)
    generation_input = roadmaps.generation_input(role_id)
    roadmaps.save_result(
        role_id,
        _result(str(generation_input["input_fingerprint"]), "# 原样 Roadmap content"),
    )
    roadmap_id = str(roadmaps.storage.list_roadmaps(roadmaps._uuid(role_id, "role_id"))[0].roadmap_id)
    client = TestClient(create_app(root), raise_server_exceptions=False)
    client.cookies.set(LOCALE_COOKIE, locale)
    client.cookies.set("job_learning_current_role", role_id)

    for path in (
        "/market",
        "/capabilities",
        f"/capabilities/{capability_id}",
        "/learning",
        f"/learning/capabilities/{capability_id}",
        "/roadmaps",
        f"/roadmaps/{roadmap_id}",
        "/settings",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert f'<html lang="{locale}">' in response.text
    assert "原样 Roadmap content" in client.get(f"/roadmaps/{roadmap_id}").text
