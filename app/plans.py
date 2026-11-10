from datetime import date, datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload

from app.access import ensure_department_access
from app.audit import audit
from app.auth import (
    ROLE_ADMIN,
    ROLE_DEPARTMENT_HEAD,
    admin_required,
    department_head_required,
    roles_required,
)
from app.discussion import add_comment, comments_for, notify_participants
from app.extensions import db
from app.models import Employee, Plan, PlanItem, PlanItemAuthor, PlanVersion
from app.progress import ASSESSMENTS, plan_progress
from app.services.catalogue import get_reference_values
from app.services.listing import paginate, search_term, sort_order
from app.services.loading import plan_detail_options
from app.services.plan_workflow import (
    create_plan_version as create_plan_version,
)
from app.services.plan_workflow import (
    get_next_version_number as get_next_version_number,
)
from app.services.plan_workflow import (
    serialize_plan as serialize_plan,
)
from app.services.publication_workflow import create_publications_from_plan
from app.services.validation import validate_plan_item

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


def get_department_employees(department_id, selected_ids=()):
    return db.session.scalars(
        select(Employee)
        .where(
            Employee.department_id == department_id,
            Employee.is_active.is_(True) | Employee.id.in_(selected_ids),
        )
        .order_by(Employee.full_name)
    ).all()


def get_plan(plan_id):
    query = select(Plan).where(Plan.id == plan_id).options(*plan_detail_options())
    if request.method == "POST":
        query = query.with_for_update(of=Plan)
    plan = db.session.scalar(query)

    if plan is None:
        flash("План не найден.", "danger")
        return None

    return plan


def get_accessible_plan(plan_id):
    plan = get_plan(plan_id)

    if plan is None:
        return None

    ensure_department_access(plan.department_id)

    return plan


def editable_plan_required(plan):
    if plan.status not in PLAN_EDITABLE_STATUSES:
        flash(
            "Этот план нельзя редактировать в текущем статусе.",
            "danger",
        )
        return False

    return True


@plans_bp.route("/")
@roles_required(ROLE_ADMIN, ROLE_DEPARTMENT_HEAD)
def plans():
    department_id = None

    if current_user.role == ROLE_DEPARTMENT_HEAD:
        department_id = current_user.department_id

        if department_id is None:
            flash(
                "У пользователя не указана кафедра.",
                "danger",
            )
            return redirect(url_for("main.index"))

    query = select(Plan)

    if department_id is not None:
        query = query.where(Plan.department_id == department_id)

    term = search_term(request.args)
    if term:
        query = query.where(Plan.items.any(PlanItem.title.ilike(f"%{term}%", escape="\\")))
    order = sort_order(
        request.args,
        {"year_desc": Plan.year.desc(), "year": Plan.year.asc(), "status": Plan.status.asc()},
        "year_desc",
    )
    pagination = paginate(
        query.options(joinedload(Plan.department), selectinload(Plan.items)).order_by(
            order, Plan.department_id, Plan.id
        ),
        request.args,
    )

    return render_template(
        "plans/list.html",
        plans=pagination.items,
        pagination=pagination,
        monitor=current_user.role == ROLE_ADMIN,
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
        db.session.flush()

        audit(
            "PLAN_CREATED",
            entity_type="Plan",
            entity_id=plan.id,
            details={
                "department_id": plan.department_id,
                "year": plan.year,
                "status": plan.status,
            },
        )

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
@roles_required(ROLE_ADMIN, ROLE_DEPARTMENT_HEAD)
def plan_detail(plan_id):
    plan = get_accessible_plan(plan_id)

    if plan is None:
        return redirect(url_for("plans.plans"))

    versions = db.session.scalars(
        select(PlanVersion)
        .options(joinedload(PlanVersion.creator))
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
        monitor=current_user.role == ROLE_ADMIN,
        comments=comments_for("PLAN", plan.id),
        progress=plan_progress(plan),
        assessments=ASSESSMENTS,
    )


@plans_bp.route(
    "/<int:plan_id>/items/create",
    methods=["GET", "POST"],
)
@department_head_required
def create_plan_item(plan_id):
    plan = get_accessible_plan(plan_id)

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
    employees = get_department_employees(current_user.department_id)

    if request.method == "POST":
        values, errors = validate_plan_item(request.form, publication_types, quartiles, employees)
        title = values.title
        journal = values.journal
        planned_date_value = values.planned_date
        selected_employee_ids = set(values.author_ids)
        publication_type = next(
            (item for item in publication_types if item.id == values.publication_type_id), None
        )
        quartile = next((item for item in quartiles if item.id == values.quartile_id), None)

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
            quartile_id=(quartile.id if quartile else None),
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

        audit(
            "PLAN_ITEM_CREATED",
            entity_type="PlanItem",
            entity_id=item.id,
            details={
                "plan_id": plan.id,
                "title": item.title,
                "publication_type_id": item.publication_type_id,
                "quartile_id": item.quartile_id,
                "planned_date": (item.planned_date.isoformat() if item.planned_date else None),
                "author_ids": sorted(selected_employee_ids),
            },
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
    plan = get_accessible_plan(plan_id)

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
        current_user.department_id, [link.employee_id for link in item.author_links]
    )

    if request.method == "POST":
        values, errors = validate_plan_item(request.form, publication_types, quartiles, employees)
        title = values.title
        journal = values.journal
        planned_date_value = values.planned_date
        selected_employee_ids = set(values.author_ids)
        publication_type = next(
            (item for item in publication_types if item.id == values.publication_type_id), None
        )
        quartile = next((item for item in quartiles if item.id == values.quartile_id), None)

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
        item.quartile_id = quartile.id if quartile else None
        item.planned_date = planned_date_value

        item.author_links.clear()

        for employee_id in selected_employee_ids:
            item.author_links.append(
                PlanItemAuthor(
                    employee_id=employee_id,
                )
            )

        audit(
            "PLAN_ITEM_UPDATED",
            entity_type="PlanItem",
            entity_id=item.id,
            details={
                "plan_id": plan.id,
                "title": item.title,
                "publication_type_id": item.publication_type_id,
                "quartile_id": item.quartile_id,
                "planned_date": (item.planned_date.isoformat() if item.planned_date else None),
                "author_ids": sorted(selected_employee_ids),
            },
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

    selected_author_ids = {link.employee_id for link in item.author_links}

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
    plan = get_accessible_plan(plan_id)

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

    audit(
        "PLAN_ITEM_DELETED",
        entity_type="PlanItem",
        entity_id=item.id,
        details={
            "plan_id": plan.id,
            "title": item.title,
            "publication_type_id": item.publication_type_id,
        },
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
    plan = get_accessible_plan(plan_id)

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
    notify_participants(plan, "PLAN", "План на согласовании", str(plan.year), audience="monitor")

    audit(
        "PLAN_SUBMITTED",
        entity_type="Plan",
        entity_id=plan.id,
        details={
            "department_id": plan.department_id,
            "year": plan.year,
            "status": plan.status,
            "submitted_at": (plan.submitted_at.isoformat() if plan.submitted_at else None),
        },
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

    create_publications_from_plan(
        plan=plan,
        user_id=current_user.id,
    )
    db.session.flush()
    plan.approved_snapshot = serialize_plan(plan)
    plan.correction_requested_at = None
    plan.manual_assessment = None
    plan.assessment_comment = None
    plan.assessed_by = None
    plan.assessed_at = None
    create_plan_version(plan=plan, status=PLAN_STATUS_APPROVED)
    notify_participants(plan, "PLAN", "План одобрен.", str(plan.year), "success", audience="head")

    audit(
        "PLAN_APPROVED",
        entity_type="Plan",
        entity_id=plan.id,
        details={
            "department_id": plan.department_id,
            "year": plan.year,
            "status": plan.status,
            "approved_at": (plan.approved_at.isoformat() if plan.approved_at else None),
        },
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

    if plan.status != PLAN_STATUS_SUBMITTED and not (
        plan.status == PLAN_STATUS_APPROVED and plan.correction_requested_at
    ):
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
    plan.correction_requested_at = None

    create_plan_version(
        plan=plan,
        status=PLAN_STATUS_RETURNED,
        comment=comment,
    )

    add_comment(plan, "PLAN", comment, "План возвращён на доработку")

    audit(
        "PLAN_RETURNED",
        entity_type="Plan",
        entity_id=plan.id,
        details={
            "department_id": plan.department_id,
            "year": plan.year,
            "status": plan.status,
            "comment": comment,
        },
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


@plans_bp.post("/<int:plan_id>/request-correction")
@department_head_required
def request_correction(plan_id):
    plan = get_accessible_plan(plan_id)
    if plan is None:
        abort(404)
    comment = request.form.get("comment", "").strip()
    if plan.status != PLAN_STATUS_APPROVED or plan.correction_requested_at:
        flash("Запрос на корректировку уже отправлен или план не утверждён.", "warning")
    elif not comment or len(comment) > 5000:
        flash("Введите комментарий длиной от 1 до 5000 символов.", "danger")
    else:
        # Older approved plans may not yet have a persisted snapshot.
        if plan.approved_snapshot is None:
            plan.approved_snapshot = serialize_plan(plan)
        plan.correction_requested_at = datetime.utcnow()
        create_plan_version(plan, "CORRECTION_REQUESTED", comment)
        add_comment(plan, "PLAN", comment, "Запрос на корректировку плана")
        audit(
            "PLAN_CORRECTION_REQUESTED", entity_type="Plan", entity_id=plan.id, details={"comment": comment}
        )
        db.session.commit()
        flash("Запрос на корректировку отправлен монитору.", "success")
    return redirect(url_for("plans.plan_detail", plan_id=plan.id))


@plans_bp.post("/<int:plan_id>/decline-correction")
@admin_required
def decline_correction(plan_id):
    plan = get_plan(plan_id)
    if plan is None:
        abort(404)
    comment = request.form.get("comment", "").strip()
    if plan.status != PLAN_STATUS_APPROVED or not plan.correction_requested_at:
        abort(400)
    if not comment or len(comment) > 5000:
        flash("Введите комментарий длиной от 1 до 5000 символов.", "danger")
    else:
        plan.correction_requested_at = None
        create_plan_version(plan, "CORRECTION_DECLINED", comment)
        add_comment(plan, "PLAN", comment, "Запрос на корректировку отклонён")
        audit("PLAN_CORRECTION_DECLINED", entity_type="Plan", entity_id=plan.id, details={"comment": comment})
        db.session.commit()
    return redirect(url_for("plans.plan_detail", plan_id=plan.id))


@plans_bp.post("/<int:plan_id>/assessment")
@admin_required
def assess_plan(plan_id):
    plan = get_plan(plan_id)
    if plan is None:
        abort(404)
    if plan.status != PLAN_STATUS_APPROVED and plan.approved_snapshot is None:
        abort(400)
    assessment = request.form.get("assessment", "")
    comment = request.form.get("comment", "").strip()
    if assessment not in {*ASSESSMENTS, "AUTO"} or not comment or len(comment) > 5000:
        flash("Выберите оценку и укажите пояснение до 5000 символов.", "danger")
    else:
        old_assessment = plan.manual_assessment
        plan.manual_assessment = None if assessment == "AUTO" else assessment
        plan.assessment_comment = comment
        plan.assessed_by = current_user.id
        plan.assessed_at = datetime.utcnow()
        add_comment(plan, "PLAN", comment, "Оценка выполнения плана изменена")
        audit(
            "PLAN_ASSESSMENT_CHANGED",
            entity_type="Plan",
            entity_id=plan.id,
            details={"old": old_assessment, "new": plan.manual_assessment, "comment": comment},
        )
        db.session.commit()
        flash("Оценка сохранена.", "success")
    return redirect(url_for("plans.plan_detail", plan_id=plan.id))


@plans_bp.get("/<int:plan_id>/versions/<int:version_id>")
@roles_required(ROLE_ADMIN, ROLE_DEPARTMENT_HEAD)
def plan_version(plan_id, version_id):
    plan = get_accessible_plan(plan_id)
    version = db.session.get(PlanVersion, version_id)
    if plan is None or version is None or version.plan_id != plan.id:
        abort(404)
    return render_template("plans/version.html", plan=plan, version=version)
