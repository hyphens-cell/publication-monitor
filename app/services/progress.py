"""One definition of approved workload and achieved publications for all reports."""

from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db
from app.models import Plan, PlanItem, Publication

ASSESSMENTS = {"COMPLETE": "План выполнен", "ATTENTION": "Требует внимания", "RISK": "Риск невыполнения"}


def calculate_progress(planned_count, actual_count):
    return round(actual_count / planned_count * 100, 2) if planned_count > 0 else 0.0


def approved_items(plan):
    if plan.approved_snapshot is not None:
        return plan.approved_snapshot.get("items", [])
    if plan.status != "APPROVED":
        return []
    # Compatibility for plans created before version snapshots existed.
    return [
        {
            "id": item.id,
            "publication_id": item.publication.id if item.publication else None,
            "publication_type": {
                "id": item.publication_type_id,
                "name_ru": item.publication_type.name_ru,
                "name_kk": item.publication_type.name_kk,
            },
            "planned_date": item.planned_date.isoformat() if item.planned_date else None,
        }
        for item in plan.items
    ]


def get_workload_rows(year=None, department_id=None, publication_type_id=None, plan=None, plans=None):
    if plan is None and plans is None:
        query = select(Plan).where(or_(Plan.status == "APPROVED", Plan.approved_snapshot.is_not(None)))
        if year is not None:
            query = query.where(Plan.year == year)
        if department_id is not None:
            query = query.where(Plan.department_id == department_id)
        plans = db.session.scalars(
            query.options(
                joinedload(Plan.department),
                selectinload(Plan.items).joinedload(PlanItem.publication),
                selectinload(Plan.items).joinedload(PlanItem.publication_type),
            )
        ).all()
    elif plan is not None:
        plans = [plan]
    pairs = [
        (current_plan, item)
        for current_plan in plans
        for item in approved_items(current_plan)
        if publication_type_id is None or item["publication_type"]["id"] == publication_type_id
    ]
    publication_ids = {item.get("publication_id") for _, item in pairs} - {None}
    item_ids = {item["id"] for _, item in pairs if not item.get("publication_id")}
    publications = (
        db.session.scalars(
            select(Publication).where(
                or_(Publication.id.in_(publication_ids), Publication.plan_item_id.in_(item_ids))
            )
        ).all()
        if pairs
        else []
    )
    by_id = {p.id: p for p in publications}
    by_item = {p.plan_item_id: p for p in publications}
    result = []
    for current_plan, item in pairs:
        publication = by_id.get(item.get("publication_id")) or by_item.get(item["id"])
        actual = bool(
            publication
            and publication.department_id == current_plan.department_id
            and publication.status == "PUBLISHED"
            and publication.verification_status == "APPROVED"
            and publication.publication_year == current_plan.year
        )
        result.append({"plan": current_plan, "item": item, "publication": publication, "actual": int(actual)})
    return result


def plan_progress(plan, rows=None):
    rows = get_workload_rows(plan=plan) if rows is None else rows
    actual_count = sum(row["actual"] for row in rows)
    published = [row["publication"] for row in rows if row["publication"]]
    today = date.today()
    due = 0
    for row in rows:
        planned_date = row["item"].get("planned_date")
        deadline = date.fromisoformat(planned_date) if planned_date else date(plan.year, 12, 31)
        if deadline <= today and not row["actual"]:
            due += 1
    automatic = "COMPLETE" if rows and actual_count >= len(rows) else "RISK" if due else "ATTENTION"
    return {
        "plan": plan,
        "planned_count": len(rows),
        "created_count": len(published),
        "actual_count": actual_count,
        "pending_count": sum(p.verification_status == "PENDING" for p in published),
        "returned_count": sum(p.verification_status == "RETURNED" for p in published),
        "duplicate_count": sum(p.verification_status == "DUPLICATE" for p in published),
        "progress": calculate_progress(len(rows), actual_count),
        "overdue_count": due,
        "automatic_assessment": automatic,
        "assessment": plan.manual_assessment or automatic,
    }
