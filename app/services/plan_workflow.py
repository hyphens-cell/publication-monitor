"""Plan snapshots and versions are saved with their enclosing business change."""

from flask_login import current_user
from sqlalchemy import func, select

from app.extensions import db
from app.models import PlanVersion


def get_next_version_number(plan):
    current_max = db.session.scalar(
        select(func.max(PlanVersion.version_number)).where(PlanVersion.plan_id == plan.id)
    )

    return (current_max or 0) + 1


def serialize_plan(plan):
    return {
        "id": plan.id,
        "department_id": plan.department_id,
        "department_name": plan.department.name,
        "year": plan.year,
        "status": plan.status,
        "created_by": plan.created_by,
        "created_by_name": plan.creator.full_name,
        "submitted_at": (plan.submitted_at.isoformat() if plan.submitted_at else None),
        "approved_at": (plan.approved_at.isoformat() if plan.approved_at else None),
        "items": [
            {
                "id": item.id,
                "publication_id": item.publication.id if item.publication else None,
                "title": item.title,
                "publication_type": {
                    "id": item.publication_type.id,
                    "code": item.publication_type.code,
                    "name_ru": item.publication_type.name_ru,
                    "name_kk": item.publication_type.name_kk,
                },
                "journal": item.journal,
                "quartile": (
                    {
                        "id": item.quartile.id,
                        "code": item.quartile.code,
                        "name_ru": item.quartile.name_ru,
                        "name_kk": item.quartile.name_kk,
                    }
                    if item.quartile
                    else None
                ),
                "planned_date": (item.planned_date.isoformat() if item.planned_date else None),
                "status": item.status,
                "authors": [
                    {
                        "id": link.employee.id,
                        "full_name": link.employee.full_name,
                        "position": link.employee.position,
                    }
                    for link in item.author_links
                ],
            }
            for item in plan.items
        ],
    }


def create_plan_version(plan, status, comment=None):
    version = PlanVersion(
        plan_id=plan.id,
        version_number=get_next_version_number(plan),
        created_by=current_user.id,
        status=status,
        comment=comment,
        data=serialize_plan(plan),
    )

    db.session.add(version)

    return version
