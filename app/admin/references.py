from flask import flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy import select

from app.admin import admin_bp
from app.audit import audit
from app.auth import technical_admin_required
from app.extensions import db
from app.models import ReferenceValue


def _serialize_reference(item):
    return {
        "id": item.id,
        "type": item.type,
        "code": item.code,
        "name_ru": item.name_ru,
        "name_kk": item.name_kk,
        "sort_order": item.sort_order,
        "is_active": item.is_active,
    }


def _payload():
    data = request.get_json(silent=True)

    if data is None:
        data = request.form

    return data


@admin_bp.route("/references", methods=["GET"])
@technical_admin_required
def list_references():
    reference_type = request.args.get("type", "").strip()

    query = select(ReferenceValue).order_by(
        ReferenceValue.type,
        ReferenceValue.sort_order,
        ReferenceValue.name_ru,
    )

    if reference_type:
        query = query.where(ReferenceValue.type == reference_type)

    values = db.session.scalars(query).all()

    if request.args.get("view") == "1":
        return render_template("admin/references.html", values=values)
    return jsonify({"items": [_serialize_reference(item) for item in values]})


@admin_bp.route("/references", methods=["POST"])
@technical_admin_required
def create_reference():
    data = _payload()

    reference_type = str(data.get("type", "")).strip()
    code = str(data.get("code", "")).strip()
    name_ru = str(data.get("name_ru", "")).strip()
    name_kk = str(data.get("name_kk", "")).strip()

    try:
        sort_order = int(data.get("sort_order", 0))
    except (TypeError, ValueError):
        message = "Порядок сортировки должен быть числом."
        if request.is_json:
            return jsonify({"error": message}), 400
        flash(message, "danger")
        return redirect(url_for("admin.list_references", view=1))

    if not reference_type or not code or not name_ru or not name_kk:
        message = "type, code, name_ru и name_kk обязательны."
        if request.is_json:
            return jsonify({"error": message}), 400
        flash(message, "danger")
        return redirect(url_for("admin.list_references", view=1))

    existing = db.session.scalar(
        select(ReferenceValue).where(
            ReferenceValue.type == reference_type,
            ReferenceValue.code == code,
        )
    )

    if existing is not None:
        message = "Справочное значение с таким type и code уже существует."
        if request.is_json:
            return jsonify({"error": message}), 409
        flash(message, "danger")
        return redirect(url_for("admin.list_references", view=1))

    item = ReferenceValue(
        type=reference_type,
        code=code,
        name_ru=name_ru,
        name_kk=name_kk,
        sort_order=sort_order,
        is_active=True,
    )

    db.session.add(item)
    db.session.flush()

    audit(
        "REFERENCE_VALUE_CREATED",
        entity_type="ReferenceValue",
        entity_id=item.id,
        details=_serialize_reference(item),
    )

    db.session.commit()

    if request.is_json:
        return jsonify(_serialize_reference(item)), 201
    flash("Справочное значение добавлено.", "success")
    return redirect(url_for("admin.list_references", view=1))


@admin_bp.route("/references/<int:reference_id>", methods=["PUT", "PATCH"])
@technical_admin_required
def update_reference(reference_id):
    item = db.session.get(ReferenceValue, reference_id)

    if item is None:
        return jsonify({"error": "Справочное значение не найдено."}), 404

    data = _payload()

    reference_type = str(data.get("type", item.type)).strip()
    code = str(data.get("code", item.code)).strip()
    name_ru = str(data.get("name_ru", item.name_ru)).strip()
    name_kk = str(data.get("name_kk", item.name_kk)).strip()

    try:
        sort_order = int(data.get("sort_order", item.sort_order))
    except (TypeError, ValueError):
        return jsonify({"error": "sort_order должен быть числом."}), 400

    if not reference_type or not code or not name_ru or not name_kk:
        return jsonify(
            {
                "error": "type, code, name_ru и name_kk обязательны."
            }
        ), 400

    duplicate = db.session.scalar(
        select(ReferenceValue).where(
            ReferenceValue.id != item.id,
            ReferenceValue.type == reference_type,
            ReferenceValue.code == code,
        )
    )

    if duplicate is not None:
        return jsonify(
            {"error": "Справочное значение с таким type и code уже существует."}
        ), 409

    item.type = reference_type
    item.code = code
    item.name_ru = name_ru
    item.name_kk = name_kk
    item.sort_order = sort_order

    audit(
        "REFERENCE_VALUE_UPDATED",
        entity_type="ReferenceValue",
        entity_id=item.id,
        details=_serialize_reference(item),
    )

    db.session.commit()

    return jsonify(_serialize_reference(item))


@admin_bp.route("/references/<int:reference_id>/status", methods=["POST"])
@technical_admin_required
def change_reference_status(reference_id):
    item = db.session.get(ReferenceValue, reference_id)

    if item is None:
        return jsonify({"error": "Справочное значение не найдено."}), 404

    data = _payload()
    value = data.get("is_active")

    if isinstance(value, bool):
        is_active = value
    else:
        is_active = str(value).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    item.is_active = is_active

    audit(
        "REFERENCE_VALUE_STATUS_CHANGED",
        entity_type="ReferenceValue",
        entity_id=item.id,
        details={
            "type": item.type,
            "code": item.code,
            "is_active": item.is_active,
        },
    )

    db.session.commit()

    return jsonify(_serialize_reference(item))
