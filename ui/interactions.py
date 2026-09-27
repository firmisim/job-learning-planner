from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi.responses import RedirectResponse


def redirect_with_notice(
    path: str,
    message: str,
    *,
    level: str = "success",
    anchor: str | None = None,
) -> RedirectResponse:
    """Return to an internal UI location without discarding its query context."""

    target = urlsplit(path)
    if target.scheme or target.netloc or not target.path.startswith("/"):
        raise ValueError("redirect target must be an absolute local UI path")
    query = [
        (key, value)
        for key, value in parse_qsl(target.query, keep_blank_values=True)
        if key not in {"notice", "level"}
    ]
    query.extend((("notice", message), ("level", level)))
    fragment = anchor if anchor is not None else target.fragment
    location = urlunsplit(("", "", target.path, urlencode(query), fragment))
    return RedirectResponse(location, status_code=303)
