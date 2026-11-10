"""Publication export infrastructure; rendering is independent of route dispatch."""

from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.i18n import (
    PUBLICATION_STATUS_LABELS,
    VERIFICATION_STATUS_LABELS,
    current_language,
    localized_label,
    translate,
)
from app.services.export_safety import append_literal_row
from app.services.export_safety import literal_paragraph as Paragraph


def get_quartile_name(publication):
    if publication.quartile is None:
        return ""

    if current_language() == "kk":
        return publication.quartile.name_kk or publication.quartile.name_ru or ""

    return publication.quartile.name_ru or publication.quartile.name_kk or ""


def get_indexing_type_name(publication):
    if publication.indexing_type is None:
        return ""

    if current_language() == "kk":
        return publication.indexing_type.name_kk or publication.indexing_type.name_ru or ""

    return publication.indexing_type.name_ru or publication.indexing_type.name_kk or ""


def get_publication_report_row(publication):
    plan = publication.plan_item.plan

    verifier = ""

    if publication.verifier:
        verifier = publication.verifier.full_name

    verified_at = ""

    if publication.verified_at:
        verified_at = publication.verified_at.strftime("%d.%m.%Y %H:%M")

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

    headers = [
        translate(label)
        for label in [
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
        ]
    ]

    append_literal_row(worksheet, headers)

    for publication in publications:
        append_literal_row(worksheet, get_publication_report_row(publication))

    worksheet.freeze_panes = "A2"

    if worksheet.max_row >= 2:
        worksheet.auto_filter.ref = worksheet.dimensions

    for column_cells in worksheet.columns:
        max_length = max(
            (len(str(cell.value)) for cell in column_cells if cell.value is not None),
            default=0,
        )

        column_letter = get_column_letter(column_cells[0].column)

        worksheet.column_dimensions[column_letter].width = min(
            max(max_length + 2, 12),
            60,
        )

    return workbook


def get_pdf_font_paths():
    regular_candidates = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/calibri.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
    ]

    bold_candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/calibrib.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
    ]

    regular_path = next(
        (path for path in regular_candidates if path.is_file()),
        None,
    )

    bold_path = next(
        (path for path in bold_candidates if path.is_file()),
        None,
    )

    if regular_path is None or bold_path is None:
        raise RuntimeError(
            "Не найден Unicode-шрифт для генерации PDF. Установите Arial, Calibri или DejaVu Sans."
        )

    return regular_path, bold_path


def register_pdf_fonts():
    regular_path, bold_path = get_pdf_font_paths()

    if "PublicationReportRegular" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(
            TTFont(
                "PublicationReportRegular",
                str(regular_path),
            )
        )

    if "PublicationReportBold" not in pdfmetrics.getRegisteredFontNames():
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

    headers = [
        translate(label)
        for label in [
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
        ]
    ]

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
        values = get_publication_report_row(publication)

        rows.append(
            [
                Paragraph(
                    str(value) if value != "" else "—",
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
