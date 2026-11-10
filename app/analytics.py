from flask import Blueprint, abort, render_template, request, send_file
from flask_login import current_user
from sqlalchemy import or_, select

from app.access import (
    ensure_department_access,
    get_scoped_department_id,
)
from app.auth import (
    ROLE_ADMIN,
    ROLE_DEPARTMENT_HEAD,
    roles_required,
)
from app.extensions import db
from app.models import (
    Department,
    Plan,
)
from app.progress import calculate_progress, get_workload_rows
from app.services.analytics_exports import create_analytics_pdf, create_analytics_workbook
from app.services.catalogue import get_reference_values
from app.services.listing import optional_int

ANALYTICS_PLAN_STATUS = "APPROVED"
ANALYTICS_FACT_STATUS = "APPROVED"
PUBLICATION_TYPE_REFERENCE = "PUBLICATION_TYPE"


analytics_bp = Blueprint(
    "analytics",
    __name__,
    url_prefix="/analytics",
)


calculate_percentage = calculate_progress


def parse_optional_int(name):
    return optional_int(request.args, name)


def get_filters():
    year = parse_optional_int("year")
    requested_department_id = parse_optional_int("department_id")
    publication_type_id = parse_optional_int("publication_type_id")

    ensure_department_access(requested_department_id)

    department_id = get_scoped_department_id(requested_department_id)

    return {
        "year": year,
        "department_id": department_id,
        "publication_type_id": publication_type_id,
    }


def get_years():
    query = select(Plan.year).where(
        or_(Plan.status == ANALYTICS_PLAN_STATUS, Plan.approved_snapshot.is_not(None)),
    )
    if current_user.role == ROLE_DEPARTMENT_HEAD:
        query = query.where(
            Plan.department_id == current_user.department_id,
        )

    return db.session.scalars(
        query.distinct().order_by(
            Plan.year.desc(),
        )
    ).all()


def get_departments():
    query = (
        select(Department)
        .where(
            Department.is_active.is_(True),
        )
        .order_by(
            Department.name,
        )
    )

    if current_user.role == ROLE_DEPARTMENT_HEAD:
        if current_user.department_id is None:
            abort(403)

        query = query.where(
            Department.id == current_user.department_id,
        )

    return db.session.scalars(query).all()


def get_publication_types():
    return get_reference_values(PUBLICATION_TYPE_REFERENCE)


def build_analytics_data(filters):
    rows = get_workload_rows(**filters)
    types, departments = {}, {}
    for row in rows:
        plan, publication_type = row["plan"], row["item"]["publication_type"]
        type_summary = types.setdefault(
            publication_type["id"],
            {
                "publication_type_id": publication_type["id"],
                "name_ru": publication_type["name_ru"],
                "name_kk": publication_type["name_kk"],
                "planned_count": 0,
                "actual_count": 0,
            },
        )
        department_summary = departments.setdefault(
            plan.department_id,
            {
                "department_id": plan.department_id,
                "name": plan.department.name,
                "planned_count": 0,
                "actual_count": 0,
            },
        )
        for summary in (type_summary, department_summary):
            summary["planned_count"] += 1
            summary["actual_count"] += row["actual"]
    total = {"planned_count": len(rows), "actual_count": sum(row["actual"] for row in rows)}
    for summary in [total, *types.values(), *departments.values()]:
        summary["progress"] = calculate_percentage(summary["planned_count"], summary["actual_count"])
    return {
        "total": total,
        "by_publication_type": sorted(types.values(), key=lambda item: item["name_ru"]),
        "by_department": sorted(departments.values(), key=lambda item: item["name"]),
    }


@analytics_bp.route("/")
@roles_required(
    ROLE_ADMIN,
    ROLE_DEPARTMENT_HEAD,
)
def dashboard():
    filters = get_filters()

    data = build_analytics_data(filters)

    return render_template(
        "analytics/dashboard.html",
        summary=data["total"],
        by_publication_type=(data["by_publication_type"]),
        by_department=data["by_department"],
        years=get_years(),
        departments=get_departments(),
        publication_types=get_publication_types(),
        selected_year=filters["year"],
        selected_department_id=(filters["department_id"]),
        selected_publication_type_id=(filters["publication_type_id"]),
    )


@analytics_bp.route("/export.xlsx")
@roles_required(
    ROLE_ADMIN,
    ROLE_DEPARTMENT_HEAD,
)
def export_excel():
    data = build_analytics_data(get_filters())
    output = create_analytics_workbook(data)
    return send_file(
        output,
        as_attachment=True,
        download_name=("publication_analytics.xlsx"),
        mimetype=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    )


@analytics_bp.route("/export.pdf")
@roles_required(
    ROLE_ADMIN,
    ROLE_DEPARTMENT_HEAD,
)
def export_pdf():
    data = build_analytics_data(get_filters())
    output = create_analytics_pdf(data)
    return send_file(
        output,
        as_attachment=True,
        download_name=("publication_analytics.pdf"),
        mimetype="application/pdf",
    )
