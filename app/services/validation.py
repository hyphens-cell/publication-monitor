"""Shared form validation, before any business mutation is made."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class EmployeeInput:
    full_name: str
    position: str | None
    email: str | None


def validate_employee(form):
    full_name = form.get("full_name", "").strip()
    position = form.get("position", "").strip()
    email = form.get("email", "").strip().lower()
    errors = []
    if not full_name:
        errors.append("Введите ФИО сотрудника.")
    for value, message in (
        (full_name, "ФИО не должно превышать 255 символов."),
        (position, "Должность не должна превышать 255 символов."),
        (email, "Email не должен превышать 255 символов."),
    ):
        if len(value) > 255:
            errors.append(message)
    return EmployeeInput(full_name, position or None, email or None), errors


@dataclass(frozen=True)
class PlanItemInput:
    title: str
    publication_type_id: int | None
    journal: str | None
    quartile_id: int | None
    planned_date: date | None
    author_ids: frozenset[int]


def validate_plan_item(form, publication_types, quartiles, employees):
    errors = []
    title = form.get("title", "").strip()
    journal = form.get("journal", "").strip()
    if not title:
        errors.append("Введите название публикации.")
    if len(title) > 1000 or len(journal) > 500:
        errors.append("Превышена допустимая длина поля.")

    def reference_id(name, choices, required, message):
        value = form.get(name, "").strip()
        if not value and not required:
            return None
        try:
            result = int(value)
        except ValueError:
            errors.append(message)
            return None
        if result not in {item.id for item in choices}:
            errors.append(message)
            return None
        return result

    publication_type_id = reference_id(
        "publication_type_id", publication_types, True, "Выбран некорректный тип публикации."
    )
    quartile_id = reference_id("quartile_id", quartiles, False, "Выбран некорректный квартиль.")
    planned_date = None
    value = form.get("planned_date", "").strip()
    if value:
        try:
            planned_date = date.fromisoformat(value)
        except ValueError:
            errors.append("Введите корректную планируемую дату.")
    author_ids = set()
    for author_id in form.getlist("author_ids"):
        try:
            author_ids.add(int(author_id))
        except ValueError:
            errors.append("Выбран некорректный автор.")
    if not author_ids <= {employee.id for employee in employees}:
        errors.append("Нельзя выбрать сотрудника другой кафедры.")
    return PlanItemInput(
        title, publication_type_id, journal or None, quartile_id, planned_date, frozenset(author_ids)
    ), errors
