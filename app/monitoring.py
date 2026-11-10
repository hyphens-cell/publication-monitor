from flask import Blueprint, abort, render_template, request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from app.auth import roles_required
from app.extensions import db
from app.models import (
    Department,
    Plan,
    PlanItem,
    Publication,
)
from app.progress import ASSESSMENTS, calculate_progress, get_workload_rows, plan_progress

MONITORING_PLAN_STATUS_APPROVED = "APPROVED"

PUBLICATION_VERIFICATION_PENDING = "PENDING"
PUBLICATION_VERIFICATION_APPROVED = "APPROVED"
PUBLICATION_VERIFICATION_RETURNED = "RETURNED"
PUBLICATION_VERIFICATION_DUPLICATE = "DUPLICATE"


monitoring_bp = Blueprint(
    "monitoring",
    __name__,
    url_prefix="/monitoring",
)


get_plan_progress = plan_progress


def get_department_progress(
    department: Department,
    year: int | None = None,
) -> dict:
    approved_plans = [
        plan
        for plan in department.plans
        if (
            (plan.status == MONITORING_PLAN_STATUS_APPROVED or plan.approved_snapshot is not None)
            and (year is None or plan.year == year)
        )
    ]

    planned_count = 0

    actual_count = 0
    created_count = 0
    pending_count = 0
    returned_count = 0
    duplicate_count = 0

    for plan in approved_plans:
        progress = get_plan_progress(plan)

        planned_count += progress["planned_count"]
        actual_count += progress["actual_count"]
        created_count += progress["created_count"]
        pending_count += progress["pending_count"]
        returned_count += progress["returned_count"]
        duplicate_count += progress["duplicate_count"]

    return {
        "department": department,
        "plans_count": len(approved_plans),
        "planned_count": planned_count,
        "created_count": created_count,
        "actual_count": actual_count,
        "pending_count": pending_count,
        "returned_count": returned_count,
        "duplicate_count": duplicate_count,
        "progress": calculate_progress(
            planned_count,
            actual_count,
        ),
    }


def get_monitoring_summary(
    year: int | None = None,
    department_id: int | None = None,
) -> dict:
    department_query = select(Department)

    if department_id is not None:
        department_query = department_query.where(
            Department.id == department_id,
        )

    departments = db.session.scalars(
        department_query.order_by(
            Department.name,
        )
    ).all()

    plan_filter_conditions = []

    if year is not None:
        plan_filter_conditions.append(Plan.year == year)

    if department_id is not None:
        plan_filter_conditions.append(Plan.department_id == department_id)

    plan_counts = dict(
        db.session.execute(
            select(Plan.status, func.count(Plan.id)).where(*plan_filter_conditions).group_by(Plan.status)
        ).all()
    )
    plans_count = sum(plan_counts.values())
    publication_query = (
        select(Publication.verification_status, func.count(Publication.id))
        .join(Publication.plan_item)
        .join(PlanItem.plan)
        .where(*plan_filter_conditions)
        .group_by(Publication.verification_status)
    )
    publication_counts = dict(db.session.execute(publication_query).all())
    publications_count = sum(publication_counts.values())
    pending_publications_count = publication_counts.get(PUBLICATION_VERIFICATION_PENDING, 0)
    approved_publications_count = publication_counts.get(PUBLICATION_VERIFICATION_APPROVED, 0)
    returned_publications_count = publication_counts.get(PUBLICATION_VERIFICATION_RETURNED, 0)
    duplicate_publications_count = publication_counts.get(PUBLICATION_VERIFICATION_DUPLICATE, 0)

    approved_plan_query = (
        select(Plan)
        .options(
            joinedload(Plan.department),
            selectinload(Plan.items).joinedload(PlanItem.publication),
            selectinload(Plan.items).joinedload(PlanItem.publication_type),
        )
        .where(
            or_(Plan.status == MONITORING_PLAN_STATUS_APPROVED, Plan.approved_snapshot.is_not(None)),
        )
    )

    if year is not None:
        approved_plan_query = approved_plan_query.where(Plan.year == year)

    if department_id is not None:
        approved_plan_query = approved_plan_query.where(Plan.department_id == department_id)

    approved_plans = db.session.scalars(
        approved_plan_query.order_by(
            Plan.year.desc(),
            Plan.department_id,
            Plan.id,
        )
    ).all()

    approved_plans_count = len(approved_plans)
    workload = get_workload_rows(plans=approved_plans)
    rows_by_plan = {}
    for row in workload:
        rows_by_plan.setdefault(row["plan"].id, []).append(row)
    plan_progress = [get_plan_progress(plan, rows=rows_by_plan.get(plan.id, [])) for plan in approved_plans]

    planned_count = sum(item["planned_count"] for item in plan_progress)

    actual_count = sum(item["actual_count"] for item in plan_progress)

    department_progress = []
    for department in departments:
        plans = [item for item in plan_progress if item["plan"].department_id == department.id]
        item = {
            key: sum(plan[key] for plan in plans)
            for key in (
                "planned_count",
                "created_count",
                "actual_count",
                "pending_count",
                "returned_count",
                "duplicate_count",
            )
        }
        item.update(
            department=department,
            plans_count=len(plans),
            progress=calculate_progress(item["planned_count"], item["actual_count"]),
        )
        department_progress.append(item)

    return {
        "plans_count": plans_count,
        "approved_plans_count": approved_plans_count,
        "publications_count": publications_count,
        "pending_publications_count": pending_publications_count,
        "approved_publications_count": approved_publications_count,
        "returned_publications_count": returned_publications_count,
        "duplicate_publications_count": duplicate_publications_count,
        "planned_count": planned_count,
        "actual_count": actual_count,
        "overall_progress": calculate_progress(
            planned_count,
            actual_count,
        ),
        "department_progress": department_progress,
        "plan_progress": plan_progress,
    }


def get_attention_publications(
    year: int | None = None,
    department_id: int | None = None,
) -> dict:
    query = (
        select(Publication)
        .options(
            joinedload(Publication.department), joinedload(Publication.plan_item).joinedload(PlanItem.plan)
        )
        .where(
            Publication.verification_status.in_(
                [
                    PUBLICATION_VERIFICATION_PENDING,
                    PUBLICATION_VERIFICATION_RETURNED,
                    PUBLICATION_VERIFICATION_DUPLICATE,
                ]
            )
        )
        .join(Publication.plan_item)
        .join(PlanItem.plan)
    )

    if year is not None:
        query = query.where(Plan.year == year)

    if department_id is not None:
        query = query.where(Plan.department_id == department_id)

    publications = db.session.scalars(
        query.order_by(
            Publication.updated_at.desc(),
            Publication.id.desc(),
        )
    ).all()

    return {
        "pending": [
            publication
            for publication in publications
            if publication.verification_status == PUBLICATION_VERIFICATION_PENDING
        ],
        "returned": [
            publication
            for publication in publications
            if publication.verification_status == PUBLICATION_VERIFICATION_RETURNED
        ],
        "duplicate": [
            publication
            for publication in publications
            if publication.verification_status == PUBLICATION_VERIFICATION_DUPLICATE
        ],
    }


@monitoring_bp.route("/")
@roles_required("ADMIN")
def dashboard():
    year_value = request.args.get(
        "year",
        "",
    ).strip()

    department_id_value = request.args.get(
        "department_id",
        "",
    ).strip()

    year = None
    department_id = None

    if year_value:
        try:
            year = int(year_value)
        except ValueError:
            abort(400)

    if department_id_value:
        try:
            department_id = int(department_id_value)
        except ValueError:
            abort(400)

    summary = get_monitoring_summary(
        year=year,
        department_id=department_id,
    )

    attention = get_attention_publications(
        year=year,
        department_id=department_id,
    )
    years = db.session.scalars(select(Plan.year).distinct().order_by(Plan.year.desc())).all()

    departments = db.session.scalars(
        select(Department)
        .where(
            Department.is_active.is_(True),
        )
        .order_by(
            Department.name,
        )
    ).all()

    return render_template(
        "monitoring/dashboard.html",
        summary=summary,
        attention=attention,
        years=years,
        departments=departments,
        assessments=ASSESSMENTS,
        selected_year=year,
        selected_department_id=department_id,
    )
