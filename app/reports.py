from io import BytesIO
from pathlib import Path

from flask import Blueprint, abort, render_template, request, send_file
from flask_login import current_user
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import select

from app.access import (
    ensure_department_access,
    get_scoped_department_id,
)
from app.auth import (
    ROLE_DEPARTMENT_HEAD,
    roles_required,
)
from app.extensions import db
from app.i18n import (
    PUBLICATION_STATUS_LABELS,
    VERIFICATION_STATUS_LABELS,
    current_language,
    localized_label,
    translate,
)
from app.models import (
    Department,
    Plan,
    PlanItem,
    Publication,
    ReferenceValue,
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
    value = request.args.get(
        name,
        "",
    ).strip()

    if not value:
        return None

    try:
        parsed_value = int(value)
    except ValueError:
        abort(400)

    if parsed_value < 0:
        abort(400)

    return parsed_value


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
    return db.session.scalars(
        select(Plan.year)
        .where(
            Plan.status == REPORT_PLAN_STATUS,
        )
        .distinct()
        .order_by(
            Plan.year.desc(),
        )
    ).all()


def get_report_reference_values(reference_type):
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


def get_publications_report_filters():
    year = parse_optional_int("year")

    requested_department_id = parse_optional_int(
        "department_id"
    )

    quartile_id = parse_optional_int(
        "quartile_id"
    )

    indexing_type_id = parse_optional_int(
        "indexing_type_id"
    )

    publication_status = request.args.get(
        "publication_status",
        "",
    ).strip()

    verification_status = request.args.get(
        "verification_status",
        "",
    ).strip()

    if publication_status:
        if (
            publication_status
            not in REPORT_PUBLICATION_STATUSES
        ):
            abort(400)

    if verification_status:
        if (
            verification_status
            not in REPORT_VERIFICATION_STATUSES
        ):
            abort(400)

    ensure_department_access(
        requested_department_id
    )

    department_id = get_scoped_department_id(
        requested_department_id
    )

    return {
        "year": year,
        "department_id": department_id,
        "quartile_id": quartile_id,
        "indexing_type_id": indexing_type_id,
        "publication_status": (
            publication_status or None
        ),
        "verification_status": (
            verification_status or None
        ),
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
            Plan.status == REPORT_PLAN_STATUS,
        )
    )

    if year is not None:
        query = query.where(
            Plan.year == year,
        )

    if department_id is not None:
        query = query.where(
            Publication.department_id
            == department_id,
        )

    if publication_status is not None:
        query = query.where(
            Publication.status
            == publication_status,
        )

    if verification_status is not None:
        query = query.where(
            Publication.verification_status
            == verification_status,
        )

    if quartile_id is not None:
        query = query.where(
            Publication.quartile_id
            == quartile_id,
        )

    if indexing_type_id is not None:
        query = query.where(
            Publication.indexing_type_id
            == indexing_type_id,
        )

    return query.order_by(
        Plan.year.desc(),
        Publication.department_id,
        Publication.title,
        Publication.id,
    )


def get_quartile_name(publication):
    if publication.quartile is None:
        return ""

    if current_language() == "kk":
        return (
            publication.quartile.name_kk
            or publication.quartile.name_ru
            or ""
        )

    return (
        publication.quartile.name_ru
        or publication.quartile.name_kk
        or ""
    )


def get_indexing_type_name(publication):
    if publication.indexing_type is None:
        return ""

    if current_language() == "kk":
        return (
            publication.indexing_type.name_kk
            or publication.indexing_type.name_ru
            or ""
        )

    return (
        publication.indexing_type.name_ru
        or publication.indexing_type.name_kk
        or ""
    )


def get_publication_report_row(publication):
    plan = publication.plan_item.plan

    verifier = ""

    if publication.verifier:
        verifier = publication.verifier.full_name

    verified_at = ""

    if publication.verified_at:
        verified_at = publication.verified_at.strftime(
            "%d.%m.%Y %H:%M"
        )

    return [
        plan.year,
        publication.department.name,
        f"№{plan.id}",
        publication.title,
        publication.journal or "",
        publication.publication_year or "",
        publication.doi or "",
        get_quartile_name(publication),
        get_indexing_type_name(publication),
        localized_label(PUBLICATION_STATUS_LABELS, publication.status),
        localized_label(VERIFICATION_STATUS_LABELS, publication.verification_status),
        verifier,
        verified_at,
    ]


def create_publications_workbook(publications):
    workbook = Workbook()

    worksheet = workbook.active
    worksheet.title = translate("Публикации")

    headers = [translate(label) for label in [
        "Год плана",
        "Кафедра",
        "План",
        "Название публикации",
        "Журнал",
        "Год публикации",
        "DOI",
        "Квартиль",
        "Индексация",
        "Статус публикации",
        "Статус проверки",
        "Проверяющий",
        "Дата проверки",
    ]]

    worksheet.append(headers)

    for publication in publications:
        worksheet.append(
            get_publication_report_row(
                publication
            )
        )

    worksheet.freeze_panes = "A2"

    if worksheet.max_row >= 2:
        worksheet.auto_filter.ref = (
            worksheet.dimensions
        )

    for column_cells in worksheet.columns:
        max_length = max(
            (
                len(str(cell.value))
                for cell in column_cells
                if cell.value is not None
            ),
            default=0,
        )

        column_letter = get_column_letter(
            column_cells[0].column
        )

        worksheet.column_dimensions[
            column_letter
        ].width = min(
            max(max_length + 2, 12),
            60,
        )

    return workbook


def get_pdf_font_paths():
    regular_candidates = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/calibri.ttf"),
        Path(
            "/usr/share/fonts/truetype/dejavu/"
            "DejaVuSans.ttf"
        ),
        Path(
            "/usr/share/fonts/truetype/liberation2/"
            "LiberationSans-Regular.ttf"
        ),
    ]

    bold_candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/calibrib.ttf"),
        Path(
            "/usr/share/fonts/truetype/dejavu/"
            "DejaVuSans-Bold.ttf"
        ),
        Path(
            "/usr/share/fonts/truetype/liberation2/"
            "LiberationSans-Bold.ttf"
        ),
    ]

    regular_path = next(
        (
            path
            for path in regular_candidates
            if path.is_file()
        ),
        None,
    )

    bold_path = next(
        (
            path
            for path in bold_candidates
            if path.is_file()
        ),
        None,
    )

    if (
        regular_path is None
        or bold_path is None
    ):
        raise RuntimeError(
            "Не найден Unicode-шрифт для генерации PDF. "
            "Установите Arial, Calibri или DejaVu Sans."
        )

    return regular_path, bold_path


def register_pdf_fonts():
    regular_path, bold_path = (
        get_pdf_font_paths()
    )

    if (
        "PublicationReportRegular"
        not in pdfmetrics.getRegisteredFontNames()
    ):
        pdfmetrics.registerFont(
            TTFont(
                "PublicationReportRegular",
                str(regular_path),
            )
        )

    if (
        "PublicationReportBold"
        not in pdfmetrics.getRegisteredFontNames()
    ):
        pdfmetrics.registerFont(
            TTFont(
                "PublicationReportBold",
                str(bold_path),
            )
        )


def create_publications_pdf(publications):
    register_pdf_fonts()

    output = BytesIO()

    document = SimpleDocTemplate(
        output,
        pagesize=landscape(A4),
        rightMargin=4 * mm,
        leftMargin=4 * mm,
        topMargin=8 * mm,
        bottomMargin=8 * mm,
        title=translate("Отчёт по публикациям"),
        author="Publication Monitor",
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "PublicationReportTitle",
        parent=styles["Title"],
        fontName="PublicationReportBold",
        fontSize=14,
        leading=17,
        alignment=TA_LEFT,
        spaceAfter=5 * mm,
    )

    header_style = ParagraphStyle(
        "PublicationReportHeader",
        fontName="PublicationReportBold",
        fontSize=5.5,
        leading=6.5,
        alignment=TA_LEFT,
    )

    cell_style = ParagraphStyle(
        "PublicationReportCell",
        fontName="PublicationReportRegular",
        fontSize=5.2,
        leading=6.2,
        alignment=TA_LEFT,
    )

    story = [
        Paragraph(
            translate("Отчёт по публикациям"),
            title_style,
        ),
        Spacer(
            1,
            2 * mm,
        ),
    ]

    headers = [translate(label) for label in [
        "Год",
        "Кафедра",
        "План",
        "Публикация",
        "Журнал",
        "Год",
        "DOI",
        "Квартиль",
        "Индексация",
        "Статус",
        "Проверка",
        "Проверяющий",
        "Дата",
    ]]

    rows = [
        [
            Paragraph(
                header,
                header_style,
            )
            for header in headers
        ]
    ]

    for publication in publications:
        values = get_publication_report_row(
            publication
        )

        rows.append(
            [
                Paragraph(
                    str(value)
                    if value != ""
                    else "—",
                    cell_style,
                )
                for value in values
            ]
        )

    column_widths = [
        8 * mm,
        22 * mm,
        8 * mm,
        20 * mm,
        34 * mm,
        20 * mm,
        8 * mm,
        20 * mm,
        13 * mm,
        19 * mm,
        19 * mm,
        22 * mm,
        17 * mm,
    ]

    table = Table(
        rows,
        colWidths=column_widths,
        repeatRows=1,
        hAlign="LEFT",
    )

    table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    "#E8E8E8",
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.3,
                    "#999999",
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "TOP",
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    2,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    2,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    2,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    2,
                ),
            ]
        )
    )

    story.append(table)

    story.append(
        Spacer(
            1,
            4 * mm,
        )
    )

    story.append(
        Paragraph(
            f"{translate('Всего публикаций:')} {len(publications)}",
            cell_style,
        )
    )

    document.build(story)

    output.seek(0)

    return output


def get_filtered_publications():
    filters = get_publications_report_filters()

    query = build_publications_report_query(
        **filters
    )

    return db.session.scalars(
        query
    ).all(), filters


@reports_bp.route("/publications")
@roles_required(
    "ADMIN",
    ROLE_DEPARTMENT_HEAD,
)
def publications_report():
    publications, filters = (
        get_filtered_publications()
    )

    return render_template(
        "reports/publications.html",
        publications=publications,
        departments=get_report_departments(),
        years=get_report_years(),
        quartiles=get_report_reference_values(
            "QUARTILE"
        ),
        indexing_types=get_report_reference_values(
            "INDEXING_TYPE"
        ),
        publication_statuses=(
            REPORT_PUBLICATION_STATUSES
        ),
        verification_statuses=(
            REPORT_VERIFICATION_STATUSES
        ),
        selected_year=filters["year"],
        selected_department_id=(
            filters["department_id"]
        ),
        selected_quartile_id=(
            filters["quartile_id"]
        ),
        selected_indexing_type_id=(
            filters["indexing_type_id"]
        ),
        selected_publication_status=(
            filters["publication_status"]
        ),
        selected_verification_status=(
            filters["verification_status"]
        ),
    )


@reports_bp.route(
    "/publications/export.xlsx"
)
@roles_required(
    "ADMIN",
    ROLE_DEPARTMENT_HEAD,
)
def export_publications_excel():
    publications, _ = (
        get_filtered_publications()
    )

    workbook = create_publications_workbook(
        publications
    )

    output = BytesIO()

    workbook.save(output)

    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="publication_report.xlsx",
        mimetype=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
    )


@reports_bp.route(
    "/publications/export.pdf"
)
@roles_required(
    "ADMIN",
    ROLE_DEPARTMENT_HEAD,
)
def export_publications_pdf():
    publications, _ = (
        get_filtered_publications()
    )

    output = create_publications_pdf(
        publications
    )

    return send_file(
        output,
        as_attachment=True,
        download_name="publication_report.pdf",
        mimetype="application/pdf",
    )
