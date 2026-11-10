"""Bounded list queries with deterministic ordering supplied by each module."""

from flask import abort

from app.extensions import db


def optional_int(arguments, name):
    value = arguments.get(name, "").strip()
    if not value:
        return None
    try:
        result = int(value)
    except ValueError:
        abort(400)
    if result < 0:
        abort(400)
    return result


def paginate(query, arguments):
    page = optional_int(arguments, "page")
    per_page = optional_int(arguments, "per_page")
    if page == 0 or per_page == 0:
        abort(400)
    return db.paginate(
        query, page=page or 1, per_page=min(per_page or 25, 50), max_per_page=50, error_out=False
    )


def search_term(arguments):
    term = arguments.get("q", "").strip()
    if len(term) > 255:
        abort(400)
    # Treat search text literally, including SQL wildcard characters.
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def sort_order(arguments, options, default):
    key = arguments.get("sort", default)
    if key not in options:
        abort(400)
    return options[key]
