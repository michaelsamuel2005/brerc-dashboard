"""Baseline HTTP security headers.

The embedding-related header (``Content-Security-Policy: frame-ancestors ...``)
is set once at the reverse proxy (see proxy/Caddyfile), so it is intentionally
NOT set here to avoid two conflicting policies. This middleware adds the
non-conflicting hardening headers that belong on every API response.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        # Note: no X-Frame-Options here — embedding is controlled by the proxy's
        # CSP frame-ancestors so the dashboard can sit inside BRERC's site.
        return response
