from flask import Blueprint, abort, render_template, request
from flask_login import current_user
from sqlalchemy import func, select

from app.auth import roles_required
from app.extensions import db
from app.models import (
    Department,
    Plan,
    PlanItem,
    Publication,
)


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


def calculate_progress(
    planned_count: int,
    actual_count: int,
) -> float:
    if planned_count <= 0:
        return 0.0

    progress = actual_count / planned_count * 100

    return round(
        min(progress, 100.0),
        2,
    )


def get_plan_progress(plan: Plan) -> dict:
    planned_count = len(plan.items)

    actual_count = sum(
        1
        for item in plan.items
        if (
            item.publication is not None
            and item.publication.verification_status
            == PUBLICATION_VERIFICATION_APPROVED
        )
    )

    pending_count = sum(
        1
        for item in plan.items
        if (
            item.publication is not None
            and item.publication.verification_status
            == PUBLICATION_VERIFICATION_PENDING
        )
    )

    returned_count = sum(
        1
        for item in plan.items
        if (
            item.publication is not None
            and item.publication.verification_status
            == PUBLICATION_VERIFICATION_RETURNED
        )
    )

    duplicate_count = sum(
        1
        for item in plan.items
        if (
            item.publication is not None
            and item.publication.verification_status
            == PUBLICATION_VERIFICATION_DUPLICATE
        )
    )

    created_count = sum(
        1
        for item in plan.items
        if item.publication is not None
    )

    return {
        "plan": plan,
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


def get_department_progress(
    department: Department,
    year: int | None = None,
) -> dict:
    approved_plans = [
        plan
        for plan in department.plans
        if (
            plan.status == MONITORING_PLAN_STATUS_APPROVED
            and (
                year is None
                or plan.year == year
            )
        )
    ]

    planned_count = sum(
        len(plan.items)
        for plan in approved_plans
    )

    actual_count = 0
    created_count = 0
    pending_count = 0
    returned_count = 0
    duplicate_count = 0

    for plan in approved_plans:
        progress = get_plan_progress(plan)

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
    department_query = select(Department).where(
        Department.is_active.is_(True),
    )

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
        plan_filter_conditions.append(
            Plan.year == year
        )

    if department_id is not None:
        plan_filter_conditions.append(
            Plan.department_id == department_id
        )

    plans_query = select(func.count(Plan.id))

    if plan_filter_conditions:
        plans_query = plans_query.where(
            *plan_filter_conditions
        )

    plans_count = db.session.scalar(
        plans_query
    ) or 0

    approved_plans_query = select(
        func.count(Plan.id)
    ).where(
        Plan.status == MONITORING_PLAN_STATUS_APPROVED,
    )

    if plan_filter_conditions:
        approved_plans_query = approved_plans_query.where(
            *plan_filter_conditions
        )

    approved_plans_count = db.session.scalar(
        approved_plans_query
    ) or 0

    publication_query = select(
        func.count(Publication.id)
    ).join(
        Publication.plan_item
    ).join(
        PlanItem.plan
    )

    if year is not None:
        publication_query = publication_query.where(
            Plan.year == year
        )

    if department_id is not None:
        publication_query = publication_query.where(
            Plan.department_id == department_id
        )

    publications_count = db.session.scalar(
        publication_query
    ) or 0

    def publication_status_count(status: str) -> int:
        query = select(
            func.count(Publication.id)
        ).join(
            Publication.plan_item
        ).join(
            PlanItem.plan
        ).where(
            Publication.verification_status == status
        )

        if year is not None:
            query = query.where(
                Plan.year == year
            )

        if department_id is not None:
            query = query.where(
                Plan.department_id == department_id
            )

        return db.session.scalar(query) or 0

    pending_publications_count = publication_status_count(
        PUBLICATION_VERIFICATION_PENDING
    )

    approved_publications_count = publication_status_count(
        PUBLICATION_VERIFICATION_APPROVED
    )

    returned_publications_count = publication_status_count(
        PUBLICATION_VERIFICATION_RETURNED
    )

    duplicate_publications_count = publication_status_count(
        PUBLICATION_VERIFICATION_DUPLICATE
    )

    approved_plan_query = select(Plan).where(
        Plan.status == MONITORING_PLAN_STATUS_APPROVED,
    )

    if year is not None:
        approved_plan_query = approved_plan_query.where(
            Plan.year == year
        )

    if department_id is not None:
        approved_plan_query = approved_plan_query.where(
            Plan.department_id == department_id
        )

    approved_plans = db.session.scalars(
        approved_plan_query.order_by(
            Plan.year.desc(),
            Plan.department_id,
            Plan.id,
        )
    ).all()

    plan_progress = [
        get_plan_progress(plan)
        for plan in approved_plans
    ]

    planned_count = sum(
        item["planned_count"]
        for item in plan_progress
    )

    actual_count = sum(
        item["actual_count"]
        for item in plan_progress
    )

    department_progress = [
        get_department_progress(
            department,
            year=year,
        )
        for department in departments
    ]

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
    query = select(Publication).join(
        Publication.plan_item
    ).join(
        PlanItem.plan
    )

    if year is not None:
        query = query.where(
            Plan.year == year
        )

    if department_id is not None:
        query = query.where(
            Plan.department_id == department_id
        )

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
            if publication.verification_status
            == PUBLICATION_VERIFICATION_PENDING
        ],
        "returned": [
            publication
            for publication in publications
            if publication.verification_status
            == PUBLICATION_VERIFICATION_RETURNED
        ],
        "duplicate": [
            publication
            for publication in publications
            if publication.verification_status
            == PUBLICATION_VERIFICATION_DUPLICATE
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
            department_id = int(
                department_id_value
            )
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
    years = db.session.scalars(
        select(Plan.year)
        .distinct()
        .order_by(
            Plan.year.desc()
        )
    ).all()

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
        selected_year=year,
        selected_department_id=department_id,
    )