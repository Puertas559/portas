from __future__ import annotations

import os
import secrets
from datetime import timedelta
from urllib.parse import urlparse

from flask import current_app, g, request, session


def configure_security(app):
    app.config.setdefault("PERMANENT_SESSION_LIFETIME", timedelta(hours=int(os.getenv("SESSION_HOURS", "12"))))
    app.config.setdefault("SESSION_REFRESH_EACH_REQUEST", True)
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Strict")
    app.config.setdefault("SESSION_COOKIE_SECURE", True)


def mark_session_permanent():
    session.permanent = True


def same_origin_ok() -> bool:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return True
    origin = request.headers.get("Origin")
    if not origin:
        # Native forms and same-site clients may omit Origin. Sec-Fetch-Site adds another signal.
        return request.headers.get("Sec-Fetch-Site", "same-origin") in {"same-origin", "same-site", "none"}
    return urlparse(origin).netloc == request.host


def apply_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(self)")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    response.headers.setdefault("X-Robots-Tag", "noindex, nofollow, noarchive")
    if request.is_secure or os.getenv("TRUST_PROXY", "false").lower() in {"1", "true", "yes"}:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    # Compatible policy for the current frontend; still blocks foreign frames/objects/forms.
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; "
        "form-action 'self'; img-src 'self' data: https:; font-src 'self' data: https:; "
        "style-src 'self' 'unsafe-inline' https:; script-src 'self' 'unsafe-inline' https:; "
        "connect-src 'self' https:; upgrade-insecure-requests",
    )
    if request.path.startswith(("/api/", "/hub/")):
        response.headers.setdefault("Cache-Control", "private, no-store")
    return response
