from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook

from scripts.apply_semantic_handoff import apply
from ui.app import create_app


def _create_role(client: TestClient, name: str) -> str:
    view = client.app.state.market.view()
    response = client.post("/settings/roles", data={"name": name, "expected_sha256": view.roles_sha256}, follow_redirects=False)
    assert response.status_code == 303
    return response.cookies["job_learning_current_role"]


def _workbook(title: str, text: str) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["job_title", "jd_text"])
    sheet.append([title, text])
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_role_create_switch_rename_delete_ui_and_role_scoping(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "state"), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    assert "Create your first Role" in client.get("/market").text
    role_a = _create_role(client, "AI 应用开发")
    role_b = _create_role(client, "Java 后端")

    view_b = client.app.state.market.view(role_b)
    client.post("/market/jobs", data={"role_id": role_b, "title": "Java JD", "company": "", "source_url": "", "jd_text": "Spring Boot", "expected_sha256": view_b.jds_sha256})
    switched = client.post("/roles/switch", data={"role_name": "AI 应用开发"}, follow_redirects=False)
    assert switched.status_code == 303
    switch_notice = client.get(switched.headers["location"])
    assert "Current Role switched" in switch_notice.text
    assert "technical detail that is not shown here" not in switch_notice.text
    client.cookies.set("job_learning_current_role", role_a)
    page_a = client.get("/market")
    assert "AI 应用开发" in page_a.text
    assert "Java JD" not in page_a.text
    assert 'action="/settings/roles"' not in page_a.text
    settings = client.get("/settings")
    assert 'action="/settings/roles"' in settings.text
    assert 'action="/settings/roles/rename"' in settings.text
    assert 'action="/settings/roles/delete"' in settings.text
    assert 'action="/roles/switch"' in settings.text

    renamed = client.post("/settings/roles/rename", data={"role_id": role_a, "name": "AI 产品开发", "expected_sha256": client.app.state.market.view(role_a).roles_sha256}, follow_redirects=False)
    assert renamed.status_code == 303
    deleted = client.post("/settings/roles/delete", data={"role_id": role_a, "confirmation": "AI 产品开发", "expected_sha256": client.app.state.market.view(role_a).roles_sha256}, follow_redirects=False)
    assert deleted.status_code == 303
    assert client.app.state.market.resolve_role(role_a) is not None
    assert str(client.app.state.market.resolve_role(role_a)) == role_b


def test_jd_add_import_replace_bulk_delete_and_analysis_handoff_ui(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "state"), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    role_id = _create_role(client, "Backend")
    view = client.app.state.market.view(role_id)
    added = client.post("/market/jobs", data={"role_id": role_id, "title": "Backend JD", "company": "Example", "source_url": "", "jd_text": "Spring Boot 或 FastAPI", "expected_sha256": view.jds_sha256}, follow_redirects=False)
    assert added.status_code == 303
    page = client.get("/market")
    assert "Backend JD" in page.text
    assert "1 JD waiting for analysis" in page.text
    assert "Prepare JD Analysis" in page.text
    assert "Input and output contract" not in page.text
    assert "result JSON" not in page.text
    prepared = client.post(
        "/market/analysis",
        data={"role_id": role_id},
        follow_redirects=False,
    )
    assert prepared.status_code == 303
    prepared_page = client.get("/market")
    assert "JD Analysis request is prepared" in prepared_page.text
    assert "Analysis has not run yet" in prepared_page.text
    assert "jd-analysis" in prepared_page.text
    assert "return to Market" in prepared_page.text
    handoffs = client.app.state.market.handoffs
    request = handoffs.load_request("jd-analysis")
    analysis_input = request["input"]
    assert isinstance(analysis_input, dict)
    assert analysis_input["jobs"][0]["jd_text"] == "Spring Boot 或 FastAPI"
    analysis_result = {
        "schema_version": "1.0",
        "role_id": role_id,
        "analyses": [
            {
                "job_id": analysis_input["jobs"][0]["job_id"],
                "role_id": role_id,
                "source_fingerprint": analysis_input["jobs"][0]["source_fingerprint"],
                "signals": [
                    {"source_expression": "Spring Boot 或 FastAPI", "atomic_expression": name, "evidence": "Spring Boot 或 FastAPI"}
                    for name in ("Spring Boot", "FastAPI")
                ],
            }
        ],
    }
    handoffs.draft_path("jd-analysis").write_text(
        json.dumps(analysis_result), encoding="utf-8"
    )
    apply("jd-analysis", tmp_path / "state")
    analyzed_page = client.get("/market")
    assert "Spring Boot" in analyzed_page.text
    assert "FastAPI" in analyzed_page.text
    assert "JD Analysis request is prepared" not in analyzed_page.text

    replaced = client.post(
        "/market/import",
        data={"role_id": role_id, "mode": "replace", "expected_sha256": client.app.state.market.view(role_id).jds_sha256},
        files={"workbook": ("jobs.xlsx", _workbook("Replacement", "CI/CD 与 TCP/IP"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        follow_redirects=False,
    )
    assert replaced.status_code == 303
    assert "Replacement" in client.get("/market").text
    assert "Backend JD" not in client.get("/market").text
    replaced_view = client.app.state.market.view(role_id)
    assert replaced_view.current_analysis_count == 0
    assert replaced_view.pending_analysis_count == 1

    current = replaced_view
    deleted = client.post("/market/jobs/delete", data={"role_id": role_id, "job_id": current.jobs[0].job_id, "expected_sha256": current.jds_sha256}, follow_redirects=False)
    assert deleted.status_code == 303
    assert client.app.state.market.view(role_id).jobs == ()


def test_ui_rejects_invalid_workbook_and_forged_role_without_traceback(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "state"), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    role_id = _create_role(client, "Backend")
    response = client.post(
        "/market/import",
        data={"role_id": role_id, "mode": "append", "expected_sha256": client.app.state.market.view(role_id).jds_sha256},
        files={"workbook": ("jobs.xlsx", b"invalid", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 422
    assert "Traceback" not in response.text
    forged = client.post("/roles/switch", data={"role_name": "Missing Role"})
    assert forged.status_code == 422
    assert "Traceback" not in forged.text
