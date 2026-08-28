from flask import abort
from flask_login import current_user

from app.auth import (
    ROLE_ADMIN,
    ROLE_DEPARTMENT_HEAD,
    ROLE_TECH_ADMIN,
)


def is_tech_admin():
    return current_user.role == ROLE_TECH_ADMIN


def is_admin():
    return current_user.role == ROLE_ADMIN


def is_department_head():
    return current_user.role == ROLE_DEPARTMENT_HEAD


def get_scoped_department_id(
    requested_department_id=None,
):
    if is_department_head():
        if current_user.department_id is None:
            abort(403)

        return current_user.department_id

    return requested_department_id


def ensure_department_access(department_id):
    if is_department_head():
        if current_user.department_id is None:
            abort(403)

        if department_id != current_user.department_id:
            abort(403)

    return True