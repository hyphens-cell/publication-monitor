"""Comments and durable notifications share the enclosing business transaction."""

import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage

import click
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func, or_, select

from app.access import ensure_department_access
from app.audit import audit
from app.auth import roles_required
from app.extensions import db
from app.models import Comment, Notification, Plan, Publication, User

discussion_bp = Blueprint("discussion", __name__)
ENTITY_MODELS = {"PLAN": Plan, "PUBLICATION": Publication}


def entity_url(entity_type, entity_id):
    if entity_type == "PLAN":
        return url_for("plans.plan_detail", plan_id=entity_id)
    return url_for("publications.publication_detail", publication_id=entity_id)


def comments_for(entity_type, entity_id):
    return db.session.scalars(
        select(Comment)
        .where(Comment.entity_type == entity_type, Comment.entity_id == entity_id)
        .order_by(Comment.created_at, Comment.id)
    ).all()


def notify_participants(entity, entity_type, title, message, severity="warning", audience=None):
    """Queue in-app/email notices; never contact SMTP in a web transaction."""
    query = select(User).where(User.is_active.is_(True))
    heads = (User.role == "DEPARTMENT_HEAD") & (User.department_id == entity.department_id)
    monitors = User.role == "ADMIN"
    query = query.where(
        heads if audience == "head" else monitors if audience == "monitor" else or_(heads, monitors)
    )
    if current_user.is_authenticated:
        query = query.where(User.id != current_user.id)
    for user in db.session.scalars(query):
        db.session.add(
            Notification(
                user_id=user.id,
                type=severity,
                title=title,
                message=message,
                entity_type=entity_type,
                entity_id=entity.id,
            )
        )


def add_comment(entity, entity_type, text, title="Новый комментарий"):
    comment = Comment(user_id=current_user.id, entity_type=entity_type, entity_id=entity.id, text=text)
    db.session.add(comment)
    notify_participants(entity, entity_type, title, text)
    return comment


@discussion_bp.post("/comments/<entity_type>/<int:entity_id>")
@roles_required("ADMIN", "DEPARTMENT_HEAD")
def create_comment(entity_type, entity_id):
    model = ENTITY_MODELS.get(entity_type)
    if model is None:
        abort(404)
    entity = db.session.get(model, entity_id)
    if entity is None:
        abort(404)
    ensure_department_access(entity.department_id)
    text = request.form.get("text", "").strip()
    if not text or len(text) > 5000:
        flash("Введите комментарий длиной от 1 до 5000 символов.", "danger")
    else:
        add_comment(entity, entity_type, text)
        audit("COMMENT_ADDED", entity_type=entity_type, entity_id=entity_id, details={"text": text})
        db.session.commit()
        flash("Комментарий добавлен.", "success")
    return redirect(entity_url(entity_type, entity_id))


def accessible_notifications():
    # Reassignment of a department must not expose previous department notices.
    query = select(Notification).where(Notification.user_id == current_user.id)
    if current_user.role == "DEPARTMENT_HEAD":
        query = query.where(
            or_(
                (Notification.entity_type == "PLAN")
                & Notification.entity_id.in_(
                    select(Plan.id).where(Plan.department_id == current_user.department_id)
                ),
                (Notification.entity_type == "PUBLICATION")
                & Notification.entity_id.in_(
                    select(Publication.id).where(Publication.department_id == current_user.department_id)
                ),
            )
        )
    return query


@discussion_bp.app_context_processor
def notification_context():
    count = 0
    if (
        not g.get("error_response")
        and current_user.is_authenticated
        and current_user.role in {"ADMIN", "DEPARTMENT_HEAD"}
    ):
        count = (
            db.session.scalar(
                select(func.count()).select_from(
                    accessible_notifications().where(Notification.is_read.is_(False)).subquery()
                )
            )
            or 0
        )
    return {"unread_notification_count": count, "notification_url": entity_url}


@discussion_bp.get("/notifications")
@roles_required("ADMIN", "DEPARTMENT_HEAD")
def notifications():
    page = request.args.get("page", 1, type=int)
    if page < 1:
        abort(400)
    pagination = db.paginate(
        accessible_notifications().order_by(Notification.created_at.desc(), Notification.id.desc()),
        page=page,
        per_page=30,
        error_out=False,
    )
    return render_template("notifications/list.html", pagination=pagination)


@discussion_bp.post("/notifications/<int:notification_id>/read")
@roles_required("ADMIN", "DEPARTMENT_HEAD")
def read_notification(notification_id):
    notification = db.session.scalar(accessible_notifications().where(Notification.id == notification_id))
    if notification is None:
        abort(404)
    notification.is_read = True
    notification.read_at = datetime.utcnow()
    db.session.commit()
    return redirect(entity_url(notification.entity_type, notification.entity_id))


def deliver_notification(notification):
    config = current_app.config
    message = EmailMessage()
    message["From"] = config["MAIL_DEFAULT_SENDER"]
    message["To"] = notification.user.email
    message["Subject"] = "Publication Monitor: " + notification.title.replace("\r", " ").replace("\n", " ")
    message.set_content(
        notification.message
        + "\n\n"
        + config.get("APPLICATION_URL", "").rstrip("/")
        + (
            f"/plans/{notification.entity_id}"
            if notification.entity_type == "PLAN"
            else f"/publications/{notification.entity_id}"
        )
    )
    with smtplib.SMTP(config["MAIL_SERVER"], config["MAIL_PORT"], timeout=15) as smtp:
        if config["MAIL_USE_TLS"]:
            smtp.starttls(context=ssl.create_default_context())
        if config.get("MAIL_USERNAME"):
            smtp.login(config["MAIL_USERNAME"], config["MAIL_PASSWORD"])
        smtp.send_message(message)


@discussion_bp.cli.command("send-notifications")
@click.option("--limit", default=100, type=click.IntRange(1, 1000))
def send_notifications(limit):
    """Deliver queued messages. Configure SMTP before explicitly running this command."""
    if not current_app.config.get("MAIL_SERVER") or not current_app.config.get("MAIL_DEFAULT_SENDER"):
        raise click.ClickException("Configure MAIL_SERVER and MAIL_DEFAULT_SENDER first.")
    ids = db.session.scalars(
        select(Notification.id)
        .join(Notification.user)
        .where(
            Notification.email_sent.is_(False),
            User.is_active.is_(True),
            User.role.in_(["ADMIN", "DEPARTMENT_HEAD"]),
        )
        .order_by(Notification.id)
        .limit(limit)
    ).all()
    sent = failed = 0
    for notification_id in ids:
        # PostgreSQL row locks prevent concurrent senders from sending the same queued notice.
        notice = db.session.scalar(
            select(Notification)
            .where(Notification.id == notification_id, Notification.email_sent.is_(False))
            .with_for_update(skip_locked=True)
        )
        if notice is None:
            db.session.rollback()
            continue
        entity = db.session.get(ENTITY_MODELS.get(notice.entity_type, Plan), notice.entity_id)
        if entity is None or (
            notice.user.role == "DEPARTMENT_HEAD" and notice.user.department_id != entity.department_id
        ):
            db.session.rollback()
            continue
        try:
            deliver_notification(notice)
        except (OSError, smtplib.SMTPException):
            db.session.rollback()
            failed += 1
            continue
        notice.email_sent = True
        db.session.commit()
        sent += 1
    click.echo(f"Sent: {sent}; failed: {failed}")
    if failed:
        raise click.ClickException("Some messages remain queued; check SMTP settings and retry.")
