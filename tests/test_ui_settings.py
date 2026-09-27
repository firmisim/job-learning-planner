from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_application_roadmaps import _ready_role
from ui.app import create_app


def test_settings_is_low_frequency_and_reset_requires_exact_preview(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    _ready_role(root)
    client = TestClient(create_app(root), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    page = client.get("/settings")
    assert page.status_code == 200
    assert "Manage Roles" in page.text
    assert "Local data is ready" in page.text
    assert "Reset all learning data" in page.text
    assert 'action="/settings/roles"' in page.text
    assert "Exact file" not in page.text
    preview = client.post("/settings/development-reset/preview")
    assert preview.status_code == 200
    view = client.app.state.settings.preview_reset()
    blocked = client.post(
        "/settings/development-reset/apply",
        data={
            "manifest_json": view.reset_manifest_json,
            "confirmation": "wrong",
            "risk_confirmation": "FULL DEVELOPMENT RESET",
        },
    )
    assert blocked.status_code == 422
    assert client.app.state.settings.storage.load_roles().roles

    # Use the exact one-time preview for the successful application.
    exact = client.app.state.settings.preview_reset()
    applied = client.post(
        "/settings/development-reset/apply",
        data={
            "manifest_json": exact.reset_manifest_json,
            "confirmation": exact.reset_id,
            "risk_confirmation": "FULL DEVELOPMENT RESET",
        },
        follow_redirects=False,
    )
    assert applied.status_code == 303
    assert client.app.state.settings.storage.load_roles().roles == []
    assert client.app.state.settings.storage.load_catalog().capabilities == []
    assert client.app.state.settings.storage.load_personal_states().states == []
    assert client.app.state.settings.storage.load_practices().practices == []
