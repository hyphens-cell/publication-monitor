import csv
import json
from datetime import datetime
from io import StringIO

from flask import Response, abort, jsonify, render_template, request
from flask_login import current_user
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.admin import admin_bp
from app.auth import roles_required
from app.extensions import db
from app.models import AuditLog, User


def _parse_datetime(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        abort(400)


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


@admin_bp.route("/audit/export.csv", methods=["GET"], endpoint="audit_export")
@admin_bp.route("/audit", methods=["GET"])
@admin_bp.route("/api/audit", methods=["GET"], endpoint="audit_api")
@roles_required("TECH_ADMIN", "ADMIN")
def audit_list():
    is_api = request.endpoint == "admin.audit_api"
    is_export = request.endpoint == "admin.audit_export"
    if is_export and current_user.role != "TECH_ADMIN":
        abort(403)
    try:
        limit = int(request.args.get("limit", "100"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        message = "limit и offset должны быть числами."
        if is_api:
            return jsonify({"error": message}), 400
        abort(400, description=message)

    limit = min(max(limit, 1), 500)
    offset = max(offset, 0)

    action = request.args.get("action", "").strip()
    entity_type = request.args.get("entity_type", "").strip()
    username = request.args.get("username", "").strip()
    ip_address = request.args.get("ip_address", "").strip()
    date_from = _parse_datetime(request.args.get("date_from", "").strip())
    date_to = _parse_datetime(request.args.get("date_to", "").strip())

    query = (
        select(AuditLog)
        .options(joinedload(AuditLog.user))
        .order_by(
            AuditLog.created_at.desc(),
            AuditLog.id.desc(),
        )
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
        ).where(User.username.ilike(f"%{username}%"))

    if date_from:
        query = query.where(AuditLog.created_at >= date_from)

    if date_to:
        query = query.where(AuditLog.created_at <= date_to)

    if date_from and date_to and date_from > date_to:
        abort(400)
    if is_export:
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(
            ["ID", "Дата", "Пользователь", "Действие", "Объект", "ID объекта", "IP", "Подробности"]
        )

        def safe_cell(value):
            value = str(value) if value is not None else ""
            return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value

        for log in db.session.scalars(query.execution_options(yield_per=500)):
            writer.writerow(
                [
                    safe_cell(value)
                    for value in [
                        log.id,
                        log.created_at.isoformat(),
                        log.user.username if log.user else "",
                        log.action,
                        log.entity_type,
                        log.entity_id,
                        log.ip_address,
                        json.dumps(log.details, ensure_ascii=False),
                    ]
                ]
            )
        return Response(
            "\ufeff" + output.getvalue(),
            content_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=audit.csv"},
        )

    total = db.session.scalar(select(func.count()).select_from(query.order_by(None).subquery()))

    logs = db.session.scalars(query.offset(offset).limit(limit)).all()

    payload = {
        "items": [_serialize_audit(log) for log in logs],
        "total": total or 0,
        "limit": limit,
        "offset": offset,
    }
    if is_api:
        return jsonify(payload)
    return render_template("admin/audit.html", logs=logs, total=payload["total"])
