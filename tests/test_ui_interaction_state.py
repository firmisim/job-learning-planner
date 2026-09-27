from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit

from fastapi.testclient import TestClient

from tests.test_ui_high_volume import _run_chromium_until_complete
from ui.app import create_app


def test_bulk_selection_survives_pages_and_respects_scope_boundaries(
    tmp_path: Path,
) -> None:
    app_script = (Path(__file__).parents[1] / "ui" / "static" / "app.js").read_text(
        encoding="utf-8"
    )
    submitted: list[dict[str, list[str]]] = []
    requested_paths: list[str] = []
    reported_results: list[str] = []
    completion = Event()

    def page(
        items: tuple[str, ...],
        *,
        role: str = "role-a",
        query: str = "",
        action: str = "/submit",
    ) -> bytes:
        checkboxes = "".join(
            f'<input type="checkbox" name="capability_id" value="{item}" '
            f'data-bulk-item aria-label="{item}">'
            for item in items
        )
        stage = """
const count = () => document.querySelector('[data-selected-count]').textContent;
const item = (value) => document.querySelector(`[data-bulk-item][value="${value}"]`);
const finish = (result) => {
  document.body.dataset.result = result;
  fetch(`/result?status=${encodeURIComponent(result)}`);
};
const fail = (message) => finish(`FAIL: ${message}`);
const phase = sessionStorage.getItem('test-phase') || 'first';
if (phase === 'first') {
  item('a').click(); item('b').click();
  if (count() !== '2') fail('page-one count');
  else { sessionStorage.setItem('test-phase', 'second'); location.href = '/page2'; }
} else if (phase === 'second') {
  if (count() !== '2') fail('cross-page count');
  else { item('c').click(); sessionStorage.setItem('test-phase', 'back'); location.href = '/'; }
} else if (phase === 'back') {
  if (!item('a').checked || !item('b').checked || count() !== '3') fail('restored state');
  else { item('b').click(); sessionStorage.setItem('test-phase', 'submitted'); document.querySelector('[data-bulk-submit]').click(); }
} else if (phase === 'submitted') {
  if (count() !== '0') fail('successful submit did not clear');
  else { item('a').click(); sessionStorage.setItem('test-phase', 'reload'); location.reload(); }
} else if (phase === 'reload') {
  if (!item('a').checked || count() !== '1') fail('refresh did not restore');
  else { sessionStorage.setItem('test-phase', 'query'); document.querySelector('[data-search-submit]').click(); }
} else if (phase === 'query') {
  if (count() !== '0') fail('query change did not clear');
  else { item('c').click(); sessionStorage.setItem('test-phase', 'role'); document.querySelector('[data-role-submit]').click(); }
} else if (phase === 'role') {
  if (count() !== '0') fail('role change did not clear');
  else { item('d').click(); sessionStorage.setItem('test-phase', 'failed'); document.querySelector('[data-bulk-submit]').click(); }
} else if (phase === 'failed') {
  finish(item('d').checked && count() === '1'
    ? 'PASS'
    : 'FAIL: failed submit lost selection');
}
"""
        html = f"""<!doctype html>
<title>Bulk selection test</title>
<body>
  <form method="post" action="{action}" data-bulk-form data-selection-list="knowledge" data-selection-role="{role}" data-selection-query="{query}">
    {checkboxes}
    <span data-selected-count>0</span>
    <button type="submit" data-bulk-submit disabled>Prepare Selected</button>
  </form>
  <form method="get" action="/query">
    <input name="knowledge_query" value="changed">
    <button type="submit" data-search-submit>Search</button>
  </form>
  <form method="post" action="/role" data-role-switch>
    <button type="submit" data-role-submit>Switch</button>
  </form>
  <script>{app_script}</script>
  <script>{stage}</script>
</body>"""
        return html.encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requested_paths.append(f"GET {self.path}")
            parsed = urlsplit(self.path)
            if parsed.path == "/result":
                reported_results.extend(parse_qs(parsed.query).get("status", ()))
                completion.set()
                self.send_response(204)
                self.end_headers()
                return
            if parsed.path == "/page2":
                body = page(("c",))
            elif parsed.path == "/query":
                body = page(("c",), query="changed")
            elif parsed.path == "/role":
                body = page(("d",), role="role-b", query="changed", action="/fail")
            else:
                body = page(("a", "b"))
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            requested_paths.append(f"POST {self.path}")
            length = int(self.headers.get("Content-Length", "0"))
            values = parse_qs(self.rfile.read(length).decode("utf-8"))
            if self.path == "/submit":
                submitted.append(values)
                self.send_response(303)
                self.send_header("Location", "/?selection_cleared=knowledge")
                self.end_headers()
                return
            if self.path == "/role":
                self.send_response(303)
                self.send_header("Location", "/role")
                self.end_headers()
                return
            body = page(("d",), role="role-b", query="changed", action="/fail")
            self.send_response(422)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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
            semantic_state=lambda: {
                "reported_results": tuple(reported_results),
                "submitted": tuple(submitted),
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert reported_results == ["PASS"]
    assert submitted == [{"capability_id": ["a", "c"]}]


def test_market_cross_page_selection_deletes_all_selected_jds_and_retains_stale_failure(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    app = create_app(root)
    market = app.state.market
    role_a, _ = market.create_role("Market Role A", market.view().roles_sha256)
    role_b, _ = market.create_role("Market Role B", market.view(role_a).roles_sha256)
    for index in range(12):
        view = market.view(role_a)
        market.add_job(
            role_a,
            title=f"JD {index:02d}",
            company="Example",
            jd_text=f"Description {index:02d}",
            source_url=None,
            expected_sha256=view.jds_sha256 or "",
        )
    original_jobs = market.view(role_a).jobs
    client = TestClient(
        app,
        raise_server_exceptions=False,
        headers={"Accept-Language": "en"},
    )
    client.cookies.set("job_learning_current_role", role_a)
    delete_requests: list[list[tuple[str, str]]] = []
    requested_paths: list[str] = []
    reported_results: list[str] = []
    browser_done = Event()
    app_script = (Path(__file__).parents[1] / "ui" / "static" / "app.js").read_bytes()

    automation = f"""
<script>
(() => {{
  window.confirm = () => true;
  const phase = sessionStorage.getItem('market-test-phase') || 'first';
  const form = document.querySelector('[data-selection-list="market-jd"]');
  const items = form ? [...form.querySelectorAll('[data-bulk-item]')] : [];
  const count = () => form?.querySelector('[data-selected-count]')?.textContent;
  const finish = (result) => {{
    document.body.dataset.result = result;
    fetch(`/release?result=${{encodeURIComponent(result)}}`);
  }};
  const fail = (message) => finish(`FAIL: ${{message}}`);
  const switchRole = (name, nextPhase) => {{
    const roleForm = document.querySelector('[data-role-switch]');
    roleForm.querySelector('[name="role_name"]').value = name;
    sessionStorage.setItem('market-test-phase', nextPhase);
    roleForm.querySelector('button').click();
  }};
  if (phase === 'first') {{
    items[0].click(); items[1].click();
    if (count() !== '2') fail('page-one count');
    else {{ sessionStorage.setItem('market-test-phase', 'second'); location.href = '/market?jd_page=2#jd-list'; }}
  }} else if (phase === 'second') {{
    if (count() !== '2') fail('page-two retained count');
    else {{ items[0].click(); sessionStorage.setItem('market-test-phase', 'back'); location.href = '/market?jd_page=1#jd-list'; }}
  }} else if (phase === 'back') {{
    if (!items[0].checked || !items[1].checked || count() !== '3') fail('page-one restore');
    else {{ items[1].click(); sessionStorage.setItem('market-test-phase', 'refresh'); location.reload(); }}
  }} else if (phase === 'refresh') {{
    if (!items[0].checked || items[1].checked || count() !== '2') fail('refresh restore');
    else {{
      sessionStorage.setItem('market-test-phase', 'query');
      location.href = '/market?jd_query=JD+00#jd-list';
    }}
  }} else if (phase === 'query') {{
    if (count() !== '0') fail('query change did not clear');
    else {{ sessionStorage.setItem('market-test-phase', 'role-select'); location.href = '/market'; }}
  }} else if (phase === 'role-select') {{
    items[0].click();
    switchRole('Market Role B', 'role-b');
  }} else if (phase === 'role-b') {{
    if (sessionStorage.getItem('job-learning-bulk-selection:market-jd') !== null) fail('role change did not clear');
    else switchRole('Market Role A', 'role-a');
  }} else if (phase === 'role-a') {{
    if (count() !== '0') fail('old Role selection returned');
    else {{
      items[0].click(); items[1].click();
      sessionStorage.setItem('market-test-phase', 'delete-second');
      location.href = '/market?jd_page=2#jd-list';
    }}
  }} else if (phase === 'delete-second') {{
    if (count() !== '2') fail('delete cross-page count');
    else {{ items[0].click(); sessionStorage.setItem('market-test-phase', 'deleted'); form.querySelector('[data-bulk-submit]').click(); }}
  }} else if (phase === 'deleted') {{
    if (count() !== '0') fail('successful delete did not clear');
    else {{
      items[0].click();
      form.querySelector('[name="expected_sha256"]').value = '{'0' * 64}';
      sessionStorage.setItem('market-test-phase', 'stale-response');
      form.querySelector('[data-bulk-submit]').click();
    }}
  }} else if (phase === 'stale-response') {{
    sessionStorage.setItem('market-test-phase', 'recover');
    location.href = '/market';
  }} else if (phase === 'recover') {{
    finish(items[0]?.checked && count() === '1'
      ? 'PASS'
      : 'FAIL: stale failure lost selection');
  }}
}})();
</script>
""".encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def _send(self, response: object) -> None:
            status_code = int(getattr(response, "status_code"))
            headers = getattr(response, "headers")
            body = bytes(getattr(response, "content"))
            content_type = headers.get("content-type", "")
            if "text/html" in content_type:
                body = body.replace(b"http://testserver/", b"/")
                body = body.replace(
                    b'<script src="/static/app.js" defer></script>',
                    b"",
                )
                runtime = (
                    b'<iframe hidden src="/hold"></iframe><script>'
                    + app_script
                    + b"</script>"
                    + automation
                )
                body = body.replace(b"</body>", runtime + b"</body>")
            self.send_response(status_code)
            if headers.get("location"):
                self.send_header("Location", headers["location"])
            self.send_header("Content-Type", content_type or "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionAbortedError):
                pass

        def do_GET(self) -> None:
            requested_paths.append(f"GET {self.path}")
            parsed = urlsplit(self.path)
            if parsed.path == "/hold":
                browser_done.wait(timeout=25)
                self.send_response(204)
                self.end_headers()
                return
            if parsed.path == "/release":
                reported_results.extend(parse_qs(parsed.query).get("result", ()))
                browser_done.set()
                self.send_response(204)
                self.end_headers()
                return
            self._send(client.get(self.path, follow_redirects=False))

        def do_POST(self) -> None:
            requested_paths.append(f"POST {self.path}")
            length = int(self.headers.get("Content-Length", "0"))
            values = parse_qsl(
                self.rfile.read(length).decode("utf-8"), keep_blank_values=True
            )
            if self.path == "/market/jobs/delete":
                delete_requests.append(values)
            self._send(
                client.post(
                    self.path,
                    content=urlencode(values),
                    headers={"content-type": "application/x-www-form-urlencoded"},
                    follow_redirects=False,
                )
            )

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _run_chromium_until_complete(
            profile=tmp_path / "market-browser-profile",
            target=f"http://127.0.0.1:{server.server_port}/market",
            timeout=30,
            completion=browser_done,
            requested_paths=requested_paths,
            semantic_state=lambda: {
                "reported_results": tuple(reported_results),
                "delete_requests": tuple(tuple(values) for values in delete_requests),
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert reported_results == ["PASS"], (
        reported_results,
        delete_requests,
        [job.title for job in market.view(role_a).jobs],
    )
    assert len(delete_requests) == 2
    submitted_job_ids = [
        value for key, value in delete_requests[0] if key == "job_id"
    ]
    assert set(submitted_job_ids) == {
        str(original_jobs[0].job_id),
        str(original_jobs[1].job_id),
        str(original_jobs[10].job_id),
    }
    assert len(submitted_job_ids) == 3
    remaining_ids = {str(job.job_id) for job in market.view(role_a).jobs}
    assert not set(submitted_job_ids) & remaining_ids
    assert len(remaining_ids) == 9
    assert market.view(role_b).jobs == ()
