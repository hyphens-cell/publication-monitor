from __future__ import annotations

from typing import Any

from flask import has_request_context, request
from flask_login import current_user

from app.extensions import db
from app.models import AuditLog


def _current_user_id() -> int | None:
    if not has_request_context():
        return None

    if not current_user.is_authenticated:
        return None

    return current_user.id


def _current_ip_address() -> str | None:
    if not has_request_context():
        return None

    forwarded_for = request.headers.get("X-Forwarded-For", "")

    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()[:45]

    return request.remote_addr[:45] if request.remote_addr else None


def audit(
    action: str,
    *,
    entity_type: str | None = None,
    entity_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    normalized_action = action.strip()

    if not normalized_action:
        raise ValueError(
            "Действие аудита не может быть пустым."
        )

    if entity_type is not None:
        entity_type = entity_type.strip() or None

    if details is not None and not isinstance(details, dict):
        raise TypeError(
            "details должен быть словарём."
        )

    log = AuditLog(
        user_id=_current_user_id(),
        action=normalized_action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
        ip_address=_current_ip_address(),
    )

    db.session.add(log)

    return log


def audit_commit(
    action: str,
    *,
    entity_type: str | None = None,
    entity_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    log = audit(
        action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
    )

    db.session.commit()

    return log