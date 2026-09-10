from datetime import datetime

from flask import jsonify, render_template, request
from sqlalchemy import func, select

from app.admin import admin_bp
from app.auth import technical_admin_required
from app.extensions import db
from app.models import AuditLog, User


def _parse_datetime(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _serialize_audit(log):
    return {
        "id": log.id,
        "user_id": log.user_id,
        "username": log.user.username if log.user else None,
        "full_name": log.user.full_name if log.user else None,
        "action": log.action,
        "entity_type": log.entity_type,
        "entity_id": log.entity_id,
        "details": log.details,
        "ip_address": log.ip_address,
        "created_at": log.created_at.isoformat(),
    }


@admin_bp.route("/audit", methods=["GET"])
@technical_admin_required
def audit_list():
    try:
        limit = int(request.args.get("limit", "100"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        return jsonify({"error": "limit и offset должны быть числами."}), 400

    limit = min(max(limit, 1), 500)
    offset = max(offset, 0)

    action = request.args.get("action", "").strip()
    entity_type = request.args.get("entity_type", "").strip()
    username = request.args.get("username", "").strip()
    ip_address = request.args.get("ip_address", "").strip()
    date_from = _parse_datetime(request.args.get("date_from", "").strip())
    date_to = _parse_datetime(request.args.get("date_to", "").strip())

    query = select(AuditLog).order_by(
        AuditLog.created_at.desc(),
        AuditLog.id.desc(),
    )

    if action:
        query = query.where(AuditLog.action == action)

    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)

    if ip_address:
        query = query.where(AuditLog.ip_address == ip_address)

    if username:
        query = query.join(
            User,
            AuditLog.user_id == User.id,
        ).where(
            User.username.ilike(f"%{username}%")
        )

    if date_from:
        query = query.where(AuditLog.created_at >= date_from)

    if date_to:
        query = query.where(AuditLog.created_at <= date_to)

    total = db.session.scalar(
        select(func.count()).select_from(
            query.order_by(None).subquery()
        )
    )

    logs = db.session.scalars(
        query.offset(offset).limit(limit)
    ).all()

    payload = {
        "items": [_serialize_audit(log) for log in logs],
        "total": total or 0,
        "limit": limit,
        "offset": offset,
    }
    if request.args.get("view") == "1":
        return render_template("admin/audit.html", logs=logs, total=payload["total"])
    return jsonify(payload)
