from importlib import import_module

from flask import Blueprint

admin_bp = Blueprint(
    "admin",
    __name__,
    url_prefix="/admin",
)

# Register routes once after the shared blueprint exists.
for _module in ("users", "departments", "audit", "references", "system"):
    import_module(f"app.admin.{_module}")
