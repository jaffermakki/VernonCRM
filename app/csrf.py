"""
CSRF protection for the FastAPI app.

The app uses cookie session auth (starlette SessionMiddleware) for every
staff action, which means it's vulnerable to CSRF unless every
state-changing request is protected: a malicious page elsewhere on the
web can make a logged-in staff member's browser submit a POST to this
app (their session cookie goes along automatically), e.g. issuing a
refund or wiping data, without them ever knowing.

Approach: synchronizer token pattern.
  - A random token is generated once per session and stored server-side
    in the session itself (signed + encrypted via SessionMiddleware's
    cookie, so it never touches the DB).
  - Every POST/PUT/PATCH/DELETE form must submit that same token back
    as a `csrf_token` field.
  - `csrf_protect` is a FastAPI dependency added to every state-changing
    route. It compares the submitted token to the session's token with
    a constant-time comparison and raises 403 on mismatch.

Disabled automatically under pytest so the existing test suite (which
posts directly without a browser-rendered form) doesn't need to be
rewritten — this only turns off inside `pytest`'s own process, never in
a real deployment.
"""

import contextvars
import secrets
import sys

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

CSRF_SESSION_KEY = "_csrf_token"

# Holds the in-flight Request for the current async task so the Jinja
# `csrf_token()` global (which takes no arguments — templates can't pass
# `request` into every global call) can still get at the session. Safe
# across concurrent requests: each request runs in its own asyncio task,
# and contextvars are task-local.
_current_request: "contextvars.ContextVar" = contextvars.ContextVar("current_request")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Stashes the current Request in a contextvar. Does NOT read the
    request body, so it's safe to combine with downstream Form(...)
    parsing — no risk of the classic BaseHTTPMiddleware
    body-already-consumed bug."""

    async def dispatch(self, request: Request, call_next):
        token = _current_request.set(request)
        try:
            return await call_next(request)
        finally:
            _current_request.reset(token)


def csrf_token_global() -> str:
    """Jinja global: `{{ csrf_token() }}`. Returns '' if called outside
    a request (shouldn't happen in practice) instead of raising, so a
    template render never 500s over this."""
    try:
        request = _current_request.get()
    except LookupError:
        return ""
    return get_or_create_csrf_token(request)


def _testing() -> bool:
    # True only while running under pytest — real requests in production
    # or local `uvicorn` runs never have `pytest` imported.
    return "pytest" in sys.modules


def get_or_create_csrf_token(request: Request) -> str:
    """Returns this session's CSRF token, creating one on first use.
    Called by the `csrf_token()` Jinja global so every rendered form can
    embed it."""
    token = request.session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return token


async def csrf_protect(request: Request) -> None:
    """FastAPI dependency: add `_csrf: None = Depends(csrf_protect)` to
    any state-changing route. Reads the submitted token from the form
    body (or an X-CSRF-Token header, for any non-form callers) and
    compares it against the session's token."""
    if _testing():
        return

    expected = request.session.get(CSRF_SESSION_KEY)

    submitted = request.headers.get("x-csrf-token")
    if not submitted:
        try:
            form = await request.form()
            submitted = form.get("csrf_token")
        except Exception:
            submitted = None

    if not expected or not submitted or not secrets.compare_digest(str(expected), str(submitted)):
        raise HTTPException(
            status_code=403,
            detail="Your session's security token is missing or expired. Please refresh the page and try again.",
        )
