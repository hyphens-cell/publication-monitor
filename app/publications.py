from datetime import datetime
from urllib.parse import urlsplit

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user
from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload

from app.access import ensure_department_access, get_scoped_department_id
from app.audit import audit
from app.auth import ROLE_ADMIN, ROLE_DEPARTMENT_HEAD, roles_required
from app.discussion import add_comment, comments_for, notify_participants
from app.domain.publications import (
    ALLOWED_ATTACHMENT_EXTENSIONS as ALLOWED_ATTACHMENT_EXTENSIONS,
)
from app.domain.publications import (
    ALLOWED_PUBLICATION_STATUS_TRANSITIONS as ALLOWED_PUBLICATION_STATUS_TRANSITIONS,
)
from app.domain.publications import (
    PUBLICATION_STATUS_ACCEPTED as PUBLICATION_STATUS_ACCEPTED,
)
from app.domain.publications import (
    PUBLICATION_STATUS_PREPARATION as PUBLICATION_STATUS_PREPARATION,
)
from app.domain.publications import (
    PUBLICATION_STATUS_PUBLISHED as PUBLICATION_STATUS_PUBLISHED,
)
from app.domain.publications import (
    PUBLICATION_STATUS_REJECTED as PUBLICATION_STATUS_REJECTED,
)
from app.domain.publications import (
    PUBLICATION_STATUS_REVISION_REQUIRED as PUBLICATION_STATUS_REVISION_REQUIRED,
)
from app.domain.publications import (
    PUBLICATION_STATUS_SUBMITTED_TO_JOURNAL as PUBLICATION_STATUS_SUBMITTED_TO_JOURNAL,
)
from app.domain.publications import (
    PUBLICATION_STATUS_UNDER_REVIEW as PUBLICATION_STATUS_UNDER_REVIEW,
)
from app.domain.publications import (
    PUBLICATION_STATUSES as PUBLICATION_STATUSES,
)
from app.domain.publications import (
    PUBLICATION_VERIFICATION_APPROVED as PUBLICATION_VERIFICATION_APPROVED,
)
from app.domain.publications import (
    PUBLICATION_VERIFICATION_DUPLICATE as PUBLICATION_VERIFICATION_DUPLICATE,
)
from app.domain.publications import (
    PUBLICATION_VERIFICATION_PENDING as PUBLICATION_VERIFICATION_PENDING,
)
from app.domain.publications import (
    PUBLICATION_VERIFICATION_RETURNED as PUBLICATION_VERIFICATION_RETURNED,
)
from app.domain.publications import (
    PUBLICATION_VERIFICATION_STATUSES as PUBLICATION_VERIFICATION_STATUSES,
)
from app.domain.publications import (
    normalize_doi as normalize_doi,
)
from app.extensions import db
from app.models import (
    Attachment,
    AuditLog,
    Comment,
    Department,
    Employee,
    Plan,
    PlanItem,
    Publication,
    PublicationAuthor,
    PublicationHistory,
    ReferenceValue,
)
from app.services.attachment_storage import attachment_path, delete_committed_file, staged_upload
from app.services.catalogue import get_reference_values
from app.services.listing import paginate, search_term, sort_order
from app.services.loading import publication_detail_options, publication_list_options
from app.services.publication_workflow import (
    create_publications_from_plan as create_publications_from_plan,
)
from app.services.publication_workflow import (
    find_doi_conflicts as find_doi_conflicts,
)
from app.services.publication_workflow import (
    find_publication_duplicates as find_publication_duplicates,
)
from app.services.publication_workflow import (
    publication_snapshot as publication_snapshot,
)
from app.services.publication_workflow import (
    synchronize_publication_verification_status as synchronize_publication_verification_status,
)


def is_allowed_attachment(filename):
    if "." not in filename:
        return False

    extension = filename.rsplit(".", 1)[1].lower()

    return extension in ALLOWED_ATTACHMENT_EXTENSIONS


publications_bp = Blueprint(
    "publications",
    __name__,
    url_prefix="/publications",
)


@publications_bp.route("/")
@roles_required(ROLE_ADMIN, ROLE_DEPARTMENT_HEAD)
def publications():
    query = select(Publication).options(*publication_list_options())

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

        query = query.filter(Publication.verification_status == verification_status)

    requested_department_id = None

    if department_id:
        try:
            requested_department_id = int(department_id)
        except ValueError:
            abort(400)

    ensure_department_access(requested_department_id)

    department_id_value = get_scoped_department_id(requested_department_id)

    if department_id_value is not None:
        query = query.filter(Publication.department_id == department_id_value)

    if plan_year:
        try:
            plan_year_value = int(plan_year)
        except ValueError:
            abort(400)

        query = (
            query.join(Publication.plan_item)
            .join(
                Plan,
                Plan.id == PlanItem.plan_id,
            )
            .filter(Plan.year == plan_year_value)
        )

    term = search_term(request.args)
    if term:
        query = query.where(
            or_(
                Publication.title.ilike(f"%{term}%", escape="\\"),
                Publication.doi.ilike(f"%{term}%", escape="\\"),
                Publication.journal.ilike(f"%{term}%", escape="\\"),
            )
        )
    order = sort_order(
        request.args,
        {
            "newest": Publication.created_at.desc(),
            "title": Publication.title.asc(),
            "title_desc": Publication.title.desc(),
            "year": Publication.publication_year.desc(),
        },
        "newest",
    )
    pagination = paginate(query.order_by(order, Publication.id.desc()), request.args)

    plan_years_query = select(Plan.year)
    if current_user.role == ROLE_DEPARTMENT_HEAD:
        plan_years_query = plan_years_query.where(
            Plan.department_id == current_user.department_id,
        )

    return render_template(
        "publications/list.html",
        publications=pagination.items,
        pagination=pagination,
        departments=(
            db.session.scalars(
                select(Department).where(Department.is_active.is_(True)).order_by(Department.name)
            ).all()
            if current_user.role == ROLE_ADMIN
            else []
        ),
        plan_years=db.session.scalars(plan_years_query.distinct().order_by(Plan.year.desc())).all(),
        verification_statuses=PUBLICATION_VERIFICATION_STATUSES,
        selected_verification_status=verification_status,
        selected_department_id=department_id_value,
        selected_plan_year=plan_year,
        monitor=current_user.role == ROLE_ADMIN,
    )


@publications_bp.route("/<int:publication_id>")
@roles_required(ROLE_ADMIN, ROLE_DEPARTMENT_HEAD)
def publication_detail(publication_id):
    publication = db.session.scalar(
        select(Publication).where(Publication.id == publication_id).options(*publication_detail_options())
    )

    if publication is None:
        abort(404)

    ensure_department_access(publication.department_id)

    doi_conflicts = find_doi_conflicts(publication) if current_user.role == ROLE_ADMIN else []

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
        comments=comments_for("PUBLICATION", publication.id),
        changes=db.session.scalars(
            select(AuditLog)
            .options(joinedload(AuditLog.user))
            .where(
                AuditLog.entity_type == "Publication",
                AuditLog.entity_id == publication.id,
                AuditLog.action == "PUBLICATION_UPDATED",
            )
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        ).all(),
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

    ensure_department_access(publication.department_id)

    indexing_types = get_reference_values("INDEXING_TYPE")
    quartiles = get_reference_values("QUARTILE")
    employees = db.session.scalars(
        select(Employee)
        .where(
            Employee.department_id == publication.department_id,
            (Employee.is_active.is_(True))
            | Employee.id.in_([link.employee_id for link in publication.author_links]),
        )
        .order_by(Employee.full_name)
    ).all()
    selected_author_ids = [link.employee_id for link in publication.author_links]

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
        for value, limit in (
            (title, 1000),
            (doi, 500),
            (url, 1000),
            (journal, 500),
            (volume, 100),
            (issue, 100),
            (pages, 100),
        ):
            if len(value) > limit:
                errors.append("Превышена допустимая длина поля.")
                break
        if url:
            try:
                parsed_url = urlsplit(url)
                if (
                    parsed_url.scheme not in {"http", "https"}
                    or not parsed_url.hostname
                    or parsed_url.username
                ):
                    raise ValueError
            except ValueError:
                errors.append("Ссылка должна начинаться с http:// или https:// и содержать адрес сайта.")
        if "authors_present" in request.form:
            try:
                selected_author_ids = list(
                    dict.fromkeys(int(value) for value in request.form.getlist("author_ids"))
                )
            except ValueError:
                errors.append("Выбран некорректный автор.")
            if not set(selected_author_ids) <= {employee.id for employee in employees}:
                errors.append("Нельзя выбрать сотрудника другой кафедры.")

        publication_year_value = None

        if publication_year:
            try:
                publication_year_value = int(publication_year)
            except ValueError:
                errors.append("Год публикации должен быть числом.")
            else:
                if not 1900 <= publication_year_value <= 2100:
                    errors.append("Введите корректный год публикации.")

        indexing_type = None

        if indexing_type_id:
            try:
                indexing_type_id_value = int(indexing_type_id)
            except ValueError:
                indexing_type_id_value = None
                errors.append("Выбран некорректный тип индексации.")

            if indexing_type_id_value is not None:
                indexing_type = db.session.scalar(
                    select(ReferenceValue).where(
                        ReferenceValue.id == indexing_type_id_value,
                        ReferenceValue.type == "INDEXING_TYPE",
                        ReferenceValue.is_active.is_(True),
                    )
                )

                if indexing_type is None:
                    errors.append("Выбран некорректный тип индексации.")

        quartile = None

        if quartile_id:
            try:
                quartile_id_value = int(quartile_id)
            except ValueError:
                quartile_id_value = None
                errors.append("Выбран некорректный квартиль.")

            if quartile_id_value is not None:
                quartile = db.session.scalar(
                    select(ReferenceValue).where(
                        ReferenceValue.id == quartile_id_value,
                        ReferenceValue.type == "QUARTILE",
                        ReferenceValue.is_active.is_(True),
                    )
                )

                if quartile is None:
                    errors.append("Выбран некорректный квартиль.")

        if errors:
            for error in errors:
                flash(error, "danger")

            return render_template(
                "publications/form.html",
                publication=publication,
                indexing_types=indexing_types,
                quartiles=quartiles,
                employees=employees,
                selected_author_ids=selected_author_ids,
            )

        before = publication_snapshot(publication)
        publication.title = title
        publication.doi = normalize_doi(doi)
        publication.url = url or None
        publication.journal = journal or None
        publication.publication_year = publication_year_value
        publication.volume = volume or None
        publication.issue = issue or None
        publication.pages = pages or None
        publication.indexing_type_id = indexing_type.id if indexing_type else None
        publication.quartile_id = quartile.id if quartile else None
        publication.affiliation = affiliation or None
        publication.notes = notes or None
        if selected_author_ids != [link.employee_id for link in publication.author_links]:
            publication.author_links.clear()
            db.session.flush()
            publication.author_links = [
                PublicationAuthor(employee_id=employee_id, author_order=order)
                for order, employee_id in enumerate(selected_author_ids, start=1)
            ]
        after = publication_snapshot(publication)
        if before != after:
            publication.verification_status = PUBLICATION_VERIFICATION_PENDING
            publication.verified_by = None
            publication.verified_at = None
            notify_participants(
                publication, "PUBLICATION", "Публикация изменена", publication.title, audience="monitor"
            )
        duplicates = find_publication_duplicates(publication)
        if duplicates:
            audit(
                "PUBLICATION_DUPLICATE_DETECTED",
                entity_type="Publication",
                entity_id=publication.id,
                details={"conflict_ids": [item.id for item in duplicates]},
            )
            flash("Обнаружена возможная дублирующая публикация. Монитор проверит совпадение.", "warning")

        audit(
            "PUBLICATION_UPDATED",
            entity_type="Publication",
            entity_id=publication.id,
            details={
                "before": before,
                "after": after,
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
        employees=employees,
        selected_author_ids=selected_author_ids,
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

    ensure_department_access(publication.department_id)

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
    if publication.verification_status == PUBLICATION_VERIFICATION_APPROVED:
        publication.verification_status = PUBLICATION_VERIFICATION_PENDING
        publication.verified_by = None
        publication.verified_at = None

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

    ensure_department_access(publication.department_id)

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

    original_filename = (uploaded_file.filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()

    if not original_filename or len(original_filename) > 500 or any(ord(c) < 32 for c in original_filename):
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

    with staged_upload(uploaded_file, original_filename) as (file_path, mime_type):
        attachment = Attachment(
            publication_id=publication.id,
            original_filename=original_filename,
            stored_filename=file_path.name,
            file_path=str(file_path),
            mime_type=mime_type,
            file_size=file_path.stat().st_size,
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

        if publication.verification_status != PUBLICATION_VERIFICATION_DUPLICATE:
            publication.verification_status = PUBLICATION_VERIFICATION_PENDING
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

    ensure_department_access(publication.department_id)

    attachment = db.session.get(Attachment, attachment_id)

    if attachment is None or attachment.publication_id != publication.id:
        abort(404)

    file_path = attachment_path(attachment)
    if not file_path.is_file():
        abort(404)

    return send_file(
        file_path,
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

    ensure_department_access(publication.department_id)

    attachment = db.session.get(
        Attachment,
        attachment_id,
    )

    if attachment is None or attachment.publication_id != publication.id:
        abort(404)

    if attachment.uploaded_by != current_user.id:
        abort(403)

    file_path = attachment_path(attachment)

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

    synchronize_publication_verification_status(publication)

    db.session.commit()
    delete_committed_file(file_path)

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

    if attachment is None or attachment.publication_id != publication.id:
        abort(404)

    if publication.verification_status == PUBLICATION_VERIFICATION_DUPLICATE:
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

    synchronize_publication_verification_status(publication)

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

    if attachment is None or attachment.publication_id != publication.id:
        abort(404)

    if publication.verification_status == PUBLICATION_VERIFICATION_DUPLICATE:
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

    synchronize_publication_verification_status(publication)

    db.session.add(
        Comment(
            user_id=current_user.id,
            entity_type="ATTACHMENT",
            entity_id=attachment.id,
            text=comment,
        )
    )

    notify_participants(
        publication,
        "PUBLICATION",
        "Файл отклонён.",
        attachment.review_comment or publication.title,
        audience="head",
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

    # Choosing a canonical record is not a bibliographic/affiliation/file review.
    winner.verification_status = PUBLICATION_VERIFICATION_PENDING
    winner.verified_by = None
    winner.verified_at = None

    loser.verification_status = PUBLICATION_VERIFICATION_DUPLICATE
    loser.verified_by = current_user.id
    loser.verified_at = datetime.utcnow()

    db.session.add(
        Comment(
            user_id=current_user.id,
            entity_type="PUBLICATION",
            entity_id=winner.id,
            text=(f"Монитор разрешил конфликт DOI. Выбрана публикация №{winner.id}."),
        )
    )

    db.session.add(
        Comment(
            user_id=current_user.id,
            entity_type="PUBLICATION",
            entity_id=loser.id,
            text=(f"Публикация признана дубликатом публикации №{winner.id} по результату проверки DOI."),
        )
    )

    notify_participants(winner, "PUBLICATION", "Конфликт DOI разрешён", winner.title, audience="head")
    notify_participants(
        loser, "PUBLICATION", "Публикация признана дубликатом", loser.title, "danger", audience="head"
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
        f"Конфликт DOI разрешён. Публикация №{winner.id} оставлена.",
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
    if publication.status != PUBLICATION_STATUS_PUBLISHED:
        errors.append("Подтвердить можно только опубликованную работу.")
    if publication.publication_year is None:
        errors.append("Укажите год публикации.")
    if publication.verification_status == PUBLICATION_VERIFICATION_DUPLICATE:
        errors.append("Сначала разрешите конфликт дубликатов.")

    if publication.plan_item is None:
        errors.append("Публикация не связана с пунктом плана.")
    else:
        plan = publication.plan_item.plan

        if plan is None:
            errors.append("Для публикации не найден план.")
        else:
            if plan.status != "APPROVED":
                errors.append("Связанный план не утверждён.")

            if publication.department_id != plan.department_id:
                errors.append("Кафедра публикации не соответствует кафедре плана.")

    if not publication.title.strip():
        errors.append("Не указано название публикации.")

    if not publication.journal or not publication.journal.strip():
        errors.append("Не указан журнал.")

    if not publication.author_links:
        errors.append("Не указаны авторы публикации.")

    if not publication.affiliation or not publication.affiliation.strip():
        errors.append("Не указана аффилиация.")

    duplicates = [
        item
        for item in find_publication_duplicates(publication)
        if item.verification_status != PUBLICATION_VERIFICATION_DUPLICATE
    ]

    if duplicates:
        conflict_ids = ", ".join(str(item.id) for item in duplicates)
        errors.append(
            "Обнаружены возможные дубликаты: публикации № "
            f"{conflict_ids}. Сначала необходимо разрешить конфликт монитором."
        )

    if not publication.attachments:
        errors.append("Не загружен подтверждающий файл.")
    else:
        not_approved_attachments = [
            attachment for attachment in publication.attachments if attachment.review_status != "APPROVED"
        ]

        if not_approved_attachments:
            errors.append("Необходимо дождаться проверки всех подтверждающих файлов.")

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

    publication.verification_status = PUBLICATION_VERIFICATION_APPROVED
    publication.verified_by = current_user.id
    publication.verified_at = datetime.utcnow()

    notify_participants(
        publication, "PUBLICATION", "Публикация подтверждена.", publication.title, "success", audience="head"
    )
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

    publication.verification_status = PUBLICATION_VERIFICATION_RETURNED
    publication.verified_by = current_user.id
    publication.verified_at = datetime.utcnow()

    add_comment(publication, "PUBLICATION", comment_text, "Публикация возвращена на доработку")

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
