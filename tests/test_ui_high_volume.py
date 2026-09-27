from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from shutil import which
import subprocess
import sys
from tempfile import TemporaryFile
from threading import Event, Thread
import time
from typing import BinaryIO
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
import pytest

from application.capabilities import CapabilityOperations
from application.market import MarketOperations
from schemas.core import RoadmapVersion
from scripts.apply_semantic_handoff import apply
from tests.test_application_capabilities import _role_with_signals
from tests.test_application_roadmaps import _ready_role
from ui.app import create_app
from ui.pagination import paginate


def _browser_executable() -> str:
    executable_names = (
        (
            "google-chrome",
            "google-chrome-stable",
            "chromium",
            "chromium-browser",
        )
        if sys.platform.startswith("linux")
        else ("chrome", "chromium", "chromium-browser", "msedge")
    )
    installed = next(
        (
            executable
            for name in executable_names
            if (executable := which(name))
        ),
        None,
    )
    if installed:
        return installed

    if sys.platform == "win32":
        for candidate in (
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
            Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        ):
            if candidate.is_file():
                return str(candidate)
    pytest.skip("A Chromium browser is required for the JavaScript submission test")


def _captured_browser_output(stream: BinaryIO) -> str:
    stream.flush()
    stream.seek(0)
    text = stream.read().decode("utf-8", errors="replace")
    if len(text) <= 16384:
        return text
    return f"{text[:8192]}\n...[output truncated]...\n{text[-8192:]}"


def _run_chromium_until_complete(
    *,
    profile: Path,
    target: str,
    timeout: int,
    completion: Event,
    requested_paths: list[str],
    semantic_state: Callable[[], object],
) -> None:
    executable = _browser_executable()
    command = [
        executable,
        "--headless",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-software-rasterizer",
        "--disable-dev-shm-usage",
        "--no-first-run",
        "--no-default-browser-check",
        f"--user-data-dir={profile}",
        "--dump-dom",
        target,
    ]
    failure: str | None = None
    returncode: int | None = None
    with TemporaryFile() as stdout_file, TemporaryFile() as stderr_file:
        process = subprocess.Popen(
            command,
            stdout=stdout_file,
            stderr=stderr_file,
        )
        deadline = time.monotonic() + timeout
        try:
            while not completion.is_set():
                returncode = process.poll()
                if returncode is not None:
                    failure = "Chromium exited before semantic completion"
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    failure = f"Semantic completion was not reached within {timeout}s"
                    break
                completion.wait(timeout=min(0.05, remaining))
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            returncode = process.returncode

        if failure is not None:
            stdout = _captured_browser_output(stdout_file)
            stderr = _captured_browser_output(stderr_file)
            pytest.fail(
                f"{failure}\n"
                f"browser_executable={executable!r}\n"
                f"returncode={returncode}\n"
                f"requested_paths={requested_paths!r}\n"
                f"semantic_state={semantic_state()!r}\n"
                f"stdout={stdout!r}\n"
                f"stderr={stderr!r}"
            )


def test_linux_browser_discovery_prefers_stable_chrome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovered = {
        "google-chrome": "/opt/google/chrome/google-chrome",
        "chromium": "/usr/bin/chromium",
    }
    requested: list[str] = []

    def fake_which(name: str) -> str | None:
        requested.append(name)
        return discovered.get(name)

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setitem(_browser_executable.__globals__, "which", fake_which)

    assert _browser_executable() == "/opt/google/chrome/google-chrome"
    assert requested == ["google-chrome"]


def test_linux_browser_discovery_falls_back_to_chromium(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[str] = []

    def fake_which(name: str) -> str | None:
        requested.append(name)
        return "/usr/bin/chromium" if name == "chromium" else None

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setitem(_browser_executable.__globals__, "which", fake_which)

    assert _browser_executable() == "/usr/bin/chromium"
    assert requested == ["google-chrome", "google-chrome-stable", "chromium"]


def test_global_submit_handler_preserves_clicked_pagination_value(
    tmp_path: Path,
) -> None:
    app_script = (Path(__file__).parents[1] / "ui" / "static" / "app.js").read_text(
        encoding="utf-8"
    )
    ui_messages = json.dumps({"common.working": "Working..."})
    submitted_paths: list[str] = []
    requested_paths: list[str] = []
    completion = Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requested_paths.append(f"GET {self.path}")
            parsed = urlsplit(self.path)
            if parsed.path == "/submitted":
                submitted_paths.append(self.path)
                completion.set()
                body = "<!doctype html><title>Submitted</title><p>Submitted</p>"
            else:
                body = f"""<!doctype html>
<title>Pagination submission</title>
<form method="get" action="/submitted#market-signals">
  <button type="submit" name="signal_page" value="2">Next</button>
</form>
<script id="ui-messages" type="application/json">{ui_messages}</script>
<script>{app_script}</script>
<script>document.querySelector("button").click();</script>
"""
            encoded = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _run_chromium_until_complete(
            profile=tmp_path / "browser-profile",
            target=f"http://127.0.0.1:{server.server_port}/",
            timeout=20,
            completion=completion,
            requested_paths=requested_paths,
            semantic_state=lambda: {"submitted_paths": tuple(submitted_paths)},
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert submitted_paths
    assert parse_qs(urlsplit(submitted_paths[-1]).query) == {"signal_page": ["2"]}


def test_page_slice_filters_boundaries_and_clamps_invalid_pages() -> None:
    items = tuple(f"Item {index:02d}" for index in range(23))
    first = paginate(items, query="", page="invalid", searchable_text=str)
    second = paginate(items, query=None, page=2, searchable_text=str)
    last = paginate(items, query=None, page=999, searchable_text=str)
    filtered = paginate(items, query="  item 12 ", page=-4, searchable_text=str)

    assert first.page == 1 and first.items == items[:10]
    assert second.items == items[10:20]
    assert last.page == 3 and last.items == items[20:]
    assert not set(first.items) & set(second.items)
    assert filtered.query == "item 12"
    assert filtered.items == ("Item 12",)


def test_market_search_and_pagination_stay_inside_current_role(tmp_path: Path) -> None:
    root = tmp_path / "state"
    market = MarketOperations(root)
    role_id = _role_with_signals(
        market, "Scale Role", [f"Signal {index:02d}" for index in range(15)]
    )
    for index in range(11):
        view = market.view(role_id)
        market.add_job(
            role_id,
            title=f"Job {index:02d}",
            company="Example",
            jd_text=(
                "unique needle content" if index == 10 else f"Description {index:02d}"
            ),
            source_url=None,
            expected_sha256=view.jds_sha256 or "",
        )
    _role_with_signals(market, "Other Role", ["ForeignSecretSignal"])

    client = TestClient(create_app(root), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    client.cookies.set("job_learning_current_role", role_id)
    job_page_two = client.get("/market?jd_page=2#jd-list")
    assert job_page_two.status_code == 200
    assert "Job 10" in job_page_two.text
    assert "Job 00" not in job_page_two.text
    assert "Page 2 of 2" in job_page_two.text

    job_search = client.get("/market?jd_query=unique+needle#jd-list")
    jd_section = job_search.text.split('id="jd-list"', 1)[1].split(
        'id="analysis"', 1
    )[0]
    assert "Job 10" in jd_section
    assert "Scale Role JD" not in jd_section
    empty_search = client.get("/market?jd_query=ForeignSecretSignal#jd-list")
    assert "No matching JDs" in empty_search.text

    signal_page_two = client.get("/market?signal_page=2#market-signals")
    signal_section = signal_page_two.text.split('id="market-signals"', 1)[1]
    assert "Signal 14" in signal_section
    assert "Signal 00" not in signal_section
    signal_search = client.get("/market?signal_query=Signal+14#market-signals")
    search_section = signal_search.text.split('id="market-signals"', 1)[1]
    assert "Signal 14" in search_section
    assert "Signal 13" not in search_section
    foreign_search = client.get(
        "/market?signal_query=ForeignSecretSignal#market-signals"
    )
    assert "No matching signals" in foreign_search.text
    assert "Manual Input" in signal_search.text
    assert "Excel Import" in signal_search.text
    assert "input-task-grid" in signal_search.text


def test_capability_lists_search_page_restore_and_preserve_role_scope(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    market = MarketOperations(root)
    expressions = [f"Signal {index:02d}" for index in range(36)]
    role_id = _role_with_signals(market, "Capability Scale", expressions)
    operations = CapabilityOperations(root)

    for index in range(12):
        capability = operations.storage.create_capability(f"Mapped {index:02d}")
        operations.storage.add_source_mapping(
            expressions[index], capability.capability_id
        )
    for index in range(12, 24):
        workspace = operations.workspace(role_id)
        candidate = next(
            item
            for item in workspace.pending_candidates
            if item.atomic_expression == expressions[index]
        )
        operations.skip(
            role_id,
            candidate.candidate_fingerprint,
            expected_skipped_sha256=workspace.skipped_sha256 or "",
        )
    for index in range(11):
        operations.storage.create_capability(f"Reference {index:02d}")
    _role_with_signals(market, "Foreign Role", ["ForeignOnly"])

    client = TestClient(create_app(root), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    client.cookies.set("job_learning_current_role", role_id)

    pending_second = client.get("/capabilities?pending_page=2#pending-candidates")
    assert pending_second.text.count("Open candidate") == 2
    assert "Signal 35" in pending_second.text
    current_second = client.get(
        "/capabilities?current_page=2#current-capabilities"
    )
    assert current_second.text.count("View details &amp; Knowledge") == 2
    skipped_second = client.get(
        "/capabilities?skipped_page=2#skipped-candidates"
    )
    assert skipped_second.text.count(">Restore<") == 2
    all_third = client.get("/capabilities?all_page=3#all-capabilities")
    assert "Page 3 of 3" in all_third.text

    current_search = client.get(
        "/capabilities?current_query=Mapped+11#current-capabilities"
    )
    assert "Mapped 11" in current_search.text
    assert "Mapped 10" not in current_search.text
    foreign_search = client.get(
        "/capabilities?current_query=ForeignOnly#current-capabilities"
    )
    assert "No matching Capabilities" in foreign_search.text

    skipped_search = client.get(
        "/capabilities?skipped_query=Signal+12#skipped-candidates"
    )
    candidate = next(
        item
        for item in operations.workspace(role_id).skipped_candidates
        if item.atomic_expression == "Signal 12"
    )
    restored = client.post(
        f"/capabilities/skipped/{candidate.candidate_fingerprint}/restore",
        data={
            "role_id": role_id,
            "expected_skipped_sha256": operations.workspace(role_id).skipped_sha256,
        },
        follow_redirects=False,
    )
    assert restored.status_code == 303
    assert any(
        item.atomic_expression == "Signal 12"
        for item in operations.workspace(role_id).pending_candidates
    )


def test_role_and_merge_selectors_use_names_and_user_can_override_advice(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    market = MarketOperations(root)
    role_id = _role_with_signals(market, "Searchable Role", ["Candidate"])
    market.create_role("Another Role", market.view(role_id).roles_sha256)
    operations = CapabilityOperations(root)
    advised = operations.storage.create_capability("Candidate Platform")
    chosen = operations.storage.create_capability("Chosen Target")
    candidate = operations.workspace(role_id).pending_candidates[0]
    operations.prepare_recommendation(role_id, candidate.candidate_fingerprint)
    operations.handoffs.draft_path("capability-analysis").write_text(
        json.dumps(
            {
                "candidate_fingerprint": candidate.candidate_fingerprint,
                "explanation": "A reusable candidate.",
                "learning_value": "Useful in current work.",
                "recommended_action": "merge",
                "recommended_canonical_name": None,
                "recommended_merge_target": advised.name,
                "rationale": "The recommended target is close, but the user remains free to choose another valid Capability.",
                "evidence_quotes": ["Candidate"],
            }
        ),
        encoding="utf-8",
    )
    apply("capability-analysis", root)

    client = TestClient(create_app(root), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    client.cookies.set("job_learning_current_role", role_id)
    page = client.get(f"/capabilities/inbox/{candidate.candidate_fingerprint}")
    assert 'type="search" name="role_name"' in page.text
    assert '<option value="Searchable Role"></option>' in page.text
    assert 'type="search" name="merge_query"' in page.text
    assert 'value="Candidate Platform"' in page.text
    assert "Closest matches from confirmed Capability history" in page.text
    assert "Chosen Target" not in page.text
    assert "Search All Capabilities" in page.text
    assert "recommendation-details" in page.text
    assert "recommendation-details\" open" not in page.text
    assert str(advised.capability_id) not in page.text
    assert str(chosen.capability_id) not in page.text

    searched = client.get(
        f"/capabilities/inbox/{candidate.candidate_fingerprint}"
        "?merge_query=Chosen+Target"
    )
    assert 'value="Chosen Target"' in searched.text

    switched = client.post(
        "/roles/switch",
        data={"role_name": "Another Role"},
        follow_redirects=False,
    )
    assert switched.status_code == 303
    assert switched.cookies.get("job_learning_current_role")
    client.cookies.set("job_learning_current_role", role_id)

    merged = client.post(
        f"/capabilities/inbox/{candidate.candidate_fingerprint}/merge",
        data={
            "role_id": role_id,
            "capability_name": "Chosen Target",
            "expected_catalog_sha256": operations.workspace(role_id).catalog_sha256,
        },
        follow_redirects=False,
    )
    assert merged.status_code == 303
    mapping = next(
        item
        for item in operations.storage.load_catalog().source_mappings
        if item.source_expression == "Candidate"
    )
    assert mapping.capability_id == chosen.capability_id


def test_inbox_add_merge_skip_continue_to_deterministic_next_candidate(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    market = MarketOperations(root)
    role_id = _role_with_signals(market, "Continuous", ["A", "B", "C", "D"])
    operations = CapabilityOperations(root)
    target = operations.storage.create_capability("Existing Target")

    client = TestClient(create_app(root), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    client.cookies.set("job_learning_current_role", role_id)
    first = operations.workspace(role_id).pending_candidates[0]
    added = client.post(
        f"/capabilities/inbox/{first.candidate_fingerprint}/add",
        data={
            "role_id": role_id,
            "canonical_name": "Added A",
            "expected_catalog_sha256": operations.workspace(role_id).catalog_sha256,
        },
        follow_redirects=False,
    )
    second = operations.workspace(role_id).pending_candidates[0]
    assert added.status_code == 303
    assert second.candidate_fingerprint in added.headers["location"]

    merged = client.post(
        f"/capabilities/inbox/{second.candidate_fingerprint}/merge",
        data={
            "role_id": role_id,
            "capability_name": target.name,
            "expected_catalog_sha256": operations.workspace(role_id).catalog_sha256,
        },
        follow_redirects=False,
    )
    third = operations.workspace(role_id).pending_candidates[0]
    assert merged.status_code == 303
    assert third.candidate_fingerprint in merged.headers["location"]

    skipped = client.post(
        f"/capabilities/inbox/{third.candidate_fingerprint}/skip",
        data={
            "role_id": role_id,
            "expected_skipped_sha256": operations.workspace(role_id).skipped_sha256,
        },
        follow_redirects=False,
    )
    fourth = operations.workspace(role_id).pending_candidates[0]
    assert skipped.status_code == 303
    assert fourth.candidate_fingerprint in skipped.headers["location"]


def test_roadmap_history_is_limited_and_paginated(tmp_path: Path) -> None:
    root = tmp_path / "state"
    operations, _, role_id, _ = _ready_role(root)
    fingerprint = str(operations.generation_input(role_id)["input_fingerprint"])
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index in range(12):
        operations.storage.append_roadmap(
            RoadmapVersion(
                role_id=operations._uuid(role_id, "role_id"),
                generated_at=base_time + timedelta(days=index),
                input_fingerprint=fingerprint,
                content=f"# Version {index:02d}",
            )
        )

    client = TestClient(create_app(root), raise_server_exceptions=False, headers={"Accept-Language": "en"})
    client.cookies.set("job_learning_current_role", role_id)
    first = client.get("/roadmaps")
    second = client.get("/roadmaps?history_page=2#roadmap-history")
    assert first.status_code == 200 and second.status_code == 200
    first_history = first.text.split('id="roadmap-history"', 1)[1]
    second_history = second.text.split('id="roadmap-history"', 1)[1]
    assert first_history.count("<tr>") == 11
    assert second_history.count("<tr>") == 3
    assert "Page 2 of 2" in second.text
