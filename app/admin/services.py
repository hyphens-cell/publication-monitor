"""Administration validation and queries, independent of form rendering."""

from email_validator import EmailNotValidError, validate_email
from flask import abort, request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import Department, User

ROLES = (
    ("TECH_ADMIN", "Технический администратор"),
    ("ADMIN", "Монитор / Администратор"),
    ("DEPARTMENT_HEAD", "Заведующий кафедрой"),
)
LANGUAGES = (("ru", "Русский"), ("kk", "Қазақша"))


def active_departments():
    return db.session.scalars(
        select(Department).where(Department.is_active.is_(True)).order_by(Department.name)
    ).all()


def another_active_technical_admin(user_id):
    return bool(
        db.session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.id != user_id, User.role == "TECH_ADMIN", User.is_active.is_(True))
        )
    )


def lock_technical_admins():
    """Serialize changes to the last-admin invariant on PostgreSQL."""
    db.session.scalars(
        select(User).where(User.role == "TECH_ADMIN").order_by(User.id).with_for_update()
    ).all()


def department_assignment_errors(department, *, exclude_user_id=None):
    if department is None:
        return ["Для заведующего кафедрой необходимо указать кафедру."]
    if not department.is_active:
        return ["Нельзя назначить заведующего на архивную кафедру."]
    query = select(User.id).where(
        User.department_id == department.id, User.role == "DEPARTMENT_HEAD", User.is_active.is_(True)
    )
    if exclude_user_id is not None:
        query = query.where(User.id != exclude_user_id)
    if db.session.scalar(query) is not None:
        return ["У этой кафедры уже есть активный заведующий."]
    return []


def validate_user_form(form, *, actor, user=None):
    values = {key: form.get(key, "").strip() for key in ("username", "full_name", "email", "role")}
    values["email"] = values["email"].lower()
    values["language"] = form.get("language", "ru").strip()
    values["is_active"] = True if user is None else form.get("is_active") == "on"
    password = form.get("password", "")
    confirmation = form.get("password_confirmation", "")
    errors = []
    for field, label, limit in (
        ("username", "Логин", 100),
        ("full_name", "ФИО", 255),
        ("email", "Email", 255),
    ):
        if not values[field] or len(values[field]) > limit:
            errors.append(f"{label}: допустимая длина от 1 до {limit} символов.")
    if values["email"]:
        try:
            validate_email(values["email"], check_deliverability=False)
        except EmailNotValidError:
            errors.append("Введите корректный email.")
    if values["role"] not in {role for role, _ in ROLES}:
        errors.append("Выберите корректную роль.")
    if values["language"] not in {language for language, _ in LANGUAGES}:
        errors.append("Выберите корректный язык.")
    if user is None or password or confirmation:
        if len(password) < 8 or len(password.encode("utf-8")) > 72:
            errors.append("Пароль: минимум 8 символов, максимум 72 байта UTF-8.")
        if password != confirmation:
            errors.append("Пароли не совпадают.")
    duplicate = select(User.id).where(or_(User.username == values["username"], User.email == values["email"]))
    if user:
        duplicate = duplicate.where(User.id != user.id)
    if db.session.scalar(duplicate) is not None:
        errors.append("Пользователь с таким логином или email уже существует.")
    values["department_id"] = None
    if values["role"] == "DEPARTMENT_HEAD":
        department = None
        try:
            department_id = int(form.get("department_id", ""))
            department = db.session.scalar(
                select(Department).where(Department.id == department_id).with_for_update()
            )
        except (TypeError, ValueError):
            pass
        errors.extend(department_assignment_errors(department, exclude_user_id=user.id if user else None))
        if department:
            values["department_id"] = department.id
        if not values["is_active"]:
            errors.append("Заведующий кафедрой должен иметь активную учетную запись.")
    if user:
        if user.id == actor.id:
            if values["role"] != "TECH_ADMIN":
                errors.append("Нельзя лишить себя роли технического администратора.")
            if not values["is_active"]:
                errors.append("Нельзя заблокировать собственную учетную запись.")
        if (
            user.role == "TECH_ADMIN"
            and user.is_active
            and (values["role"] != "TECH_ADMIN" or not values["is_active"])
            and not another_active_technical_admin(user.id)
        ):
            errors.append("В системе должен оставаться хотя бы один активный технический администратор.")
    return values, password, errors


def validate_department_form(form, department=None):
    values = {"name": form.get("name", "").strip(), "code": form.get("code", "").strip().upper()}
    errors = []
    for key, limit in (("name", 255), ("code", 50)):
        if not values[key] or len(values[key]) > limit:
            errors.append("Название и код кафедры обязательны; максимум 255 и 50 символов соответственно.")
    query = select(Department).where(
        or_(Department.name == values["name"], Department.code == values["code"])
    )
    if department:
        query = query.where(Department.id != department.id)
    if db.session.scalar(query) is not None:
        errors.append("Кафедра с таким названием или кодом уже существует.")
    return values, errors


def paginated_admin_list(model, search_fields, sort_fields, default_sort):
    try:
        page = int(request.args.get("page", "1"))
        per_page = int(request.args.get("per_page", "25"))
    except ValueError:
        abort(400)
    if page < 1 or per_page < 1:
        abort(400)
    query = select(model)
    search = request.args.get("q", "").strip()[:255]
    if search:
        query = query.where(or_(*(field.icontains(search, autoescape=True) for field in search_fields)))
    status = request.args.get("status", "")
    if status in {"active", "archived"}:
        query = query.where(model.is_active.is_(status == "active"))
    if model is User:
        query = query.options(joinedload(User.department))
        role = request.args.get("role", "")
        if role in {value for value, _ in ROLES}:
            query = query.where(User.role == role)
    order = sort_fields.get(request.args.get("sort"), default_sort)
    query = query.order_by(order, model.id)
    return db.paginate(query, page=page, per_page=min(per_page, 100), error_out=False)
