"""Encode untrusted data as text in spreadsheet and PDF exports."""

from xml.sax.saxutils import escape

from reportlab.platypus import Paragraph


def append_literal_row(worksheet, values):
    worksheet.append(values)
    for cell in worksheet[worksheet.max_row]:
        if isinstance(cell.value, str):
            cell.data_type = "s"


def literal_paragraph(value, style, *args, **kwargs):
    return Paragraph(escape(str(value)), style, *args, **kwargs)
