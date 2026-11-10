from flask import flash, redirect, render_template, request, session, url_for
from flask_login import current_user
from sqlalchemy import func, select

from app.admin import admin_bp
from app.admin.services import (
    active_departments,
    department_assignment_errors,
    lock_technical_admins,
    paginated_admin_list,
    validate_user_form,
)
from app.audit import audit
from app.auth import technical_admin_required
from app.extensions import db
from app.models import Department, User
from app.security import password_stamp

ROLE_TECH_ADMIN = "TECH_ADMIN"
ROLE_ADMIN = "ADMIN"
ROLE_DEPARTMENT_HEAD = "DEPARTMENT_HEAD"


ROLES = (
    (ROLE_TECH_ADMIN, "Технический администратор"),
    (ROLE_ADMIN, "Монитор / Администратор"),
    (ROLE_DEPARTMENT_HEAD, "Заведующий кафедрой"),
)

LANGUAGES = (
    ("ru", "Русский"),
    ("kk", "Қазақша"),
)


def has_another_active_technical_admin(user_id):
    return bool(
        db.session.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.id != user_id,
                User.role == ROLE_TECH_ADMIN,
                User.is_active.is_(True),
            )
        )
    )


def get_active_departments():
    return active_departments()


def get_user_form_context(user=None):
    return {
        "user": user,
        "departments": get_active_departments(),
        "roles": ROLES,
        "languages": LANGUAGES,
    }


def validate_department_assignment(role, department):
    errors = []

    if role == ROLE_DEPARTMENT_HEAD:
        if department is None:
            errors.append("Для заведующего кафедрой необходимо указать кафедру.")
        elif not department.is_active:
            errors.append("Нельзя назначить заведующего на архивную кафедру.")
        else:
            existing_head = db.session.scalar(
                select(User).where(
                    User.department_id == department.id,
                    User.role == ROLE_DEPARTMENT_HEAD,
                    User.is_active.is_(True),
                )
            )

            if existing_head:
                errors.append("У этой кафедры уже есть активный заведующий.")

    return errors


def get_department_from_form():
    department_id = request.form.get("department_id", "").strip()

    if not department_id:
        return None, []

    try:
        department_id = int(department_id)
    except ValueError:
        return None, ["Выбрана некорректная кафедра."]

    department = db.session.get(Department, department_id)

    if department is None:
        return None, ["Выбрана некорректная кафедра."]

    if not department.is_active:
        return None, ["Нельзя назначить пользователя на архивную кафедру."]

    return department, []


@admin_bp.route("/users")
@technical_admin_required
def users():
    pagination = paginated_admin_list(
        User,
        (User.full_name, User.username, User.email),
        {"name": User.full_name, "username": User.username, "role": User.role},
        User.full_name,
    )
    return render_template("admin/users/list.html", users=pagination.items, pagination=pagination)


@admin_bp.route("/users/create", methods=["GET", "POST"])
@technical_admin_required
def create_user():
    departments = get_active_departments()

    if request.method == "POST":
        lock_technical_admins()
        values, password, errors = validate_user_form(request.form, actor=current_user)
        if errors:
            for error in errors:
                flash(error, "danger")

            return render_template(
                "admin/users/form.html",
                user=None,
                departments=departments,
                roles=ROLES,
                languages=LANGUAGES,
            )

        user = User(**values)

        user.set_password(password)

        db.session.add(user)
        db.session.flush()

        audit(
            "USER_CREATED",
            entity_type="User",
            entity_id=user.id,
            details={
                "username": user.username,
                "role": user.role,
                "department_id": user.department_id,
                "language": user.language,
            },
        )

        db.session.commit()

        flash(
            "Пользователь успешно создан.",
            "success",
        )

        return redirect(url_for("admin.users"))

    return render_template(
        "admin/users/form.html",
        user=None,
        departments=departments,
        roles=ROLES,
        languages=LANGUAGES,
    )


@admin_bp.route(
    "/users/<int:user_id>/edit",
    methods=["GET", "POST"],
)
@technical_admin_required
def edit_user(user_id):
    user = db.session.get(User, user_id)

    if user is None:
        flash(
            "Пользователь не найден.",
            "danger",
        )
        return redirect(url_for("admin.users"))

    departments = get_active_departments()

    if request.method == "POST":
        lock_technical_admins()
        values, password, errors = validate_user_form(request.form, actor=current_user, user=user)
        if errors:
            for error in errors:
                flash(error, "danger")

            return render_template(
                "admin/users/form.html",
                user=user,
                departments=departments,
                roles=ROLES,
                languages=LANGUAGES,
            )

        for key, value in values.items():
            setattr(user, key, value)

        if password:
            user.set_password(password)

        audit(
            "USER_UPDATED",
            entity_type="User",
            entity_id=user.id,
            details={
                "username": user.username,
                "role": user.role,
                "department_id": user.department_id,
                "language": user.language,
                "is_active": user.is_active,
                "password_changed": bool(password),
            },
        )

        db.session.commit()
        if user.id == current_user.id and password:
            session["auth_stamp"] = password_stamp(user)

        flash(
            "Пользователь успешно изменён.",
            "success",
        )

        return redirect(url_for("admin.users"))

    return render_template(
        "admin/users/form.html",
        user=user,
        departments=departments,
        roles=ROLES,
        languages=LANGUAGES,
    )


@admin_bp.route(
    "/users/<int:user_id>/block",
    methods=["POST"],
)
@technical_admin_required
def block_user(user_id):
    lock_technical_admins()
    user = db.session.get(User, user_id)

    if user is None:
        flash(
            "Пользователь не найден.",
            "danger",
        )
        return redirect(url_for("admin.users"))

    if user.id == current_user.id:
        flash(
            "Нельзя заблокировать собственную учетную запись.",
            "danger",
        )
        return redirect(url_for("admin.users"))

    if user.role == ROLE_TECH_ADMIN and not has_another_active_technical_admin(user.id):
        flash("Нельзя заблокировать последнего активного технического администратора.", "danger")
        return redirect(url_for("admin.users"))

    user.is_active = False

    audit(
        "USER_BLOCKED",
        entity_type="User",
        entity_id=user.id,
        details={
            "username": user.username,
        },
    )

    db.session.commit()

    flash(
        "Пользователь заблокирован.",
        "success",
    )

    return redirect(url_for("admin.users"))


@admin_bp.route(
    "/users/<int:user_id>/delete",
    methods=["POST"],
)
@technical_admin_required
def delete_user(user_id):
    lock_technical_admins()
    user = db.session.get(User, user_id)

    if user is None:
        flash(
            "Пользователь не найден.",
            "danger",
        )
        return redirect(url_for("admin.users"))

    if user.id == current_user.id:
        flash(
            "Нельзя удалить собственную учетную запись.",
            "danger",
        )
        return redirect(url_for("admin.users"))

    if user.role == ROLE_TECH_ADMIN and not has_another_active_technical_admin(user.id):
        flash("Нельзя удалить последнего активного технического администратора.", "danger")
        return redirect(url_for("admin.users"))

    audit(
        "USER_DELETED",
        entity_type="User",
        entity_id=user.id,
        details={
            "username": user.username,
            "full_name": user.full_name,
            "email": user.email,
            "role": user.role,
            "department_id": user.department_id,
        },
    )

    db.session.delete(user)
    db.session.commit()

    flash(
        "Пользователь удалён.",
        "success",
    )

    return redirect(url_for("admin.users"))


@admin_bp.route(
    "/users/<int:user_id>/unblock",
    methods=["POST"],
)
@technical_admin_required
def unblock_user(user_id):
    lock_technical_admins()
    user = db.session.get(User, user_id)

    if user is None:
        flash("Пользователь не найден.", "danger")
        return redirect(url_for("admin.users"))

    if user.is_active:
        flash("Учётная запись уже активна.", "warning")
        return redirect(url_for("admin.users"))

    if user.role == ROLE_DEPARTMENT_HEAD and user.department_id is None:
        flash("Нельзя разблокировать заведующего без назначенной кафедры.", "danger")
        return redirect(url_for("admin.users"))

    if user.role == ROLE_DEPARTMENT_HEAD:
        department = db.session.scalar(
            select(Department).where(Department.id == user.department_id).with_for_update()
        )
        errors = department_assignment_errors(department, exclude_user_id=user.id)
        if errors:
            for message in errors:
                flash(message, "danger")
            return redirect(url_for("admin.users"))

    user.is_active = True
    audit(
        "USER_UNBLOCKED",
        entity_type="User",
        entity_id=user.id,
        details={"username": user.username},
    )
    db.session.commit()

    flash("Пользователь разблокирован.", "success")
    return redirect(url_for("admin.users"))
