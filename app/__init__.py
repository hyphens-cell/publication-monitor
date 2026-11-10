from hmac import compare_digest
from pathlib import Path

from flask import Flask, session

from app.admin import admin_bp
from app.analytics import analytics_bp
from app.auth import auth_bp
from app.config import configure_app
from app.discussion import discussion_bp
from app.employees import employees_bp
from app.errors import register_error_handlers
from app.extensions import bcrypt, csrf, db, limiter, login_manager, migrate
from app.i18n import (
    ATTACHMENT_STATUS_LABELS,
    PLAN_STATUS_LABELS,
    PUBLICATION_STATUS_LABELS,
    ROLE_LABELS,
    VERIFICATION_STATUS_LABELS,
    TemplateTranslationExtension,
    audit_action_label,
    current_language,
    format_file_size,
    localized_label,
    translate,
)
from app.main import main_bp
from app.models import User
from app.monitoring import monitoring_bp
from app.plans import plans_bp
from app.publications import publications_bp
from app.reports import reports_bp
from app.security import password_stamp, register_security_headers
from app.seed_reference_values import seed_reference_values


def create_app(config=None, *, instance_path=None):
    app = Flask(__name__, instance_path=instance_path)
    configure_app(app, config)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    bcrypt.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    register_security_headers(app)
    register_error_handlers(app)
    app.jinja_env.add_extension(TemplateTranslationExtension)
    app.jinja_env.globals.update(
        audit_action_label=audit_action_label,
        tr=translate,
        current_language=current_language,
        filesize=format_file_size,
        role_label=lambda code: localized_label(ROLE_LABELS, code),
        plan_status_label=lambda code: localized_label(PLAN_STATUS_LABELS, code),
        publication_status_label=lambda code: localized_label(PUBLICATION_STATUS_LABELS, code),
        verification_status_label=lambda code: localized_label(VERIFICATION_STATUS_LABELS, code),
        attachment_status_label=lambda code: localized_label(ATTACHMENT_STATUS_LABELS, code),
    )

    login_manager.login_view = "auth.login"
    login_manager.login_message = "Для доступа необходимо войти в систему."
    login_manager.login_message_category = "warning"

    @login_manager.user_loader
    def load_user(user_id):
        try:
            user = db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None
        if user is None or not user.is_active:
            return None
        stamp = session.get("auth_stamp")
        if stamp is not None and (
            not isinstance(stamp, str) or not compare_digest(stamp, password_stamp(user))
        ):
            return None
        return user

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(employees_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(publications_bp)
    app.register_blueprint(monitoring_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(discussion_bp)

    @app.cli.command("seed-reference-values")
    def seed_reference_values_command():
        created_count = seed_reference_values()

        print(f"Создано справочных значений: {created_count}")

    return app
