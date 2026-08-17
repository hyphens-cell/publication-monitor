from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import or_, select

from app.admin import admin_bp
from app.auth import technical_admin_required
from app.extensions import db
from app.models import Department


@admin_bp.route("/departments")
@technical_admin_required
def departments():
    departments_list = db.session.scalars(
        select(Department).order_by(Department.name)
    ).all()

    return render_template(
        "admin/departments/list.html",
        departments=departments_list,
    )


@admin_bp.route("/departments/create", methods=["GET", "POST"])
@technical_admin_required
def create_department():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip().upper()

        errors = []

        if not name:
            errors.append("Введите название кафедры.")

        if not code:
            errors.append("Введите код кафедры.")

        if len(code) > 50:
            errors.append("Код кафедры не должен превышать 50 символов.")

        existing_department = db.session.scalar(
            select(Department).where(
                or_(
                    Department.name == name,
                    Department.code == code,
                )
            )
        )

        if existing_department:
            if existing_department.name == name:
                errors.append("Кафедра с таким названием уже существует.")

            if existing_department.code == code:
                errors.append("Кафедра с таким кодом уже существует.")

        if errors:
            for error in errors:
                flash(error, "danger")

            return render_template(
                "admin/departments/form.html",
                department=None,
            )

        department = Department(
            name=name,
            code=code,
            is_active=True,
        )

        db.session.add(department)
        db.session.commit()

        flash("Кафедра успешно создана.", "success")

        return redirect(url_for("admin.departments"))

    return render_template(
        "admin/departments/form.html",
        department=None,
    )


@admin_bp.route("/departments/<int:department_id>/edit", methods=["GET", "POST"])
@technical_admin_required
def edit_department(department_id):
    department = db.session.get(Department, department_id)

    if department is None:
        flash("Кафедра не найдена.", "danger")
        return redirect(url_for("admin.departments"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip().upper()

        errors = []

        if not name:
            errors.append("Введите название кафедры.")

        if not code:
            errors.append("Введите код кафедры.")

        if len(code) > 50:
            errors.append("Код кафедры не должен превышать 50 символов.")

        duplicate = db.session.scalar(
            select(Department).where(
                Department.id != department.id,
                or_(
                    Department.name == name,
                    Department.code == code,
                ),
            )
        )

        if duplicate:
            if duplicate.name == name:
                errors.append(
                    "Кафедра с таким названием уже существует."
                )

            if duplicate.code == code:
                errors.append(
                    "Кафедра с таким кодом уже существует."
                )

        if errors:
            for error in errors:
                flash(error, "danger")

            return render_template(
                "admin/departments/form.html",
                department=department,
            )

        department.name = name
        department.code = code

        db.session.commit()

        flash("Кафедра успешно изменена.", "success")

        return redirect(url_for("admin.departments"))

    return render_template(
        "admin/departments/form.html",
        department=department,
    )


@admin_bp.route(
    "/departments/<int:department_id>/archive",
    methods=["POST"],
)
@technical_admin_required
def archive_department(department_id):
    department = db.session.get(Department, department_id)

    if department is None:
        flash("Кафедра не найдена.", "danger")
        return redirect(url_for("admin.departments"))

    department.is_active = False

    db.session.commit()

    flash("Кафедра архивирована.", "success")

    return redirect(url_for("admin.departments"))


@admin_bp.route(
    "/departments/<int:department_id>/restore",
    methods=["POST"],
)
@technical_admin_required
def restore_department(department_id):
    department = db.session.get(Department, department_id)

    if department is None:
        flash("Кафедра не найдена.", "danger")
        return redirect(url_for("admin.departments"))

    department.is_active = True

    db.session.commit()

    flash("Кафедра восстановлена.", "success")

    return redirect(url_for("admin.departments"))