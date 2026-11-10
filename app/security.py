"""Shared browser/session policy at the HTTP boundary."""

import hashlib
from urllib.parse import unquote, urlsplit

from flask import request


def password_stamp(user):
    return hashlib.sha256(user.password_hash.encode("utf-8")).hexdigest()


def safe_local_redirect(value):
    if not isinstance(value, str) or not value:
        return False
    decoded = value
    for _ in range(3):
        decoded = unquote(decoded)
    if any(ord(char) < 32 or ord(char) == 127 for char in decoded) or "\\" in decoded:
        return False
    try:
        parts = urlsplit(decoded)
    except ValueError:
        return False
    return decoded.startswith("/") and not decoded.startswith("//") and not parts.scheme and not parts.netloc


def register_security_headers(app):
    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            (
                "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data:; "
                "font-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
            ),
        )
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store, private"
        if request.is_secure and app.config["APP_ENV"] == "production":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response
