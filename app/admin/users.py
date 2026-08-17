from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import or_, select

from app.admin import admin_bp
from app.auth import technical_admin_required
from app.extensions import db
from app.models import Department, User


ROLES = (
    ("TECH_ADMIN", "Технический администратор"),
    ("ADMIN", "Монитор / Администратор"),
    ("DEPARTMENT_HEAD", "Заведующий кафедрой"),
)

LANGUAGES = (
    ("ru", "Русский"),
    ("kk", "Қазақша"),
)


def get_active_departments():
    return db.session.scalars(
        select(Department)
        .where(Department.is_active.is_(True))
        .order_by(Department.name)
    ).all()


def get_user_form_context(user=None):
    return {
        "user": user,
        "departments": get_active_departments(),
        "roles": ROLES,
        "languages": LANGUAGES,
    }


def validate_department_assignment(role, department):
    errors = []

    if role == "DEPARTMENT_HEAD":
        if department is None:
            errors.append(
                "Для заведующего кафедрой необходимо указать кафедру."
            )
        elif not department.is_active:
            errors.append(
                "Нельзя назначить заведующего на архивную кафедру."
            )
        else:
            existing_head = db.session.scalar(
                select(User).where(
                    User.department_id == department.id,
                    User.role == "DEPARTMENT_HEAD",
                    User.is_active.is_(True),
                )
            )

            if existing_head:
                errors.append(
                    "У этой кафедры уже есть активный заведующий."
                )

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
        return None, [
            "Нельзя назначить пользователя на архивную кафедру."
        ]

    return department, []


@admin_bp.route("/users")
@technical_admin_required
def users():
    users_list = db.session.scalars(
        select(User).order_by(User.full_name)
    ).all()

    return render_template(
        "admin/users/list.html",
        users=users_list,
    )


@admin_bp.route("/users/create", methods=["GET", "POST"])
@technical_admin_required
def create_user():
    departments = get_active_departments()

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        password_confirmation = request.form.get(
            "password_confirmation",
            "",
        )
        role = request.form.get("role", "").strip()
        language = request.form.get("language", "ru").strip()

        errors = []

        if not username:
            errors.append("Введите логин.")

        if not full_name:
            errors.append("Введите ФИО.")

        if not email:
            errors.append("Введите email.")

        if role not in {value for value, _ in ROLES}:
            errors.append("Выберите корректную роль.")

        if language not in {value for value, _ in LANGUAGES}:
            errors.append("Выберите корректный язык.")

        if len(password) < 8:
            errors.append(
                "Пароль должен содержать минимум 8 символов."
            )

        if password != password_confirmation:
            errors.append("Пароли не совпадают.")

        existing_user = db.session.scalar(
            select(User).where(
                or_(
                    User.username == username,
                    User.email == email,
                )
            )
        )

        if existing_user:
            errors.append(
                "Пользователь с таким логином или email уже существует."
            )

        department, department_errors = get_department_from_form()
        errors.extend(department_errors)

        if role != "DEPARTMENT_HEAD":
            department = None

        if role == "DEPARTMENT_HEAD" and not department_errors:
            errors.extend(
                validate_department_assignment(
                    role,
                    department,
                )
            )

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

        user = User(
            username=username,
            full_name=full_name,
            email=email,
            role=role,
            language=language,
            department_id=(
                department.id
                if department is not None
                else None
            ),
            is_active=True,
        )

        user.set_password(password)

        db.session.add(user)
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
        username = request.form.get("username", "").strip()
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        password_confirmation = request.form.get(
            "password_confirmation",
            "",
        )
        role = request.form.get("role", "").strip()
        language = request.form.get("language", "ru").strip()
        is_active = request.form.get("is_active") == "on"

        errors = []

        if not username:
            errors.append("Введите логин.")

        if not full_name:
            errors.append("Введите ФИО.")

        if not email:
            errors.append("Введите email.")

        if role not in {value for value, _ in ROLES}:
            errors.append("Выберите корректную роль.")

        if language not in {value for value, _ in LANGUAGES}:
            errors.append("Выберите корректный язык.")

        duplicate = db.session.scalar(
            select(User).where(
                User.id != user.id,
                or_(
                    User.username == username,
                    User.email == email,
                ),
            )
        )

        if duplicate:
            errors.append(
                "Логин или email уже используются другим пользователем."
            )

        department, department_errors = get_department_from_form()
        errors.extend(department_errors)

        if role == "DEPARTMENT_HEAD":
            if department is None:
                errors.append(
                    "Для заведующего кафедрой необходимо указать кафедру."
                )
            elif not department_errors:
                existing_head = db.session.scalar(
                    select(User).where(
                        User.id != user.id,
                        User.department_id == department.id,
                        User.role == "DEPARTMENT_HEAD",
                        User.is_active.is_(True),
                    )
                )

                if existing_head:
                    errors.append(
                        "У этой кафедры уже есть активный заведующий."
                    )
        else:
            department = None

        if role == "DEPARTMENT_HEAD" and not is_active:
            errors.append(
                "Заведующий кафедрой должен иметь активную учетную запись."
            )

        if password or password_confirmation:
            if len(password) < 8:
                errors.append(
                    "Новый пароль должен содержать минимум 8 символов."
                )

            if password != password_confirmation:
                errors.append(
                    "Пароли не совпадают."
                )

        if user.id == current_user.id:
            if role != "TECH_ADMIN":
                errors.append(
                    "Нельзя лишить себя роли технического администратора."
                )

            if not is_active:
                errors.append(
                    "Нельзя заблокировать собственную учетную запись."
                )

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

        user.username = username
        user.full_name = full_name
        user.email = email
        user.role = role
        user.language = language
        user.department_id = (
            department.id
            if department is not None
            else None
        )
        user.is_active = is_active

        if password:
            user.set_password(password)

        db.session.commit()

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

    user.is_active = False

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

    db.session.delete(user)
    db.session.commit()

    flash(
        "Пользователь удалён.",
        "success",
    )

    return redirect(url_for("admin.users"))