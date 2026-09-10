from flask import Blueprint

admin_bp = Blueprint(
    "admin",
    __name__,
    url_prefix="/admin",
)

from app.admin import audit
from app.admin import references
from app.admin import system
