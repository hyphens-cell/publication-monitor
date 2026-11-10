"""Publication use cases participate in the caller's database transaction."""

from sqlalchemy import select

from app.audit import audit
from app.domain.publications import (
    PUBLICATION_STATUS_PREPARATION,
    PUBLICATION_VERIFICATION_DUPLICATE,
    PUBLICATION_VERIFICATION_PENDING,
    PUBLICATION_VERIFICATION_RETURNED,
    normalize_doi,
)
from app.extensions import db
from app.models import Plan, Publication, PublicationAuthor, PublicationHistory


def create_publications_from_plan(
    plan: Plan,
    user_id: int,
) -> list[Publication]:
    if plan.status != "APPROVED":
        raise ValueError("Публикации можно создавать только из утверждённого плана.")

    publications: list[Publication] = []

    for item in plan.items:
        existing_publication = item.publication

        if existing_publication is not None:
            publications.append(existing_publication)
            continue

        publication = Publication(
            plan_item=item,
            department_id=plan.department_id,
            title=item.title,
            journal=item.journal,
            quartile_id=item.quartile_id,
            status=PUBLICATION_STATUS_PREPARATION,
        )

        db.session.add(publication)
        db.session.flush()

        for author_order, author_link in enumerate(
            item.author_links,
            start=1,
        ):
            publication_author = PublicationAuthor(
                publication_id=publication.id,
                employee_id=author_link.employee_id,
                author_order=author_order,
            )

            db.session.add(publication_author)

        publication_history = PublicationHistory(
            publication_id=publication.id,
            user_id=user_id,
            old_status=None,
            new_status=PUBLICATION_STATUS_PREPARATION,
        )

        db.session.add(publication_history)

        audit(
            "PUBLICATION_CREATED",
            entity_type="Publication",
            entity_id=publication.id,
            details={
                "plan_item_id": item.id,
                "department_id": plan.department_id,
                "title": publication.title,
                "journal": publication.journal,
                "status": publication.status,
            },
        )

        publications.append(publication)

    return publications


def synchronize_publication_verification_status(
    publication: Publication,
) -> None:
    if publication.verification_status == PUBLICATION_VERIFICATION_DUPLICATE:
        return

    attachments = publication.attachments

    if not attachments:
        publication.verification_status = PUBLICATION_VERIFICATION_PENDING
        publication.verified_by = None
        publication.verified_at = None
        return

    review_statuses = {attachment.review_status for attachment in attachments}

    if "REJECTED" in review_statuses:
        publication.verification_status = PUBLICATION_VERIFICATION_RETURNED
        publication.verified_by = None
        publication.verified_at = None
        return

    if "PENDING" in review_statuses:
        publication.verification_status = PUBLICATION_VERIFICATION_PENDING
        publication.verified_by = None
        publication.verified_at = None
        return

    publication.verification_status = PUBLICATION_VERIFICATION_PENDING
    publication.verified_by = None
    publication.verified_at = None


def publication_snapshot(publication):
    fields = (
        "title",
        "doi",
        "url",
        "journal",
        "publication_year",
        "volume",
        "issue",
        "pages",
        "indexing_type_id",
        "quartile_id",
        "affiliation",
        "notes",
    )
    result = {field: getattr(publication, field) for field in fields}
    result["author_ids"] = [link.employee_id for link in publication.author_links]
    return result


def find_publication_duplicates(publication):
    duplicates = {}

    normalized_doi = normalize_doi(publication.doi)

    if normalized_doi:
        candidate_publications = db.session.scalars(
            select(Publication).where(
                Publication.id != publication.id,
                Publication.doi.is_not(None),
            )
        ).all()

        for candidate in candidate_publications:
            candidate_doi = normalize_doi(candidate.doi)

            if candidate_doi == normalized_doi:
                duplicates[candidate.id] = candidate

    normalized_title = publication.title.strip().lower()

    normalized_journal = publication.journal.strip().lower() if publication.journal else None

    if normalized_title and normalized_journal:
        candidate_query = select(Publication).where(
            Publication.id != publication.id,
            Publication.title.is_not(None),
            Publication.journal.is_not(None),
        )

        if publication.publication_year is not None:
            candidate_query = candidate_query.where(
                Publication.publication_year == publication.publication_year
            )

        candidate_publications = db.session.scalars(candidate_query).all()

        for candidate in candidate_publications:
            candidate_title = candidate.title.strip().lower() if candidate.title else ""

            candidate_journal = candidate.journal.strip().lower() if candidate.journal else ""

            if candidate_title == normalized_title and candidate_journal == normalized_journal:
                duplicates[candidate.id] = candidate

    return list(duplicates.values())


def find_doi_conflicts(publication):
    if not publication.doi:
        return []

    normalized_doi = normalize_doi(publication.doi)
    candidates = db.session.scalars(
        select(Publication).where(
            Publication.id != publication.id,
            Publication.doi.is_not(None),
        )
    ).all()
    return [item for item in candidates if normalize_doi(item.doi) == normalized_doi]
