from datetime import date, datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func, select

from app.auth import admin_required, department_head_required, roles_required
from app.extensions import db
from app.models import Employee, Plan, PlanItem, PlanItemAuthor, PlanVersion, ReferenceValue


plans_bp = Blueprint(
    "plans",
    __name__,
    url_prefix="/plans",
)


PLAN_STATUS_DRAFT = "DRAFT"
PLAN_STATUS_SUBMITTED = "SUBMITTED"
PLAN_STATUS_RETURNED = "RETURNED"
PLAN_STATUS_APPROVED = "APPROVED"

PLAN_ITEM_STATUS_PLANNED = "PLANNED"

PLAN_EDITABLE_STATUSES = {
    PLAN_STATUS_DRAFT,
    PLAN_STATUS_RETURNED,
}


def next_plan_year():
    return date.today().year + 1


def get_reference_values(reference_type):
    return db.session.scalars(
        select(ReferenceValue)
        .where(
            ReferenceValue.type == reference_type,
            ReferenceValue.is_active.is_(True),
        )
        .order_by(
            ReferenceValue.sort_order,
            ReferenceValue.name_ru,
        )
    ).all()


def get_department_employees(department_id):
    return db.session.scalars(
        select(Employee)
        .where(
            Employee.department_id == department_id,
            Employee.is_active.is_(True),
        )
        .order_by(Employee.full_name)
    ).all()


def get_plan(plan_id):
    plan = db.session.get(Plan, plan_id)

    if plan is None:
        flash("План не найден.", "danger")
        return None

    return plan


def get_department_head_plan(plan_id):
    plan = get_plan(plan_id)

    if plan is None:
        return None

    if current_user.department_id is None:
        flash(
            "У пользователя не указана кафедра.",
            "danger",
        )
        return None

    if plan.department_id != current_user.department_id:
        flash(
            "У вас нет доступа к этому плану.",
            "danger",
        )
        return None

    return plan


def get_next_version_number(plan):
    current_max = db.session.scalar(
        select(func.max(PlanVersion.version_number))
        .where(PlanVersion.plan_id == plan.id)
    )

    return (current_max or 0) + 1


def serialize_plan(plan):
    return {
        "id": plan.id,
        "department_id": plan.department_id,
        "department_name": plan.department.name,
        "year": plan.year,
        "status": plan.status,
        "created_by": plan.created_by,
        "created_by_name": plan.creator.full_name,
        "submitted_at": (
            plan.submitted_at.isoformat()
            if plan.submitted_at
            else None
        ),
        "approved_at": (
            plan.approved_at.isoformat()
            if plan.approved_at
            else None
        ),
        "items": [
            {
                "id": item.id,
                "title": item.title,
                "publication_type": {
                    "id": item.publication_type.id,
                    "code": item.publication_type.code,
                    "name_ru": item.publication_type.name_ru,
                    "name_kk": item.publication_type.name_kk,
                },
                "journal": item.journal,
                "quartile": (
                    {
                        "id": item.quartile.id,
                        "code": item.quartile.code,
                        "name_ru": item.quartile.name_ru,
                        "name_kk": item.quartile.name_kk,
                    }
                    if item.quartile
                    else None
                ),
                "planned_date": (
                    item.planned_date.isoformat()
                    if item.planned_date
                    else None
                ),
                "status": item.status,
                "authors": [
                    {
                        "id": link.employee.id,
                        "full_name": link.employee.full_name,
                        "position": link.employee.position,
                    }
                    for link in item.author_links
                ],
            }
            for item in plan.items
        ],
    }


def create_plan_version(plan, status, comment=None):
    version = PlanVersion(
        plan_id=plan.id,
        version_number=get_next_version_number(plan),
        created_by=current_user.id,
        status=status,
        comment=comment,
        data=serialize_plan(plan),
    )

    db.session.add(version)

    return version


def editable_plan_required(plan):
    if plan.status not in PLAN_EDITABLE_STATUSES:
        flash(
            "Этот план нельзя редактировать в текущем статусе.",
            "danger",
        )
        return False

    return True


@plans_bp.route("/")
@roles_required("ADMIN", "DEPARTMENT_HEAD")
def plans():
    if current_user.role == "DEPARTMENT_HEAD":
        if current_user.department_id is None:
            flash(
                "У пользователя не указана кафедра.",
                "danger",
            )
            return redirect(url_for("main.index"))

        plans_list = db.session.scalars(
            select(Plan)
            .where(
                Plan.department_id == current_user.department_id,
            )
            .order_by(Plan.year.desc())
        ).all()

        return render_template(
            "plans/list.html",
            plans=plans_list,
            monitor=False,
        )

    plans_list = db.session.scalars(
        select(Plan)
        .order_by(
            Plan.year.desc(),
            Plan.department_id,
        )
    ).all()

    return render_template(
        "plans/list.html",
        plans=plans_list,
        monitor=True,
    )


@plans_bp.route("/create", methods=["GET", "POST"])
@department_head_required
def create_plan():
    if current_user.department_id is None:
        flash(
            "У пользователя не указана кафедра.",
            "danger",
        )
        return redirect(url_for("main.index"))

    year = next_plan_year()

    existing_plan = db.session.scalar(
        select(Plan).where(
            Plan.department_id == current_user.department_id,
            Plan.year == year,
        )
    )

    if existing_plan is not None:
        flash(
            f"План на {year} год уже существует.",
            "warning",
        )
        return redirect(
            url_for(
                "plans.plan_detail",
                plan_id=existing_plan.id,
            )
        )

    if request.method == "POST":
        plan = Plan(
            department_id=current_user.department_id,
            year=year,
            status=PLAN_STATUS_DRAFT,
            created_by=current_user.id,
        )

        db.session.add(plan)
        db.session.commit()

        flash(
            f"Черновик плана на {year} год создан.",
            "success",
        )

        return redirect(
            url_for(
                "plans.plan_detail",
                plan_id=plan.id,
            )
        )

    return render_template(
        "plans/create.html",
        year=year,
    )


@plans_bp.route("/<int:plan_id>")
@roles_required("ADMIN", "DEPARTMENT_HEAD")
def plan_detail(plan_id):
    plan = get_plan(plan_id)

    if plan is None:
        return redirect(url_for("plans.plans"))

    if (
        current_user.role == "DEPARTMENT_HEAD"
        and plan.department_id != current_user.department_id
    ):
        flash(
            "У вас нет доступа к этому плану.",
            "danger",
        )
        return redirect(url_for("plans.plans"))

    versions = db.session.scalars(
        select(PlanVersion)
        .where(
            PlanVersion.plan_id == plan.id,
        )
        .order_by(
            PlanVersion.version_number.desc(),
        )
    ).all()

    return render_template(
        "plans/detail.html",
        plan=plan,
        versions=versions,
        monitor=current_user.role == "ADMIN",
    )


@plans_bp.route(
    "/<int:plan_id>/items/create",
    methods=["GET", "POST"],
)
@department_head_required
def create_plan_item(plan_id):
    plan = get_department_head_plan(plan_id)

    if plan is None:
        return redirect(url_for("plans.plans"))

    if not editable_plan_required(plan):
        return redirect(
            url_for(
                "plans.plan_detail",
                plan_id=plan.id,
            )
        )

    publication_types = get_reference_values("PUBLICATION_TYPE")
    quartiles = get_reference_values("QUARTILE")
    employees = get_department_employees(
        current_user.department_id
    )

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        publication_type_id = request.form.get(
            "publication_type_id",
            "",
        ).strip()
        journal = request.form.get("journal", "").strip()
        quartile_id = request.form.get(
            "quartile_id",
            "",
        ).strip()
        planned_date = request.form.get(
            "planned_date",
            "",
        ).strip()

        author_ids = request.form.getlist("author_ids")

        errors = []

        if not title:
            errors.append(
                "Введите название публикации."
            )

        try:
            publication_type_id_value = int(
                publication_type_id
            )
        except ValueError:
            publication_type_id_value = None
            errors.append(
                "Выберите тип публикации."
            )

        publication_type = None

        if publication_type_id_value is not None:
            publication_type = db.session.scalar(
                select(ReferenceValue).where(
                    ReferenceValue.id == publication_type_id_value,
                    ReferenceValue.type == "PUBLICATION_TYPE",
                    ReferenceValue.is_active.is_(True),
                )
            )

            if publication_type is None:
                errors.append(
                    "Выбран некорректный тип публикации."
                )

        quartile = None

        if quartile_id:
            try:
                quartile_id_value = int(quartile_id)
            except ValueError:
                quartile_id_value = None
                errors.append(
                    "Выбран некорректный квартиль."
                )

            if quartile_id_value is not None:
                quartile = db.session.scalar(
                    select(ReferenceValue).where(
                        ReferenceValue.id == quartile_id_value,
                        ReferenceValue.type == "QUARTILE",
                        ReferenceValue.is_active.is_(True),
                    )
                )

                if quartile is None:
                    errors.append(
                        "Выбран некорректный квартиль."
                    )

        planned_date_value = None

        if planned_date:
            try:
                planned_date_value = date.fromisoformat(
                    planned_date
                )
            except ValueError:
                errors.append(
                    "Введите корректную планируемую дату."
                )

        selected_employee_ids = set()

        for author_id in author_ids:
            try:
                selected_employee_ids.add(int(author_id))
            except ValueError:
                errors.append(
                    "Выбран некорректный автор."
                )

        employees_by_id = {
            employee.id: employee
            for employee in employees
        }

        for employee_id in selected_employee_ids:
            if employee_id not in employees_by_id:
                errors.append(
                    "Нельзя выбрать сотрудника другой кафедры."
                )
                break

        if errors:
            for error in errors:
                flash(error, "danger")

            return render_template(
                "plans/item_form.html",
                plan=plan,
                item=None,
                publication_types=publication_types,
                quartiles=quartiles,
                employees=employees,
                selected_author_ids=selected_employee_ids,
            )

        item = PlanItem(
            plan_id=plan.id,
            title=title,
            publication_type_id=publication_type.id,
            journal=journal or None,
            quartile_id=(
                quartile.id
                if quartile
                else None
            ),
            planned_date=planned_date_value,
            status=PLAN_ITEM_STATUS_PLANNED,
        )

        db.session.add(item)
        db.session.flush()

        for employee_id in selected_employee_ids:
            db.session.add(
                PlanItemAuthor(
                    plan_item_id=item.id,
                    employee_id=employee_id,
                )
            )

        db.session.commit()

        flash(
            "Пункт плана добавлен.",
            "success",
        )

        return redirect(
            url_for(
                "plans.plan_detail",
                plan_id=plan.id,
            )
        )

    return render_template(
        "plans/item_form.html",
        plan=plan,
        item=None,
        publication_types=publication_types,
        quartiles=quartiles,
        employees=employees,
        selected_author_ids=set(),
    )


@plans_bp.route(
    "/<int:plan_id>/items/<int:item_id>/edit",
    methods=["GET", "POST"],
)
@department_head_required
def edit_plan_item(plan_id, item_id):
    plan = get_department_head_plan(plan_id)

    if plan is None:
        return redirect(url_for("plans.plans"))

    if not editable_plan_required(plan):
        return redirect(
            url_for(
                "plans.plan_detail",
                plan_id=plan.id,
            )
        )

    item = db.session.get(PlanItem, item_id)

    if item is None or item.plan_id != plan.id:
        flash(
            "Пункт плана не найден.",
            "danger",
        )
        return redirect(
            url_for(
                "plans.plan_detail",
                plan_id=plan.id,
            )
        )

    publication_types = get_reference_values("PUBLICATION_TYPE")
    quartiles = get_reference_values("QUARTILE")
    employees = get_department_employees(
        current_user.department_id
    )

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        publication_type_id = request.form.get(
            "publication_type_id",
            "",
        ).strip()
        journal = request.form.get("journal", "").strip()
        quartile_id = request.form.get(
            "quartile_id",
            "",
        ).strip()
        planned_date = request.form.get(
            "planned_date",
            "",
        ).strip()

        author_ids = request.form.getlist("author_ids")

        errors = []

        if not title:
            errors.append(
                "Введите название публикации."
            )

        try:
            publication_type_id_value = int(
                publication_type_id
            )
        except ValueError:
            publication_type_id_value = None
            errors.append(
                "Выберите тип публикации."
            )

        publication_type = None

        if publication_type_id_value is not None:
            publication_type = db.session.scalar(
                select(ReferenceValue).where(
                    ReferenceValue.id == publication_type_id_value,
                    ReferenceValue.type == "PUBLICATION_TYPE",
                    ReferenceValue.is_active.is_(True),
                )
            )

            if publication_type is None:
                errors.append(
                    "Выбран некорректный тип публикации."
                )

        quartile = None

        if quartile_id:
            try:
                quartile_id_value = int(quartile_id)
            except ValueError:
                quartile_id_value = None
                errors.append(
                    "Выбран некорректный квартиль."
                )

            if quartile_id_value is not None:
                quartile = db.session.scalar(
                    select(ReferenceValue).where(
                        ReferenceValue.id == quartile_id_value,
                        ReferenceValue.type == "QUARTILE",
                        ReferenceValue.is_active.is_(True),
                    )
                )

                if quartile is None:
                    errors.append(
                        "Выбран некорректный квартиль."
                    )

        planned_date_value = None

        if planned_date:
            try:
                planned_date_value = date.fromisoformat(
                    planned_date
                )
            except ValueError:
                errors.append(
                    "Введите корректную планируемую дату."
                )

        selected_employee_ids = set()

        for author_id in author_ids:
            try:
                selected_employee_ids.add(int(author_id))
            except ValueError:
                errors.append(
                    "Выбран некорректный автор."
                )

        employees_by_id = {
            employee.id: employee
            for employee in employees
        }

        for employee_id in selected_employee_ids:
            if employee_id not in employees_by_id:
                errors.append(
                    "Нельзя выбрать сотрудника другой кафедры."
                )
                break

        if errors:
            for error in errors:
                flash(error, "danger")

            return render_template(
                "plans/item_form.html",
                plan=plan,
                item=item,
                publication_types=publication_types,
                quartiles=quartiles,
                employees=employees,
                selected_author_ids=selected_employee_ids,
            )

        item.title = title
        item.publication_type_id = publication_type.id
        item.journal = journal or None
        item.quartile_id = (
            quartile.id
            if quartile
            else None
        )
        item.planned_date = planned_date_value

        item.author_links.clear()

        for employee_id in selected_employee_ids:
            item.author_links.append(
                PlanItemAuthor(
                    employee_id=employee_id,
                )
            )

        db.session.commit()

        flash(
            "Пункт плана изменён.",
            "success",
        )

        return redirect(
            url_for(
                "plans.plan_detail",
                plan_id=plan.id,
            )
        )

    selected_author_ids = {
        link.employee_id
        for link in item.author_links
    }

    return render_template(
        "plans/item_form.html",
        plan=plan,
        item=item,
        publication_types=publication_types,
        quartiles=quartiles,
        employees=employees,
        selected_author_ids=selected_author_ids,
    )


@plans_bp.route(
    "/<int:plan_id>/items/<int:item_id>/delete",
    methods=["POST"],
)
@department_head_required
def delete_plan_item(plan_id, item_id):
    plan = get_department_head_plan(plan_id)

    if plan is None:
        return redirect(url_for("plans.plans"))

    if not editable_plan_required(plan):
        return redirect(
            url_for(
                "plans.plan_detail",
                plan_id=plan.id,
            )
        )

    item = db.session.get(PlanItem, item_id)

    if item is None or item.plan_id != plan.id:
        flash(
            "Пункт плана не найден.",
            "danger",
        )
        return redirect(
            url_for(
                "plans.plan_detail",
                plan_id=plan.id,
            )
        )

    db.session.delete(item)
    db.session.commit()

    flash(
        "Пункт плана удалён.",
        "success",
    )

    return redirect(
        url_for(
            "plans.plan_detail",
            plan_id=plan.id,
        )
    )


@plans_bp.route(
    "/<int:plan_id>/submit",
    methods=["POST"],
)
@department_head_required
def submit_plan(plan_id):
    plan = get_department_head_plan(plan_id)

    if plan is None:
        return redirect(url_for("plans.plans"))

    if plan.status not in {
        PLAN_STATUS_DRAFT,
        PLAN_STATUS_RETURNED,
    }:
        flash(
            "Этот план нельзя отправить на согласование.",
            "danger",
        )
        return redirect(
            url_for(
                "plans.plan_detail",
                plan_id=plan.id,
            )
        )

    if not plan.items:
        flash(
            "Нельзя отправить пустой план. Добавьте хотя бы одну публикацию.",
            "danger",
        )
        return redirect(
            url_for(
                "plans.plan_detail",
                plan_id=plan.id,
            )
        )

    plan.status = PLAN_STATUS_SUBMITTED
    plan.submitted_at = datetime.utcnow()
    plan.approved_at = None

    create_plan_version(
        plan=plan,
        status=PLAN_STATUS_SUBMITTED,
    )

    db.session.commit()

    flash(
        "План отправлен администратору на согласование.",
        "success",
    )

    return redirect(
        url_for(
            "plans.plan_detail",
            plan_id=plan.id,
        )
    )


@plans_bp.route(
    "/<int:plan_id>/approve",
    methods=["POST"],
)
@admin_required
def approve_plan(plan_id):
    plan = get_plan(plan_id)

    if plan is None:
        return redirect(url_for("plans.plans"))

    if plan.status != PLAN_STATUS_SUBMITTED:
        flash(
            "Одобрить можно только план, находящийся на рассмотрении.",
            "danger",
        )
        return redirect(
            url_for(
                "plans.plan_detail",
                plan_id=plan.id,
            )
        )

    plan.status = PLAN_STATUS_APPROVED
    plan.approved_at = datetime.utcnow()

    create_plan_version(
        plan=plan,
        status=PLAN_STATUS_APPROVED,
    )

    db.session.commit()

    flash(
        "План одобрен.",
        "success",
    )

    return redirect(
        url_for(
            "plans.plan_detail",
            plan_id=plan.id,
        )
    )


@plans_bp.route(
    "/<int:plan_id>/return",
    methods=["POST"],
)
@admin_required
def return_plan(plan_id):
    plan = get_plan(plan_id)

    if plan is None:
        return redirect(url_for("plans.plans"))

    if plan.status != PLAN_STATUS_SUBMITTED:
        flash(
            "На доработку можно вернуть только план, находящийся на рассмотрении.",
            "danger",
        )
        return redirect(
            url_for(
                "plans.plan_detail",
                plan_id=plan.id,
            )
        )

    comment = request.form.get("comment", "").strip()

    if not comment:
        flash(
            "При возврате плана необходимо указать замечания.",
            "danger",
        )
        return redirect(
            url_for(
                "plans.plan_detail",
                plan_id=plan.id,
            )
        )

    plan.status = PLAN_STATUS_RETURNED
    plan.approved_at = None

    create_plan_version(
        plan=plan,
        status=PLAN_STATUS_RETURNED,
        comment=comment,
    )

    db.session.commit()

    flash(
        "План возвращён заведующему на доработку.",
        "success",
    )

    return redirect(
        url_for(
            "plans.plan_detail",
            plan_id=plan.id,
        )
    )