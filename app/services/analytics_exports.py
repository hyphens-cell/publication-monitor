"""Analytics file rendering from already authorized aggregate data."""

from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.i18n import current_language, translate
from app.services.export_safety import append_literal_row
from app.services.export_safety import literal_paragraph as Paragraph


def create_analytics_workbook(data):
    workbook = Workbook()

    summary_sheet = workbook.active
    summary_sheet.title = translate("Итоги")

    append_literal_row(
        summary_sheet,
        [
            translate("Показатель"),
            translate("Значение"),
        ],
    )

    append_literal_row(
        summary_sheet,
        [
            translate("План"),
            data["total"]["planned_count"],
        ],
    )

    append_literal_row(
        summary_sheet,
        [
            translate("Факт"),
            data["total"]["actual_count"],
        ],
    )

    append_literal_row(
        summary_sheet,
        [
            translate("Выполнение, %"),
            data["total"]["progress"],
        ],
    )

    type_sheet = workbook.create_sheet(translate("По типам публикаций"))

    append_literal_row(
        type_sheet,
        [
            translate("Тип публикации"),
            translate("План"),
            translate("Факт"),
            translate("Выполнение, %"),
        ],
    )

    for item in data["by_publication_type"]:
        append_literal_row(
            type_sheet,
            [
                (item["name_kk"] if current_language() == "kk" else item["name_ru"])
                or item["name_ru"]
                or item["name_kk"]
                or "",
                item["planned_count"],
                item["actual_count"],
                item["progress"],
            ],
        )

    department_sheet = workbook.create_sheet(translate("По кафедрам"))

    append_literal_row(
        department_sheet,
        [
            translate("Кафедра"),
            translate("План"),
            translate("Факт"),
            translate("Выполнение, %"),
        ],
    )

    for item in data["by_department"]:
        append_literal_row(
            department_sheet,
            [
                item["name"],
                item["planned_count"],
                item["actual_count"],
                item["progress"],
            ],
        )

    for worksheet in workbook.worksheets:
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions

        for column_cells in worksheet.columns:
            maximum = max(
                (len(str(cell.value)) for cell in column_cells if cell.value is not None),
                default=0,
            )

            letter = get_column_letter(column_cells[0].column)

            worksheet.column_dimensions[letter].width = min(
                max(maximum + 2, 12),
                60,
            )

    output = BytesIO()

    workbook.save(output)
    output.seek(0)

    return output


def create_analytics_pdf(data):
    summary = data["total"]
    by_publication_type = data["by_publication_type"]
    by_department = data["by_department"]

    output = BytesIO()

    font_candidates = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/calibri.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]

    font_path = next(
        (candidate for candidate in font_candidates if candidate.exists()),
        None,
    )

    if font_path is not None:
        font_name = "AnalyticsUnicode"

        if font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(
                TTFont(
                    font_name,
                    str(font_path),
                )
            )
    else:
        font_name = "Helvetica"

    document = SimpleDocTemplate(
        output,
        pagesize=landscape(A4),
        leftMargin=8 * mm,
        rightMargin=8 * mm,
        topMargin=8 * mm,
        bottomMargin=8 * mm,
    )

    text_style = ParagraphStyle(
        "AnalyticsText",
        fontName=font_name,
        fontSize=7,
        leading=8,
    )

    header_style = ParagraphStyle(
        "AnalyticsHeader",
        parent=text_style,
        alignment=TA_CENTER,
    )

    title_style = ParagraphStyle(
        "AnalyticsTitle",
        fontName=font_name,
        fontSize=15,
        leading=18,
        spaceAfter=5 * mm,
    )

    section_style = ParagraphStyle(
        "AnalyticsSection",
        fontName=font_name,
        fontSize=10,
        leading=12,
        spaceAfter=2 * mm,
    )

    story = [
        Paragraph(
            translate("Аналитика публикационной деятельности"),
            title_style,
        )
    ]

    summary_table = Table(
        [
            [
                Paragraph(
                    translate("Показатель"),
                    header_style,
                ),
                Paragraph(
                    translate("Значение"),
                    header_style,
                ),
            ],
            [
                Paragraph(
                    translate("План"),
                    text_style,
                ),
                Paragraph(
                    str(summary["planned_count"]),
                    text_style,
                ),
            ],
            [
                Paragraph(
                    translate("Факт"),
                    text_style,
                ),
                Paragraph(
                    str(summary["actual_count"]),
                    text_style,
                ),
            ],
            [
                Paragraph(
                    translate("Выполнение"),
                    text_style,
                ),
                Paragraph(
                    f"{summary['progress']}%",
                    text_style,
                ),
            ],
        ],
        colWidths=[
            55 * mm,
            30 * mm,
        ],
    )

    summary_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.lightgrey,
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.3,
                    colors.grey,
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "TOP",
                ),
            ]
        )
    )

    story.append(summary_table)
    story.append(
        Spacer(
            1,
            5 * mm,
        )
    )

    story.append(
        Paragraph(
            translate("По типам публикаций"),
            section_style,
        )
    )

    type_rows = [
        [
            Paragraph(
                translate("Тип публикации"),
                header_style,
            ),
            Paragraph(
                translate("План"),
                header_style,
            ),
            Paragraph(
                translate("Факт"),
                header_style,
            ),
            Paragraph(
                "%",
                header_style,
            ),
        ]
    ]

    for item in by_publication_type:
        type_rows.append(
            [
                Paragraph(
                    (item["name_kk"] if current_language() == "kk" else item["name_ru"])
                    or item["name_ru"]
                    or item["name_kk"]
                    or "",
                    text_style,
                ),
                Paragraph(
                    str(item["planned_count"]),
                    text_style,
                ),
                Paragraph(
                    str(item["actual_count"]),
                    text_style,
                ),
                Paragraph(
                    f"{item['progress']}%",
                    text_style,
                ),
            ]
        )

    type_table = Table(
        type_rows,
        repeatRows=1,
        colWidths=[
            80 * mm,
            25 * mm,
            25 * mm,
            25 * mm,
        ],
    )

    type_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.lightgrey,
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.3,
                    colors.grey,
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "TOP",
                ),
            ]
        )
    )

    story.append(type_table)
    story.append(
        Spacer(
            1,
            5 * mm,
        )
    )

    story.append(
        Paragraph(
            translate("По кафедрам"),
            section_style,
        )
    )

    department_rows = [
        [
            Paragraph(
                translate("Кафедра"),
                header_style,
            ),
            Paragraph(
                translate("План"),
                header_style,
            ),
            Paragraph(
                translate("Факт"),
                header_style,
            ),
            Paragraph(
                "%",
                header_style,
            ),
        ]
    ]

    for item in by_department:
        department_rows.append(
            [
                Paragraph(
                    item["name"],
                    text_style,
                ),
                Paragraph(
                    str(item["planned_count"]),
                    text_style,
                ),
                Paragraph(
                    str(item["actual_count"]),
                    text_style,
                ),
                Paragraph(
                    f"{item['progress']}%",
                    text_style,
                ),
            ]
        )

    department_table = Table(
        department_rows,
        repeatRows=1,
        colWidths=[
            105 * mm,
            25 * mm,
            25 * mm,
            25 * mm,
        ],
    )

    department_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.lightgrey,
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.3,
                    colors.grey,
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "TOP",
                ),
            ]
        )
    )

    story.append(department_table)

    document.build(story)

    output.seek(0)

    return output
