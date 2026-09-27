from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient

from tests.test_application_capabilities import _role_with_signals
from tests.test_application_roadmaps import _ready_role, _result
from tests.test_ui_localization import _state_snapshot
from ui.app import create_app
from ui.i18n import LOCALE_COOKIE


@pytest.mark.parametrize("locale", ["zh-CN", "en"])
def test_brand_assets_are_pure_local_vectors_and_locale_independent(
    tmp_path: Path, locale: str,
) -> None:
    root = tmp_path / "state"
    client = TestClient(create_app(root))
    client.cookies.set(LOCALE_COOKIE, locale)
    before = _state_snapshot(root)
    page = client.get("/market")
    assert page.status_code == 200
    assert 'type="image/svg+xml"' in page.text
    assert '/static/brand/favicon.svg' in page.text
    assert '/static/brand/logo-mark.svg' in page.text
    assert 'class="brand-mark" aria-hidden="true"' in page.text
    assert 'width="32" height="32" alt=""' in page.text
    assert '>JL<' not in page.text and 'href="data:,"' not in page.text
    assets = []
    for name in ("logo-mark.svg", "favicon.svg"):
        response = client.get(f"/static/brand/{name}")
        assert response.status_code == 200
        assert "image/svg+xml" in response.headers["content-type"]
        svg = ElementTree.fromstring(response.content)
        assert svg.attrib["viewBox"] == "0 0 32 32"
        allowed = {"svg", "path", "circle"}
        for node in svg.iter():
            assert node.tag.rsplit("}", 1)[-1] in allowed
            assert not (node.text or "").strip()
            for key, value in node.attrib.items():
                assert not key.lower().startswith("on")
                assert not any(token in value.lower() for token in (
                    "url(", "data:", "http:", "https:", "font",
                ))
        assert len(list(svg)) == 4
        assets.append(response.content)
    assert assets[0] == assets[1]
    assert _state_snapshot(root) == before


@pytest.mark.parametrize("locale", ["zh-CN", "en"])
def test_release_workflows_and_locale_switch_preserve_business_boundaries(
    tmp_path: Path, locale: str,
) -> None:
    root = tmp_path / "state"
    roadmaps, learning, role_id, capability_id = _ready_role(root)
    fingerprint = str(roadmaps.generation_input(role_id)["input_fingerprint"])
    content = "# 中文路线 / English content\n\n- 保持原样，不随 UI 改写"
    roadmaps.save_result(role_id, _result(fingerprint, content))
    roadmap_id = roadmaps.view(role_id).history[0].roadmap_id
    other = _role_with_signals(roadmaps.market, "中文角色", ["Redis缓存设计", "API testing", "Queue design"])
    client = TestClient(create_app(root))
    client.cookies.set(LOCALE_COOKIE, locale, domain="testserver.local", path="/")
    client.cookies.set("job_learning_current_role", role_id, domain="testserver.local", path="/")

    def post(path: str, data: dict[str, object]) -> None:
        response = client.post(path, data=data, follow_redirects=False)
        assert response.status_code == 303, (path, response.text)
        assert client.cookies.get(LOCALE_COOKIE) == locale
        returned = client.get(response.headers["location"])
        assert returned.status_code == 200
        assert f'<html lang="{locale}">' in returned.text

    post("/roadmaps", {"role_id": role_id})
    assert "job-learning-roadmap" in client.get("/roadmaps").text
    assert client.get(f"/roadmaps/{roadmap_id}/export").text == content
    detail = client.get(f"/roadmaps/{roadmap_id}").text
    assert 'data-confirm=' in detail and "中文路线" in detail
    post(f"/learning/capabilities/{capability_id}/level", {
        "role_id": role_id, "current_level": "2",
        "expected_sha256": learning.view(role_id).personal_states_sha256,
    })
    post(f"/learning/capabilities/{capability_id}/practices", {
        "role_id": role_id, "description": "完成 English API practice",
        "expected_sha256": learning.view(role_id).practices_sha256,
    })
    post("/roles/switch", {"role_name": "中文角色", "return_to": "/capabilities"})
    post("/capabilities/analysis/batch/all", {"role_id": other})
    assert "capability-analysis" in client.get("/capabilities").text
    caps = client.app.state.capabilities
    for action in ("add", "merge", "skip"):
        workspace = caps.workspace(other)
        candidate = workspace.pending_candidates[0]
        path = f"/capabilities/inbox/{candidate.candidate_fingerprint}"
        assert client.get(path + "?merge_query=FastAPI").status_code == 200
        data = {"role_id": other}
        if action == "skip":
            data["expected_skipped_sha256"] = workspace.skipped_sha256
        else:
            data["expected_catalog_sha256"] = workspace.catalog_sha256
            data["canonical_name" if action == "add" else "capability_name"] = (
                "中文新增能力" if action == "add" else "FastAPI"
            )
        post(path + "/" + action, data)
    post("/capabilities/knowledge/batch/all", {"role_id": other})
    assert "capability-knowledge-research" in client.get("/capabilities").text
    post("/market/analysis", {"role_id": other})
    assert "jd-analysis" in client.get("/market").text

    # All facts, derived input and execution manifests are stable under UI-only changes.
    before = _state_snapshot(root)
    input_before = roadmaps.generation_input(role_id)
    for selected in ("en", "zh-CN", locale):
        response = client.post("/locale", data={"locale": selected, "next": "/market"})
        assert response.status_code == 200
        assert client.cookies.get("job_learning_current_role") == other
        for path in ("/market", "/capabilities?pending_page=2", "/learning", "/roadmaps", "/settings"):
            assert f'<html lang="{selected}">' in client.get(path).text
        assert "中文角色" in client.get("/market").text
    assert _state_snapshot(root) == before
    assert roadmaps.generation_input(role_id) == input_before
    post("/roles/switch", {"role_name": "API Engineering", "return_to": "/roadmaps"})
    post(f"/roadmaps/{roadmap_id}/delete", {"role_id": role_id})
    assert not roadmaps.view(role_id).history


@pytest.mark.parametrize("locale", ["zh-CN", "en"])
def test_role_management_jd_validation_and_cookie_survive_posts(
    tmp_path: Path, locale: str,
) -> None:
    client = TestClient(create_app(tmp_path / "state"))
    client.cookies.set(LOCALE_COOKIE, locale)
    market = client.app.state.market
    created = client.post("/settings/roles", data={
        "name": "混合 Role", "expected_sha256": market.view().roles_sha256,
    }, follow_redirects=False)
    assert created.status_code == 303
    role = created.cookies["job_learning_current_role"]
    renamed = client.post("/settings/roles/rename", data={
        "role_id": role, "name": "English 角色",
        "expected_sha256": market.view().roles_sha256,
    }, follow_redirects=False)
    assert renamed.status_code == 303
    fields = {"role_id": role, "title": "中文 JD", "company": "",
              "source_url": "", "jd_text": "   ",
              "expected_sha256": market.view(role).jds_sha256}
    invalid = client.post("/market/jobs", data=fields)
    assert invalid.status_code == 422
    assert f'<html lang="{locale}">' in invalid.text
    fields["jd_text"] = "Implement reliable APIs，保持用户原文。"
    added = client.post("/market/jobs", data=fields, follow_redirects=False)
    assert added.status_code == 303
    page = client.get("/market")
    assert "中文 JD" in page.text
    assert f'<html lang="{locale}">' in page.text
    deleted = client.post("/settings/roles/delete", data={
        "role_id": role, "confirmation": "English 角色",
        "expected_sha256": market.view().roles_sha256,
    }, follow_redirects=False)
    assert deleted.status_code == 303
    assert client.cookies.get(LOCALE_COOKIE) == locale
    assert not market.view().roles
