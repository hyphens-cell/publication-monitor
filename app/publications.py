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
from sqlalchemy import func, select

from app.auth import roles_required
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

        publications.append(publication)

    return publications

def is_allowed_attachment(filename):
    if "." not in filename:
        return False

    extension = filename.rsplit(".", 1)[1].lower()

    return extension in ALLOWED_ATTACHMENT_EXTENSIONS


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


@publications_bp.route("/")
@roles_required("ADMIN", "DEPARTMENT_HEAD")
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

    if department_id:
        try:
            department_id_value = int(department_id)
        except ValueError:
            abort(400)

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

    if current_user.role == "DEPARTMENT_HEAD":
        if current_user.department_id is None:
            abort(403)

        query = query.filter(
            Publication.department_id == current_user.department_id
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
@roles_required("ADMIN", "DEPARTMENT_HEAD")
def publication_detail(publication_id):
    publication = db.session.get(
        Publication,
        publication_id,
    )

    if publication is None:
        abort(404)

    if (
        current_user.role == "DEPARTMENT_HEAD"
        and publication.department_id != current_user.department_id
    ):
        abort(403)

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
@roles_required("ADMIN", "DEPARTMENT_HEAD")
def edit_publication(publication_id):
    publication = db.session.get(
        Publication,
        publication_id,
    )

    if publication is None:
        abort(404)

    if (
        current_user.role == "DEPARTMENT_HEAD"
        and publication.department_id != current_user.department_id
    ):
        abort(403)

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
        publication.doi = doi or None
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
@roles_required("DEPARTMENT_HEAD")
def change_publication_status(publication_id):
    publication = db.session.get(
        Publication,
        publication_id,
    )

    if publication is None:
        abort(404)

    if publication.department_id != current_user.department_id:
        abort(403)

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
@roles_required("DEPARTMENT_HEAD")
def upload_publication_attachment(publication_id):
    publication = db.session.get(
        Publication,
        publication_id,
    )

    if publication is None:
        abort(404)

    if publication.department_id != current_user.department_id:
        abort(403)

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
@roles_required("ADMIN", "DEPARTMENT_HEAD")
def download_publication_attachment(publication_id, attachment_id):
    publication = db.session.get(Publication, publication_id)

    if publication is None:
        abort(404)

    if (
        current_user.role == "DEPARTMENT_HEAD"
        and publication.department_id != current_user.department_id
    ):
        abort(403)

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
@roles_required("DEPARTMENT_HEAD")
def delete_publication_attachment(publication_id, attachment_id):
    publication = db.session.get(Publication, publication_id)

    if publication is None:
        abort(404)

    if publication.department_id != current_user.department_id:
        abort(403)

    attachment = db.session.get(Attachment, attachment_id)

    if attachment is None or attachment.publication_id != publication.id:
        abort(404)

    if attachment.uploaded_by != current_user.id:
        abort(403)

    if os.path.isfile(attachment.file_path):
        os.remove(attachment.file_path)

    db.session.delete(attachment)
    db.session.commit()

    flash("Файл удалён.", "success")

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
@roles_required("ADMIN")
def approve_publication_attachment(publication_id, attachment_id):
    publication = db.session.get(Publication, publication_id)

    if publication is None:
        abort(404)

    attachment = db.session.get(Attachment, attachment_id)

    if attachment is None or attachment.publication_id != publication.id:
        abort(404)

    attachment.review_status = "APPROVED"
    attachment.reviewed_by = current_user.id
    attachment.reviewed_at = datetime.utcnow()
    attachment.review_comment = None

    db.session.commit()

    flash("Файл принят.", "success")

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
@roles_required("ADMIN")
def reject_publication_attachment(publication_id, attachment_id):
    publication = db.session.get(Publication, publication_id)

    if publication is None:
        abort(404)

    attachment = db.session.get(Attachment, attachment_id)

    if attachment is None or attachment.publication_id != publication.id:
        abort(404)

    comment = request.form.get("comment", "").strip()

    if not comment:
        flash("Укажите причину отклонения файла.", "danger")

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

    db.session.add(
        Comment(
            user_id=current_user.id,
            entity_type="ATTACHMENT",
            entity_id=attachment.id,
            text=comment,
        )
    )

    db.session.commit()

    flash("Файл отклонён.", "warning")

    return redirect(
        url_for(
            "publications.publication_detail",
            publication_id=publication.id,
        )
    )

def find_publication_duplicates(publication):
    duplicates = {}

    normalized_doi = (
        publication.doi.strip().lower()
        if publication.doi
        else None
    )

    if normalized_doi:
        candidate_publications = db.session.scalars(
            select(Publication).where(
                Publication.id != publication.id,
                Publication.doi.is_not(None),
            )
        ).all()

        for candidate in candidate_publications:
            candidate_doi = (
                candidate.doi.strip().lower()
                if candidate.doi
                else None
            )

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

    normalized_doi = publication.doi.strip().lower()

    return db.session.scalars(
        select(Publication).where(
            Publication.id != publication.id,
            Publication.doi.is_not(None),
            func.lower(Publication.doi) == normalized_doi,
        )
    ).all()

@publications_bp.route(
    "/<int:publication_id>/resolve-doi",
    methods=["POST"],
)
@roles_required("ADMIN")
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

    publication_doi = (
        publication.doi.strip().lower()
        if publication.doi
        else None
    )

    conflict_doi = (
        conflict.doi.strip().lower()
        if conflict.doi
        else None
    )

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
@roles_required("ADMIN")
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

    doi_conflicts = find_doi_conflicts(
        publication
    )

    if doi_conflicts:
        conflict_ids = ", ".join(
            str(conflict.id)
            for conflict in doi_conflicts
        )

        errors.append(
            "Обнаружен конфликт DOI. "
            f"Публикации с таким DOI: № {conflict_ids}. "
            "Сначала необходимо разрешить конфликт монитором."
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
@roles_required("ADMIN")
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