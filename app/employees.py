from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import select

from app.auth import department_head_required
from app.extensions import db
from app.models import Employee


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

    employees_list = db.session.scalars(
        select(Employee)
        .where(
            Employee.department_id == current_user.department_id,
        )
        .order_by(
            Employee.is_active.desc(),
            Employee.full_name,
        )
    ).all()

    return render_template(
        "employees/list.html",
        employees=employees_list,
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
        full_name = request.form.get("full_name", "").strip()
        position = request.form.get("position", "").strip()
        email = request.form.get("email", "").strip().lower()

        errors = []

        if not full_name:
            errors.append("Введите ФИО сотрудника.")

        if len(full_name) > 255:
            errors.append(
                "ФИО не должно превышать 255 символов."
            )

        if len(position) > 255:
            errors.append(
                "Должность не должна превышать 255 символов."
            )

        if len(email) > 255:
            errors.append(
                "Email не должен превышать 255 символов."
            )

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
        full_name = request.form.get("full_name", "").strip()
        position = request.form.get("position", "").strip()
        email = request.form.get("email", "").strip().lower()

        errors = []

        if not full_name:
            errors.append("Введите ФИО сотрудника.")

        if len(full_name) > 255:
            errors.append(
                "ФИО не должно превышать 255 символов."
            )

        if len(position) > 255:
            errors.append(
                "Должность не должна превышать 255 символов."
            )

        if len(email) > 255:
            errors.append(
                "Email не должен превышать 255 символов."
            )

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

    db.session.commit()

    flash(
        "Сотрудник восстановлен.",
        "success",
    )

    return redirect(url_for("employees.employees"))