"""Shared active reference catalogue queries."""

from sqlalchemy import select

from app.extensions import db
from app.models import ReferenceValue


def get_reference_values(reference_type):
    return db.session.scalars(
        select(ReferenceValue)
        .where(ReferenceValue.type == reference_type, ReferenceValue.is_active.is_(True))
        .order_by(ReferenceValue.sort_order, ReferenceValue.name_ru, ReferenceValue.id)
    ).all()
