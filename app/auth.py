from functools import wraps

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
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
from app.audit import audit
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

        # Drop any anonymous session state before issuing the authenticated session.
        session.clear()
        session.permanent = True
        login_user(user)
        audit("USER_LOGGED_IN", entity_type="User", entity_id=user.id, details={"username": user.username})
        db.session.commit()

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
    audit("USER_LOGGED_OUT", entity_type="User", entity_id=current_user.id)
    db.session.commit()
    logout_user()
    session.clear()

    flash(
        "Вы вышли из системы.",
        "success",
    )

    return redirect(
        url_for("auth.login")
    )


@auth_bp.route("/language", methods=["POST"])
@login_required
def change_language():
    language = request.form.get("language", "").strip()
    next_url = request.form.get("next", "").strip()

    if language not in {"ru", "kk"}:
        flash("Выбран некорректный язык.", "danger")
    else:
        current_user.language = language
        db.session.commit()

    if next_url.startswith("/") and not next_url.startswith("//"):
        return redirect(next_url)
    return redirect(url_for("main.index"))


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
