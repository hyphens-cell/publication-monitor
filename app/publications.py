from datetime import datetime
import os
import uuid

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user
from werkzeug.utils import secure_filename
from sqlalchemy import select

from app.access import ensure_department_access, get_scoped_department_id
from app.audit import audit
from app.auth import ROLE_ADMIN, ROLE_DEPARTMENT_HEAD, roles_required
from app.extensions import db
from app.models import (
    Attachment,
    Comment,
    Plan,
    Publication,
    PublicationAuthor,
    PublicationHistory,
    ReferenceValue,
)


PUBLICATION_STATUS_PREPARATION = "PREPARATION"
PUBLICATION_STATUS_SUBMITTED_TO_JOURNAL = "SUBMITTED_TO_JOURNAL"
PUBLICATION_STATUS_UNDER_REVIEW = "UNDER_REVIEW"
PUBLICATION_STATUS_REVISION_REQUIRED = "REVISION_REQUIRED"
PUBLICATION_STATUS_ACCEPTED = "ACCEPTED"
PUBLICATION_STATUS_PUBLISHED = "PUBLISHED"
PUBLICATION_STATUS_REJECTED = "REJECTED"


PUBLICATION_STATUSES = {
    PUBLICATION_STATUS_PREPARATION: "Подготовка статьи",
    PUBLICATION_STATUS_SUBMITTED_TO_JOURNAL: "Отправлена в журнал",
    PUBLICATION_STATUS_UNDER_REVIEW: "На рецензировании",
    PUBLICATION_STATUS_REVISION_REQUIRED: "Требуется доработка",
    PUBLICATION_STATUS_ACCEPTED: "Принята к публикации",
    PUBLICATION_STATUS_PUBLISHED: "Опубликована",
    PUBLICATION_STATUS_REJECTED: "Отклонена",
}


PUBLICATION_VERIFICATION_PENDING = "PENDING"
PUBLICATION_VERIFICATION_APPROVED = "APPROVED"
PUBLICATION_VERIFICATION_RETURNED = "RETURNED"
PUBLICATION_VERIFICATION_DUPLICATE = "DUPLICATE"


PUBLICATION_VERIFICATION_STATUSES = {
    PUBLICATION_VERIFICATION_PENDING: "На проверке",
    PUBLICATION_VERIFICATION_APPROVED: "Проверена",
    PUBLICATION_VERIFICATION_RETURNED: "Возвращена на доработку",
    PUBLICATION_VERIFICATION_DUPLICATE: "Дубликат",
}


ALLOWED_ATTACHMENT_EXTENSIONS = {
    "pdf",
    "doc",
    "docx",
    "jpg",
    "jpeg",
    "zip",
    "rar",
}


ALLOWED_PUBLICATION_STATUS_TRANSITIONS = {
    PUBLICATION_STATUS_PREPARATION: {
        PUBLICATION_STATUS_SUBMITTED_TO_JOURNAL,
        PUBLICATION_STATUS_REJECTED,
    },
    PUBLICATION_STATUS_SUBMITTED_TO_JOURNAL: {
        PUBLICATION_STATUS_UNDER_REVIEW,
        PUBLICATION_STATUS_REVISION_REQUIRED,
        PUBLICATION_STATUS_REJECTED,
    },
    PUBLICATION_STATUS_UNDER_REVIEW: {
        PUBLICATION_STATUS_REVISION_REQUIRED,
        PUBLICATION_STATUS_ACCEPTED,
        PUBLICATION_STATUS_REJECTED,
    },
    PUBLICATION_STATUS_REVISION_REQUIRED: {
        PUBLICATION_STATUS_SUBMITTED_TO_JOURNAL,
        PUBLICATION_STATUS_UNDER_REVIEW,
        PUBLICATION_STATUS_REJECTED,
    },
    PUBLICATION_STATUS_ACCEPTED: {
        PUBLICATION_STATUS_PUBLISHED,
        PUBLICATION_STATUS_REJECTED,
    },
    PUBLICATION_STATUS_PUBLISHED: set(),
    PUBLICATION_STATUS_REJECTED: set(),
}


def create_publications_from_plan(
    plan: Plan,
    user_id: int,
) -> list[Publication]:
    if plan.status != "APPROVED":
        raise ValueError(
            "Публикации можно создавать только из утверждённого плана."
        )

    publications: list[Publication] = []

    for item in plan.items:
        existing_publication = item.publication

        if existing_publication is not None:
            publications.append(existing_publication)
            continue

        publication = Publication(
            plan_item_id=item.id,
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

def is_allowed_attachment(filename):
    if "." not in filename:
        return False

    extension = filename.rsplit(".", 1)[1].lower()

    return extension in ALLOWED_ATTACHMENT_EXTENSIONS


def normalize_doi(value: str | None) -> str | None:
    """Return a canonical DOI suitable for storage and duplicate checks."""
    if not value:
        return None

    normalized = value.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "http://dx.doi.org/", "doi:"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
            break

    normalized = "".join(normalized.split())
    return normalized or None


def get_reference_values(reference_type):
    return db.session.scalars(
        select(ReferenceValue)
        .where(
            ReferenceValue.type == reference_type,
            ReferenceValue.is_active.is_(True),
        )
        .order_by(
            ReferenceValue.sort_order,
            ReferenceValue.name_ru,
        )
    ).all()

publications_bp = Blueprint(
    "publications",
    __name__,
    url_prefix="/publications",
)

def synchronize_publication_verification_status(
    publication: Publication,
) -> None:
    if (
        publication.verification_status
        == PUBLICATION_VERIFICATION_DUPLICATE
    ):
        return

    attachments = publication.attachments

    if not attachments:
        publication.verification_status = (
            PUBLICATION_VERIFICATION_PENDING
        )
        publication.verified_by = None
        publication.verified_at = None
        return

    review_statuses = {
        attachment.review_status
        for attachment in attachments
    }

    if "REJECTED" in review_statuses:
        publication.verification_status = (
            PUBLICATION_VERIFICATION_RETURNED
        )
        publication.verified_by = None
        publication.verified_at = None
        return

    if "PENDING" in review_statuses:
        publication.verification_status = (
            PUBLICATION_VERIFICATION_PENDING
        )
        publication.verified_by = None
        publication.verified_at = None
        return

    publication.verification_status = (
        PUBLICATION_VERIFICATION_PENDING
    )
    publication.verified_by = None
    publication.verified_at = None

@publications_bp.route("/")
@roles_required(ROLE_ADMIN, ROLE_DEPARTMENT_HEAD)
def publications():
    query = Publication.query

    verification_status = request.args.get(
        "verification_status",
        "",
    ).strip()

    department_id = request.args.get(
        "department_id",
        "",
    ).strip()
    plan_year = request.args.get(
        "plan_year",
        "",
    ).strip()

    if verification_status:
        if verification_status not in PUBLICATION_VERIFICATION_STATUSES:
            abort(400)

        query = query.filter(
            Publication.verification_status == verification_status
        )

    requested_department_id = None

    if department_id:
        try:
            requested_department_id = int(department_id)
        except ValueError:
            abort(400)

    ensure_department_access(
        requested_department_id
    )

    department_id_value = get_scoped_department_id(
        requested_department_id
    )

    if department_id_value is not None:
        query = query.filter(
            Publication.department_id == department_id_value
        )

    if plan_year:
        try:
            plan_year_value = int(plan_year)
        except ValueError:
            abort(400)

        query = query.join(
            Publication.plan_item
        ).filter(
            Plan.year == plan_year_value
        )

    publications_list = query.order_by(
        Publication.created_at.desc(),
        Publication.id.desc(),
    ).all()

    return render_template(
        "publications/list.html",
        publications=publications_list,
    )


@publications_bp.route("/<int:publication_id>")
@roles_required(ROLE_ADMIN, ROLE_DEPARTMENT_HEAD)
def publication_detail(publication_id):
    publication = db.session.get(
        Publication,
        publication_id,
    )

    if publication is None:
        abort(404)

    ensure_department_access(
        publication.department_id
    )

    doi_conflicts = find_doi_conflicts(publication)

    return render_template(
        "publications/detail.html",
        publication=publication,
        publication_statuses=PUBLICATION_STATUSES,
        allowed_statuses=ALLOWED_PUBLICATION_STATUS_TRANSITIONS.get(
            publication.status,
            set(),
        ),
        publication_verification_statuses=PUBLICATION_VERIFICATION_STATUSES,
        doi_conflicts=doi_conflicts,
    )

@publications_bp.route(
    "/<int:publication_id>/edit",
    methods=["GET", "POST"],
)
@roles_required(ROLE_DEPARTMENT_HEAD)
def edit_publication(publication_id):
    publication = db.session.get(
        Publication,
        publication_id,
    )

    if publication is None:
        abort(404)

    ensure_department_access(
        publication.department_id
    )

    indexing_types = get_reference_values("INDEXING_TYPE")
    quartiles = get_reference_values("QUARTILE")

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        doi = request.form.get("doi", "").strip()
        url = request.form.get("url", "").strip()
        journal = request.form.get("journal", "").strip()
        publication_year = request.form.get(
            "publication_year",
            "",
        ).strip()
        volume = request.form.get("volume", "").strip()
        issue = request.form.get("issue", "").strip()
        pages = request.form.get("pages", "").strip()
        indexing_type_id = request.form.get(
            "indexing_type_id",
            "",
        ).strip()
        quartile_id = request.form.get(
            "quartile_id",
            "",
        ).strip()
        affiliation = request.form.get(
            "affiliation",
            "",
        ).strip()
        notes = request.form.get(
            "notes",
            "",
        ).strip()

        errors = []

        if not title:
            errors.append("Введите название публикации.")

        

        publication_year_value = None

        if publication_year:
            try:
                publication_year_value = int(publication_year)
            except ValueError:
                errors.append(
                    "Год публикации должен быть числом."
                )
            else:
                if not 1900 <= publication_year_value <= 2100:
                    errors.append(
                        "Введите корректный год публикации."
                    )

        indexing_type = None

        if indexing_type_id:
            try:
                indexing_type_id_value = int(indexing_type_id)
            except ValueError:
                indexing_type_id_value = None
                errors.append(
                    "Выбран некорректный тип индексации."
                )

            if indexing_type_id_value is not None:
                indexing_type = db.session.scalar(
                    select(ReferenceValue).where(
                        ReferenceValue.id == indexing_type_id_value,
                        ReferenceValue.type == "INDEXING_TYPE",
                        ReferenceValue.is_active.is_(True),
                    )
                )

                if indexing_type is None:
                    errors.append(
                        "Выбран некорректный тип индексации."
                    )

        quartile = None

        if quartile_id:
            try:
                quartile_id_value = int(quartile_id)
            except ValueError:
                quartile_id_value = None
                errors.append(
                    "Выбран некорректный квартиль."
                )

            if quartile_id_value is not None:
                quartile = db.session.scalar(
                    select(ReferenceValue).where(
                        ReferenceValue.id == quartile_id_value,
                        ReferenceValue.type == "QUARTILE",
                        ReferenceValue.is_active.is_(True),
                    )
                )

                if quartile is None:
                    errors.append(
                        "Выбран некорректный квартиль."
                    )

        if errors:
            for error in errors:
                flash(error, "danger")

            return render_template(
                "publications/form.html",
                publication=publication,
                indexing_types=indexing_types,
                quartiles=quartiles,
            )

        publication.title = title
        publication.doi = normalize_doi(doi)
        publication.url = url or None
        publication.journal = journal or None
        publication.publication_year = publication_year_value
        publication.volume = volume or None
        publication.issue = issue or None
        publication.pages = pages or None
        publication.indexing_type_id = (
            indexing_type.id
            if indexing_type
            else None
        )
        publication.quartile_id = (
            quartile.id
            if quartile
            else None
        )
        publication.affiliation = affiliation or None
        publication.notes = notes or None

        audit(
            "PUBLICATION_UPDATED",
            entity_type="Publication",
            entity_id=publication.id,
            details={
                "title": publication.title,
                "doi": publication.doi,
                "journal": publication.journal,
                "publication_year": publication.publication_year,
                "indexing_type_id": publication.indexing_type_id,
                "quartile_id": publication.quartile_id,
            },
        )

        db.session.commit()

        flash(
            "Данные публикации сохранены.",
            "success",
        )

        return redirect(
            url_for(
                "publications.publication_detail",
                publication_id=publication.id,
            )
        )

    return render_template(
        "publications/form.html",
        publication=publication,
        indexing_types=indexing_types,
        quartiles=quartiles,
    )

@publications_bp.route(
    "/<int:publication_id>/status",
    methods=["POST"],
)
@roles_required(ROLE_DEPARTMENT_HEAD)
def change_publication_status(publication_id):
    publication = db.session.get(
        Publication,
        publication_id,
    )

    if publication is None:
        abort(404)

    ensure_department_access(
        publication.department_id
    )

    new_status = request.form.get(
        "status",
        "",
    ).strip()

    if new_status not in PUBLICATION_STATUSES:
        flash(
            "Выбран некорректный статус.",
            "danger",
        )

        return redirect(
            url_for(
                "publications.publication_detail",
                publication_id=publication.id,
            )
        )

    allowed_statuses = ALLOWED_PUBLICATION_STATUS_TRANSITIONS.get(
        publication.status,
        set(),
    )

    if new_status not in allowed_statuses:
        flash(
            "Недопустимый переход статуса публикации.",
            "danger",
        )

        return redirect(
            url_for(
                "publications.publication_detail",
                publication_id=publication.id,
            )
        )

    old_status = publication.status

    publication.status = new_status

    db.session.add(
        PublicationHistory(
            publication_id=publication.id,
            user_id=current_user.id,
            old_status=old_status,
            new_status=new_status,
        )
    )

    audit(
        "PUBLICATION_STATUS_CHANGED",
        entity_type="Publication",
        entity_id=publication.id,
        details={
            "old_status": old_status,
            "new_status": new_status,
        },
    )

    db.session.commit()

    flash(
        "Статус публикации изменён.",
        "success",
    )

    return redirect(
        url_for(
            "publications.publication_detail",
            publication_id=publication.id,
        )
    )

@publications_bp.route(
    "/<int:publication_id>/attachments",
    methods=["POST"],
)
@roles_required(ROLE_DEPARTMENT_HEAD)
def upload_publication_attachment(publication_id):
    publication = db.session.get(
        Publication,
        publication_id,
    )

    if publication is None:
        abort(404)

    ensure_department_access(
        publication.department_id
    )

    uploaded_file = request.files.get("file")

    if uploaded_file is None:
        flash(
            "Выберите файл.",
            "danger",
        )

        return redirect(
            url_for(
                "publications.publication_detail",
                publication_id=publication.id,
            )
        )

    original_filename = secure_filename(
        uploaded_file.filename or ""
    )

    if not original_filename:
        flash(
            "Некорректное имя файла.",
            "danger",
        )

        return redirect(
            url_for(
                "publications.publication_detail",
                publication_id=publication.id,
            )
        )

    if not is_allowed_attachment(original_filename):
        flash(
            "Недопустимый формат файла. Разрешены: PDF, DOC, DOCX, JPG, JPEG, ZIP, RAR.",
            "danger",
        )

        return redirect(
            url_for(
                "publications.publication_detail",
                publication_id=publication.id,
            )
        )

    upload_directory = os.path.join(
        current_app.instance_path,
        "uploads",
        "publications",
    )

    os.makedirs(
        upload_directory,
        exist_ok=True,
    )

    extension = original_filename.rsplit(
        ".",
        1,
    )[1].lower()

    stored_filename = (
        f"{uuid.uuid4().hex}.{extension}"
    )

    file_path = os.path.join(
        upload_directory,
        stored_filename,
    )

    uploaded_file.save(file_path)

    file_size = os.path.getsize(file_path)

    attachment = Attachment(
        publication_id=publication.id,
        original_filename=original_filename,
        stored_filename=stored_filename,
        file_path=file_path,
        mime_type=uploaded_file.mimetype,
        file_size=file_size,
        uploaded_by=current_user.id,
    )

    db.session.add(attachment)
    db.session.flush()

    audit(
        "ATTACHMENT_UPLOADED",
        entity_type="Attachment",
        entity_id=attachment.id,
        details={
            "publication_id": publication.id,
            "original_filename": attachment.original_filename,
            "mime_type": attachment.mime_type,
            "file_size": attachment.file_size,
        },
    )

    if (
        publication.verification_status
        != PUBLICATION_VERIFICATION_DUPLICATE
    ):
        publication.verification_status = (
            PUBLICATION_VERIFICATION_PENDING
        )
        publication.verified_by = None
        publication.verified_at = None

    db.session.commit()

    flash(
        "Файл загружен.",
        "success",
    )

    return redirect(
        url_for(
            "publications.publication_detail",
            publication_id=publication.id,
        )
    )



@publications_bp.route(
    "/<int:publication_id>/attachments/<int:attachment_id>/download",
)
@roles_required(ROLE_ADMIN, ROLE_DEPARTMENT_HEAD)
def download_publication_attachment(publication_id, attachment_id):
    publication = db.session.get(Publication, publication_id)

    if publication is None:
        abort(404)

    ensure_department_access(
        publication.department_id
    )

    attachment = db.session.get(Attachment, attachment_id)

    if attachment is None or attachment.publication_id != publication.id:
        abort(404)

    if not os.path.isfile(attachment.file_path):
        abort(404)

    return send_file(
        attachment.file_path,
        as_attachment=True,
        download_name=attachment.original_filename,
        mimetype=attachment.mime_type,
    )



@publications_bp.route(
    "/<int:publication_id>/attachments/<int:attachment_id>/delete",
    methods=["POST"],
)
@roles_required(ROLE_DEPARTMENT_HEAD)
def delete_publication_attachment(
    publication_id,
    attachment_id,
):
    publication = db.session.get(
        Publication,
        publication_id,
    )

    if publication is None:
        abort(404)

    ensure_department_access(
        publication.department_id
    )

    attachment = db.session.get(
        Attachment,
        attachment_id,
    )

    if (
        attachment is None
        or attachment.publication_id != publication.id
    ):
        abort(404)

    if attachment.uploaded_by != current_user.id:
        abort(403)

    if os.path.isfile(attachment.file_path):
        os.remove(attachment.file_path)

    audit(
        "ATTACHMENT_DELETED",
        entity_type="Attachment",
        entity_id=attachment.id,
        details={
            "publication_id": publication.id,
            "original_filename": attachment.original_filename,
            "file_size": attachment.file_size,
        },
    )

    db.session.delete(attachment)
    db.session.flush()

    synchronize_publication_verification_status(
        publication
    )

    db.session.commit()

    flash(
        "Файл удалён.",
        "success",
    )

    return redirect(
        url_for(
            "publications.publication_detail",
            publication_id=publication.id,
        )
    )


@publications_bp.route(
    "/<int:publication_id>/attachments/<int:attachment_id>/approve",
    methods=["POST"],
)
@roles_required(ROLE_ADMIN)
def approve_publication_attachment(
    publication_id,
    attachment_id,
):
    publication = db.session.get(
        Publication,
        publication_id,
    )

    if publication is None:
        abort(404)

    attachment = db.session.get(
        Attachment,
        attachment_id,
    )

    if (
        attachment is None
        or attachment.publication_id != publication.id
    ):
        abort(404)

    if (
        publication.verification_status
        == PUBLICATION_VERIFICATION_DUPLICATE
    ):
        flash(
            "Нельзя проверять файл публикации, признанной дубликатом.",
            "danger",
        )

        return redirect(
            url_for(
                "publications.publication_detail",
                publication_id=publication.id,
            )
        )

    attachment.review_status = "APPROVED"
    attachment.reviewed_by = current_user.id
    attachment.reviewed_at = datetime.utcnow()
    attachment.review_comment = None

    synchronize_publication_verification_status(
        publication
    )

    publication.verified_by = None
    publication.verified_at = None

    audit(
        "ATTACHMENT_APPROVED",
        entity_type="Attachment",
        entity_id=attachment.id,
        details={
            "publication_id": publication.id,
            "publication_verification_status": publication.verification_status,
        },
    )

    db.session.commit()

    flash(
        "Файл принят.",
        "success",
    )

    return redirect(
        url_for(
            "publications.publication_detail",
            publication_id=publication.id,
        )
    )


@publications_bp.route(
    "/<int:publication_id>/attachments/<int:attachment_id>/reject",
    methods=["POST"],
)
@roles_required(ROLE_ADMIN)
def reject_publication_attachment(
    publication_id,
    attachment_id,
):
    publication = db.session.get(
        Publication,
        publication_id,
    )

    if publication is None:
        abort(404)

    attachment = db.session.get(
        Attachment,
        attachment_id,
    )

    if (
        attachment is None
        or attachment.publication_id != publication.id
    ):
        abort(404)

    if (
        publication.verification_status
        == PUBLICATION_VERIFICATION_DUPLICATE
    ):
        flash(
            "Нельзя проверять файл публикации, признанной дубликатом.",
            "danger",
        )

        return redirect(
            url_for(
                "publications.publication_detail",
                publication_id=publication.id,
            )
        )

    comment = request.form.get(
        "comment",
        "",
    ).strip()

    if not comment:
        flash(
            "Укажите причину отклонения файла.",
            "danger",
        )

        return redirect(
            url_for(
                "publications.publication_detail",
                publication_id=publication.id,
            )
        )

    attachment.review_status = "REJECTED"
    attachment.reviewed_by = current_user.id
    attachment.reviewed_at = datetime.utcnow()
    attachment.review_comment = comment

    synchronize_publication_verification_status(
        publication
    )

    db.session.add(
        Comment(
            user_id=current_user.id,
            entity_type="ATTACHMENT",
            entity_id=attachment.id,
            text=comment,
        )
    )

    audit(
        "ATTACHMENT_REJECTED",
        entity_type="Attachment",
        entity_id=attachment.id,
        details={
            "publication_id": publication.id,
            "comment": comment,
            "publication_verification_status": publication.verification_status,
        },
    )

    db.session.commit()

    flash(
        "Файл отклонён.",
        "warning",
    )

    return redirect(
        url_for(
            "publications.publication_detail",
            publication_id=publication.id,
        )
    )

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

    normalized_journal = (
        publication.journal.strip().lower()
        if publication.journal
        else None
    )

    if normalized_title and normalized_journal:
        candidate_query = select(Publication).where(
            Publication.id != publication.id,
            Publication.title.is_not(None),
            Publication.journal.is_not(None),
        )

        if publication.publication_year is not None:
            candidate_query = candidate_query.where(
                Publication.publication_year
                == publication.publication_year
            )

        candidate_publications = db.session.scalars(
            candidate_query
        ).all()

        for candidate in candidate_publications:
            candidate_title = (
                candidate.title.strip().lower()
                if candidate.title
                else ""
            )

            candidate_journal = (
                candidate.journal.strip().lower()
                if candidate.journal
                else ""
            )

            if (
                candidate_title == normalized_title
                and candidate_journal == normalized_journal
            ):
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

@publications_bp.route(
    "/<int:publication_id>/resolve-doi",
    methods=["POST"],
)
@roles_required(ROLE_ADMIN)
def resolve_doi_conflict(publication_id):
    publication = db.session.get(
        Publication,
        publication_id,
    )

    if publication is None:
        abort(404)

    conflict_id = request.form.get(
        "conflict_id",
        "",
    ).strip()

    action = request.form.get(
        "action",
        "",
    ).strip()

    try:
        conflict_id_value = int(conflict_id)
    except ValueError:
        flash(
            "Некорректный идентификатор конфликтующей публикации.",
            "danger",
        )

        return redirect(
            url_for(
                "publications.publication_detail",
                publication_id=publication.id,
            )
        )

    conflict = db.session.get(
        Publication,
        conflict_id_value,
    )

    if conflict is None:
        abort(404)

    if conflict.id == publication.id:
        flash(
            "Нельзя разрешить конфликт публикации с самой собой.",
            "danger",
        )

        return redirect(
            url_for(
                "publications.publication_detail",
                publication_id=publication.id,
            )
        )

    publication_doi = normalize_doi(publication.doi)
    conflict_doi = normalize_doi(conflict.doi)

    if not publication_doi or publication_doi != conflict_doi:
        flash(
            "У публикаций нет одинакового DOI.",
            "danger",
        )

        return redirect(
            url_for(
                "publications.publication_detail",
                publication_id=publication.id,
            )
        )

    if action == "keep_current":
        winner = publication
        loser = conflict

    elif action == "keep_conflict":
        winner = conflict
        loser = publication

    else:
        flash(
            "Некорректное решение по конфликту DOI.",
            "danger",
        )

        return redirect(
            url_for(
                "publications.publication_detail",
                publication_id=publication.id,
            )
        )

    winner.verification_status = (
        PUBLICATION_VERIFICATION_APPROVED
    )
    winner.verified_by = current_user.id
    winner.verified_at = datetime.utcnow()

    loser.verification_status = (
        PUBLICATION_VERIFICATION_DUPLICATE
    )
    loser.verified_by = current_user.id
    loser.verified_at = datetime.utcnow()

    db.session.add(
        Comment(
            user_id=current_user.id,
            entity_type="PUBLICATION",
            entity_id=winner.id,
            text=(
                "Монитор разрешил конфликт DOI. "
                f"Выбрана публикация №{winner.id}."
            ),
        )
    )

    db.session.add(
        Comment(
            user_id=current_user.id,
            entity_type="PUBLICATION",
            entity_id=loser.id,
            text=(
                "Публикация признана дубликатом "
                f"публикации №{winner.id} "
                "по результату проверки DOI."
            ),
        )
    )

    audit(
        "PUBLICATION_DOI_CONFLICT_RESOLVED",
        entity_type="Publication",
        entity_id=winner.id,
        details={
            "winner_id": winner.id,
            "duplicate_id": loser.id,
            "action": action,
        },
    )

    db.session.commit()

    flash(
        f"Конфликт DOI разрешён. "
        f"Публикация №{winner.id} оставлена.",
        "success",
    )

    return redirect(
        url_for(
            "publications.publication_detail",
            publication_id=winner.id,
        )
    )

@publications_bp.route(
    "/<int:publication_id>/verify",
    methods=["POST"],
)
@roles_required(ROLE_ADMIN)
def verify_publication(publication_id):
    publication = db.session.get(
        Publication,
        publication_id,
    )

    if publication is None:
        abort(404)

    errors = []

    if publication.plan_item is None:
        errors.append(
            "Публикация не связана с пунктом плана."
        )
    else:
        plan = publication.plan_item.plan

        if plan is None:
            errors.append(
                "Для публикации не найден план."
            )
        else:
            if plan.status != "APPROVED":
                errors.append(
                    "Связанный план не утверждён."
                )

            if publication.department_id != plan.department_id:
                errors.append(
                    "Кафедра публикации не соответствует кафедре плана."
                )

            if (
                publication.title.strip()
                != publication.plan_item.title.strip()
            ):
                errors.append(
                    "Название публикации не соответствует утверждённому плану."
                )

            planned_journal = (
                publication.plan_item.journal or ""
            ).strip()

            publication_journal = (
                publication.journal or ""
            ).strip()

            if planned_journal != publication_journal:
                errors.append(
                    "Журнал публикации не соответствует утверждённому плану."
                )

            if (
                publication.quartile_id
                != publication.plan_item.quartile_id
            ):
                errors.append(
                    "Квартиль публикации не соответствует утверждённому плану."
                )

            planned_author_ids = [
                author_link.employee_id
                for author_link in publication.plan_item.author_links
            ]

            publication_author_ids = [
                author_link.employee_id
                for author_link in publication.author_links
            ]

            if planned_author_ids != publication_author_ids:
                errors.append(
                    "Состав или порядок авторов не соответствует утверждённому плану."
                )

    if not publication.title.strip():
        errors.append(
            "Не указано название публикации."
        )

    if not publication.journal or not publication.journal.strip():
        errors.append(
            "Не указан журнал."
        )

    if not publication.author_links:
        errors.append(
            "Не указаны авторы публикации."
        )

    if not publication.affiliation or not publication.affiliation.strip():
        errors.append(
            "Не указана аффилиация."
        )

    duplicates = find_publication_duplicates(publication)

    if duplicates:
        conflict_ids = ", ".join(str(item.id) for item in duplicates)
        errors.append(
            "Обнаружены возможные дубликаты: публикации № "
            f"{conflict_ids}. Сначала необходимо разрешить конфликт монитором."
        )

    if not publication.attachments:
        errors.append(
            "Не загружен подтверждающий файл."
        )
    else:
        not_approved_attachments = [
            attachment
            for attachment in publication.attachments
            if attachment.review_status != "APPROVED"
        ]

        if not_approved_attachments:
            errors.append(
                "Необходимо дождаться проверки всех подтверждающих файлов."
            )

    if errors:
        flash(
            "Публикация не может быть подтверждена:",
            "danger",
        )

        for error in errors:
            flash(
                error,
                "danger",
            )

        return redirect(
            url_for(
                "publications.publication_detail",
                publication_id=publication.id,
            )
        )

    publication.verification_status = (
        PUBLICATION_VERIFICATION_APPROVED
    )
    publication.verified_by = current_user.id
    publication.verified_at = datetime.utcnow()

    audit(
        "PUBLICATION_VERIFIED",
        entity_type="Publication",
        entity_id=publication.id,
        details={
            "verification_status": publication.verification_status,
            "verified_at": publication.verified_at.isoformat(),
        },
    )

    db.session.commit()

    flash(
        "Публикация подтверждена.",
        "success",
    )

    return redirect(
        url_for(
            "publications.publication_detail",
            publication_id=publication.id,
        )
    )


@publications_bp.route(
    "/<int:publication_id>/return",
    methods=["POST"],
)
@roles_required(ROLE_ADMIN)
def return_publication(publication_id):
    publication = db.session.get(
        Publication,
        publication_id,
    )

    if publication is None:
        abort(404)

    comment_text = request.form.get(
        "comment",
        "",
    ).strip()

    if not comment_text:
        flash(
            "Укажите замечание.",
            "danger",
        )

        return redirect(
            url_for(
                "publications.publication_detail",
                publication_id=publication.id,
            )
        )

    publication.verification_status = (
        PUBLICATION_VERIFICATION_RETURNED
    )
    publication.verified_by = current_user.id
    publication.verified_at = datetime.utcnow()

    db.session.add(
        Comment(
            user_id=current_user.id,
            entity_type="PUBLICATION",
            entity_id=publication.id,
            text=comment_text,
        )
    )

    audit(
        "PUBLICATION_RETURNED",
        entity_type="Publication",
        entity_id=publication.id,
        details={
            "verification_status": publication.verification_status,
            "comment": comment_text,
        },
    )

    db.session.commit()

    flash(
        "Публикация возвращена на доработку.",
        "warning",
    )

    return redirect(
        url_for(
            "publications.publication_detail",
            publication_id=publication.id,
        )
    )
