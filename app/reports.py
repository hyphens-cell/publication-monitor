from io import BytesIO

from flask import Blueprint, abort, render_template, request, send_file
from flask_login import current_user
from sqlalchemy import or_, select

from app.access import (
    ensure_department_access,
    get_scoped_department_id,
)
from app.auth import (
    ROLE_DEPARTMENT_HEAD,
    roles_required,
)
from app.extensions import db
from app.models import (
    Department,
    Plan,
    PlanItem,
    Publication,
)
from app.services.catalogue import get_reference_values
from app.services.listing import optional_int, paginate, search_term, sort_order
from app.services.loading import publication_report_options
from app.services.report_exports import (
    create_publications_pdf as create_publications_pdf,
)
from app.services.report_exports import (
    create_publications_workbook as create_publications_workbook,
)
from app.services.report_exports import (
    get_indexing_type_name as get_indexing_type_name,
)
from app.services.report_exports import (
    get_pdf_font_paths as get_pdf_font_paths,
)
from app.services.report_exports import (
    get_publication_report_row as get_publication_report_row,
)
from app.services.report_exports import (
    get_quartile_name as get_quartile_name,
)
from app.services.report_exports import (
    register_pdf_fonts as register_pdf_fonts,
)

REPORT_PUBLICATION_STATUSES = {
    "PREPARATION": "Подготовка статьи",
    "SUBMITTED_TO_JOURNAL": "Отправлена в журнал",
    "UNDER_REVIEW": "На рецензировании",
    "REVISION_REQUIRED": "Требуется доработка",
    "ACCEPTED": "Принята к публикации",
    "PUBLISHED": "Опубликована",
    "REJECTED": "Отклонена",
}


REPORT_VERIFICATION_STATUSES = {
    "PENDING": "Ожидает проверки",
    "APPROVED": "Проверена",
    "RETURNED": "Возвращена",
    "DUPLICATE": "Дубликат",
}


REPORT_PLAN_STATUS = "APPROVED"


reports_bp = Blueprint(
    "reports",
    __name__,
    url_prefix="/reports",
)


def parse_optional_int(name):
    return optional_int(request.args, name)


def get_report_departments():
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


def get_report_years():
    query = select(Plan.year).where(
        or_(Plan.status == REPORT_PLAN_STATUS, Plan.approved_snapshot.is_not(None)),
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


def get_report_reference_values(reference_type):
    return get_reference_values(reference_type)


def get_publications_report_filters():
    year = parse_optional_int("year")

    requested_department_id = parse_optional_int("department_id")

    quartile_id = parse_optional_int("quartile_id")

    indexing_type_id = parse_optional_int("indexing_type_id")

    publication_status = request.args.get(
        "publication_status",
        "",
    ).strip()

    verification_status = request.args.get(
        "verification_status",
        "",
    ).strip()

    if publication_status:
        if publication_status not in REPORT_PUBLICATION_STATUSES:
            abort(400)

    if verification_status:
        if verification_status not in REPORT_VERIFICATION_STATUSES:
            abort(400)

    ensure_department_access(requested_department_id)

    department_id = get_scoped_department_id(requested_department_id)

    return {
        "year": year,
        "department_id": department_id,
        "quartile_id": quartile_id,
        "indexing_type_id": indexing_type_id,
        "publication_status": (publication_status or None),
        "verification_status": (verification_status or None),
    }


def build_publications_report_query(
    year=None,
    department_id=None,
    publication_status=None,
    verification_status=None,
    quartile_id=None,
    indexing_type_id=None,
):
    query = (
        select(Publication)
        .options(*publication_report_options())
        .join(
            Publication.plan_item,
        )
        .join(
            PlanItem.plan,
        )
        .join(
            Publication.department,
        )
        .where(
            or_(Plan.status == REPORT_PLAN_STATUS, Plan.approved_snapshot.is_not(None)),
        )
    )

    if year is not None:
        query = query.where(
            Plan.year == year,
        )

    if department_id is not None:
        query = query.where(
            Publication.department_id == department_id,
        )

    if publication_status is not None:
        query = query.where(
            Publication.status == publication_status,
        )

    if verification_status is not None:
        query = query.where(
            Publication.verification_status == verification_status,
        )

    if quartile_id is not None:
        query = query.where(
            Publication.quartile_id == quartile_id,
        )

    if indexing_type_id is not None:
        query = query.where(
            Publication.indexing_type_id == indexing_type_id,
        )

    return query.order_by(
        Plan.year.desc(),
        Publication.department_id,
        Publication.title,
        Publication.id,
    )


def get_filtered_publications_query():
    filters = get_publications_report_filters()
    query = build_publications_report_query(**filters)
    term = search_term(request.args)
    if term:
        query = query.where(
            or_(
                Publication.title.ilike(f"%{term}%", escape="\\"),
                Publication.doi.ilike(f"%{term}%", escape="\\"),
                Publication.journal.ilike(f"%{term}%", escape="\\"),
            )
        )
    order = sort_order(
        request.args,
        {
            "year_desc": Plan.year.desc(),
            "title": Publication.title.asc(),
            "title_desc": Publication.title.desc(),
        },
        "year_desc",
    )
    return query.order_by(None).order_by(order, Publication.department_id, Publication.id), filters


def get_filtered_publications():
    query, filters = get_filtered_publications_query()
    return db.session.scalars(query).all(), filters


@reports_bp.route("/publications")
@roles_required(
    "ADMIN",
    ROLE_DEPARTMENT_HEAD,
)
def publications_report():
    query, filters = get_filtered_publications_query()
    pagination = paginate(query, request.args)

    return render_template(
        "reports/publications.html",
        publications=pagination.items,
        pagination=pagination,
        departments=get_report_departments(),
        years=get_report_years(),
        quartiles=get_report_reference_values("QUARTILE"),
        indexing_types=get_report_reference_values("INDEXING_TYPE"),
        publication_statuses=(REPORT_PUBLICATION_STATUSES),
        verification_statuses=(REPORT_VERIFICATION_STATUSES),
        selected_year=filters["year"],
        selected_department_id=(filters["department_id"]),
        selected_quartile_id=(filters["quartile_id"]),
        selected_indexing_type_id=(filters["indexing_type_id"]),
        selected_publication_status=(filters["publication_status"]),
        selected_verification_status=(filters["verification_status"]),
    )


@reports_bp.route("/publications/export.xlsx")
@roles_required(
    "ADMIN",
    ROLE_DEPARTMENT_HEAD,
)
def export_publications_excel():
    publications, _ = get_filtered_publications()

    workbook = create_publications_workbook(publications)

    output = BytesIO()

    workbook.save(output)

    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="publication_report.xlsx",
        mimetype=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    )


@reports_bp.route("/publications/export.pdf")
@roles_required(
    "ADMIN",
    ROLE_DEPARTMENT_HEAD,
)
def export_publications_pdf():
    publications, _ = get_filtered_publications()

    output = create_publications_pdf(publications)

    return send_file(
        output,
        as_attachment=True,
        download_name="publication_report.pdf",
        mimetype="application/pdf",
    )
