from flask import Flask

from app.admin import admin_bp
from app.auth import auth_bp
from app.config import Config
from app.extensions import bcrypt, csrf, db, login_manager, migrate
from app.main import main_bp
from app.models import User

import app.admin.users
import app.admin.departments
from app.employees import employees_bp
from app.plans import plans_bp
from app.publications import publications_bp
from app.seed_reference_values import seed_reference_values


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    bcrypt.init_app(app)
    csrf.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message = "Для доступа необходимо войти в систему."
    login_manager.login_message_category = "warning"

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(employees_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(publications_bp)
    @app.cli.command("seed-reference-values")
    def seed_reference_values_command():
        created_count = seed_reference_values()

        print(
            f"Создано справочных значений: {created_count}"
        )

    return app