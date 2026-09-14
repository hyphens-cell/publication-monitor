from flask import Blueprint, render_template
from flask_login import current_user, login_required
from sqlalchemy import func, select

from app.extensions import db
from app.models import Department, Plan, Publication, User

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
@login_required
def index():
    metrics = {}
    if current_user.role == "TECH_ADMIN":
        metrics = {
            "users": db.session.scalar(select(func.count()).select_from(User)) or 0,
            "active_users": db.session.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True))) or 0,
            "departments": db.session.scalar(select(func.count()).select_from(Department).where(Department.is_active.is_(True))) or 0,
        }
    elif current_user.role == "ADMIN":
        metrics = {
            "submitted_plans": db.session.scalar(select(func.count()).select_from(Plan).where(Plan.status == "SUBMITTED")) or 0,
            "pending_publications": db.session.scalar(select(func.count()).select_from(Publication).where(Publication.verification_status == "PENDING")) or 0,
            "published_publications": db.session.scalar(select(func.count()).select_from(Publication).where(Publication.status == "PUBLISHED")) or 0,
        }
    elif current_user.role == "DEPARTMENT_HEAD" and current_user.department_id:
        metrics = {
            "plans": db.session.scalar(select(func.count()).select_from(Plan).where(Plan.department_id == current_user.department_id)) or 0,
            "publications": db.session.scalar(select(func.count()).select_from(Publication).where(Publication.department_id == current_user.department_id)) or 0,
            "published_publications": db.session.scalar(select(func.count()).select_from(Publication).where(Publication.department_id == current_user.department_id, Publication.status == "PUBLISHED")) or 0,
        }
    return render_template("auth/dashboard.html", metrics=metrics)
