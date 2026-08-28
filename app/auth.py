from functools import wraps

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import (
    current_user,
    login_required,
    login_user,
    logout_user,
)
from sqlalchemy import select

from app.extensions import db
from app.models import User


auth_bp = Blueprint(
    "auth",
    __name__,
    url_prefix="/auth",
)


ROLE_TECH_ADMIN = "TECH_ADMIN"
ROLE_ADMIN = "ADMIN"
ROLE_DEPARTMENT_HEAD = "DEPARTMENT_HEAD"


VALID_ROLES = {
    ROLE_TECH_ADMIN,
    ROLE_ADMIN,
    ROLE_DEPARTMENT_HEAD,
}


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(
            url_for("main.index")
        )

    if request.method == "POST":
        username = request.form.get(
            "username",
            "",
        ).strip()

        password = request.form.get(
            "password",
            "",
        )

        if not username or not password:
            flash(
                "Введите логин и пароль.",
                "warning",
            )

            return render_template(
                "auth/login.html"
            )

        user = db.session.scalar(
            select(User).where(
                User.username == username
            )
        )

        if user is None or not user.is_active:
            flash(
                "Неверный логин или пароль.",
                "danger",
            )

            return render_template(
                "auth/login.html"
            )

        if not user.check_password(password):
            flash(
                "Неверный логин или пароль.",
                "danger",
            )

            return render_template(
                "auth/login.html"
            )

        login_user(user)

        next_url = request.args.get("next")

        if (
            next_url
            and next_url.startswith("/")
            and not next_url.startswith("//")
        ):
            return redirect(next_url)

        return redirect(
            url_for("main.index")
        )

    return render_template(
        "auth/login.html"
    )


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()

    flash(
        "Вы вышли из системы.",
        "success",
    )

    return redirect(
        url_for("auth.login")
    )


def roles_required(*roles):
    allowed_roles = set(roles)

    unknown_roles = (
        allowed_roles - VALID_ROLES
    )

    if unknown_roles:
        raise ValueError(
            "Неизвестные роли: "
            + ", ".join(sorted(unknown_roles))
        )

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped_view(*args, **kwargs):
            if current_user.role not in allowed_roles:
                flash(
                    "У вас нет доступа к этому разделу.",
                    "danger",
                )

                return redirect(
                    url_for("main.index")
                )

            return view(
                *args,
                **kwargs,
            )

        return wrapped_view

    return decorator


def technical_admin_required(view):
    return roles_required(
        ROLE_TECH_ADMIN,
    )(view)


def admin_required(view):
    return roles_required(
        ROLE_ADMIN,
    )(view)


def department_head_required(view):
    return roles_required(
        ROLE_DEPARTMENT_HEAD,
    )(view)


def admin_or_department_head_required(view):
    return roles_required(
        ROLE_ADMIN,
        ROLE_DEPARTMENT_HEAD,
    )(view)