"""Explicit ORM loading plans for lists, detail views, and exports."""

from sqlalchemy.orm import joinedload, selectinload

from app.models import (
    Attachment,
    Plan,
    PlanItem,
    PlanItemAuthor,
    Publication,
    PublicationAuthor,
    PublicationHistory,
)


def plan_detail_options():
    return (
        joinedload(Plan.department),
        joinedload(Plan.creator),
        selectinload(Plan.items).joinedload(PlanItem.publication_type),
        selectinload(Plan.items).joinedload(PlanItem.quartile),
        selectinload(Plan.items).joinedload(PlanItem.publication),
        selectinload(Plan.items).selectinload(PlanItem.author_links).joinedload(PlanItemAuthor.employee),
    )


def publication_list_options():
    return (joinedload(Publication.department), joinedload(Publication.quartile))


def publication_report_options():
    return (
        *publication_list_options(),
        joinedload(Publication.plan_item).joinedload(PlanItem.plan),
        joinedload(Publication.indexing_type),
        joinedload(Publication.verifier),
    )


def publication_detail_options():
    return (
        *publication_report_options(),
        selectinload(Publication.author_links).joinedload(PublicationAuthor.employee),
        selectinload(Publication.attachments).joinedload(Attachment.uploader),
        selectinload(Publication.attachments).joinedload(Attachment.reviewer),
        selectinload(Publication.history).joinedload(PublicationHistory.user),
    )
