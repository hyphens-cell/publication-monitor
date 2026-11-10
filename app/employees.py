from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import or_, select

from app.audit import audit
from app.auth import department_head_required
from app.extensions import db
from app.models import Employee
from app.services.listing import paginate, search_term, sort_order
from app.services.validation import validate_employee

employees_bp = Blueprint(
    "employees",
    __name__,
    url_prefix="/employees",
)


def get_employee(employee_id):
    employee = db.session.get(Employee, employee_id)

    if employee is None:
        flash("Сотрудник не найден.", "danger")
        return None

    if employee.department_id != current_user.department_id:
        flash("Сотрудник не относится к вашей кафедре.", "danger")
        return None

    return employee


@employees_bp.route("/")
@department_head_required
def employees():
    if current_user.department_id is None:
        flash(
            "У пользователя не указана кафедра.",
            "danger",
        )
        return redirect(url_for("main.index"))

    query = select(Employee).where(Employee.department_id == current_user.department_id)
    term = search_term(request.args)
    if term:
        query = query.where(
            or_(
                Employee.full_name.ilike(f"%{term}%", escape="\\"),
                Employee.position.ilike(f"%{term}%", escape="\\"),
                Employee.email.ilike(f"%{term}%", escape="\\"),
            )
        )
    order = sort_order(
        request.args, {"name": Employee.full_name.asc(), "name_desc": Employee.full_name.desc()}, "name"
    )
    pagination = paginate(query.order_by(Employee.is_active.desc(), order, Employee.id), request.args)

    return render_template(
        "employees/list.html",
        employees=pagination.items,
        pagination=pagination,
    )


@employees_bp.route("/create", methods=["GET", "POST"])
@department_head_required
def create_employee():
    if current_user.department_id is None:
        flash(
            "У пользователя не указана кафедра.",
            "danger",
        )
        return redirect(url_for("main.index"))

    if request.method == "POST":
        values, errors = validate_employee(request.form)
        full_name, position, email = values.full_name, values.position, values.email

        if errors:
            for error in errors:
                flash(error, "danger")

            return render_template(
                "employees/form.html",
                employee=None,
            )

        employee = Employee(
            department_id=current_user.department_id,
            full_name=full_name,
            position=position or None,
            email=email or None,
            is_active=True,
        )

        db.session.add(employee)
        db.session.flush()
        audit(
            "EMPLOYEE_CREATED",
            entity_type="Employee",
            entity_id=employee.id,
            details={"department_id": employee.department_id, "full_name": employee.full_name},
        )
        db.session.commit()

        flash(
            "Сотрудник успешно добавлен.",
            "success",
        )

        return redirect(url_for("employees.employees"))

    return render_template(
        "employees/form.html",
        employee=None,
    )


@employees_bp.route(
    "/<int:employee_id>/edit",
    methods=["GET", "POST"],
)
@department_head_required
def edit_employee(employee_id):
    employee = get_employee(employee_id)

    if employee is None:
        return redirect(url_for("employees.employees"))

    if request.method == "POST":
        values, errors = validate_employee(request.form)
        full_name, position, email = values.full_name, values.position, values.email

        if errors:
            for error in errors:
                flash(error, "danger")

            return render_template(
                "employees/form.html",
                employee=employee,
            )

        employee.full_name = full_name
        employee.position = position or None
        employee.email = email or None

        audit(
            "EMPLOYEE_UPDATED",
            entity_type="Employee",
            entity_id=employee.id,
            details={"department_id": employee.department_id, "full_name": employee.full_name},
        )

        db.session.commit()

        flash(
            "Данные сотрудника изменены.",
            "success",
        )

        return redirect(url_for("employees.employees"))

    return render_template(
        "employees/form.html",
        employee=employee,
    )


@employees_bp.route(
    "/<int:employee_id>/archive",
    methods=["POST"],
)
@department_head_required
def archive_employee(employee_id):
    employee = get_employee(employee_id)

    if employee is None:
        return redirect(url_for("employees.employees"))

    employee.is_active = False

    audit(
        "EMPLOYEE_ARCHIVED",
        entity_type="Employee",
        entity_id=employee.id,
        details={"department_id": employee.department_id},
    )

    db.session.commit()

    flash(
        "Сотрудник архивирован.",
        "success",
    )

    return redirect(url_for("employees.employees"))


@employees_bp.route(
    "/<int:employee_id>/restore",
    methods=["POST"],
)
@department_head_required
def restore_employee(employee_id):
    employee = get_employee(employee_id)

    if employee is None:
        return redirect(url_for("employees.employees"))

    employee.is_active = True

    audit(
        "EMPLOYEE_RESTORED",
        entity_type="Employee",
        entity_id=employee.id,
        details={"department_id": employee.department_id},
    )

    db.session.commit()

    flash(
        "Сотрудник восстановлен.",
        "success",
    )

    return redirect(url_for("employees.employees"))
