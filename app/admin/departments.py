from flask import flash, redirect, render_template, request, url_for

from app.admin import admin_bp
from app.admin.services import paginated_admin_list, validate_department_form
from app.audit import audit
from app.auth import technical_admin_required
from app.extensions import db
from app.models import Department


@admin_bp.route("/departments")
@technical_admin_required
def departments():
    pagination = paginated_admin_list(
        Department,
        (Department.name, Department.code),
        {"name": Department.name, "code": Department.code},
        Department.name,
    )
    return render_template("admin/departments/list.html", departments=pagination.items, pagination=pagination)


@admin_bp.route("/departments/create", methods=["GET", "POST"])
@technical_admin_required
def create_department():
    if request.method == "POST":
        values, errors = validate_department_form(request.form)
        name, code = values["name"], values["code"]

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
        db.session.flush()

        audit(
            "DEPARTMENT_CREATED",
            entity_type="Department",
            entity_id=department.id,
            details={
                "name": department.name,
                "code": department.code,
            },
        )

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
        values, errors = validate_department_form(request.form, department)
        name, code = values["name"], values["code"]

        if errors:
            for error in errors:
                flash(error, "danger")

            return render_template(
                "admin/departments/form.html",
                department=department,
            )

        department.name = name
        department.code = code

        audit(
            "DEPARTMENT_UPDATED",
            entity_type="Department",
            entity_id=department.id,
            details={
                "name": department.name,
                "code": department.code,
                "is_active": department.is_active,
            },
        )

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

    if not department.is_active:
        flash("Кафедра уже архивирована.", "warning")
        return redirect(url_for("admin.departments"))

    department.is_active = False

    audit(
        "DEPARTMENT_ARCHIVED",
        entity_type="Department",
        entity_id=department.id,
        details={
            "name": department.name,
            "code": department.code,
        },
    )

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

    if department.is_active:
        flash("Кафедра уже активна.", "warning")
        return redirect(url_for("admin.departments"))

    department.is_active = True

    audit(
        "DEPARTMENT_RESTORED",
        entity_type="Department",
        entity_id=department.id,
        details={
            "name": department.name,
            "code": department.code,
        },
    )

    db.session.commit()

    flash("Кафедра восстановлена.", "success")

    return redirect(url_for("admin.departments"))
