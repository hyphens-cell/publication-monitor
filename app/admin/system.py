import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from flask import abort, current_app, jsonify, render_template, send_file
from sqlalchemy import func, select, text

from app.admin import admin_bp
from app.audit import audit
from app.auth import technical_admin_required
from app.extensions import db
from app.models import AuditLog, Department, Employee, Plan, Publication, User


def _database_host():
    url = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if "@" not in url:
        return None
    return url.rsplit("@", 1)[1]


def _backup_directory() -> Path:
    directory = Path(current_app.instance_path, "backups")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _backup_path(filename: str) -> Path:
    if not filename or Path(filename).name != filename or not filename.endswith(".dump"):
        abort(404)

    path = _backup_directory() / filename
    if not path.is_file():
        abort(404)
    return path


@admin_bp.route("/system", methods=["GET"])
@technical_admin_required
def system_dashboard():
    return render_template("admin/system.html")


@admin_bp.route("/system/status", methods=["GET"])
@technical_admin_required
def system_status():
    database_ok = False
    database_error = None

    try:
        db.session.execute(text("SELECT 1"))
        database_ok = True
    except Exception as exc:
        db.session.rollback()
        database_error = str(exc)

    upload_root = Path(
        current_app.instance_path,
        "uploads",
    )

    if upload_root.exists():
        upload_size = sum(
            path.stat().st_size
            for path in upload_root.rglob("*")
            if path.is_file()
        )
    else:
        upload_size = 0

    disk = shutil.disk_usage(current_app.instance_path)

    result = {
        "application": "publication-monitor",
        "database": {
            "ok": database_ok,
            "host": _database_host(),
            "error": database_error,
        },
        "server_time": datetime.utcnow().isoformat(),
        "instance_path": current_app.instance_path,
        "uploads": {
            "path": str(upload_root),
            "bytes": upload_size,
        },
        "disk": {
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
        },
        "counts": {
            "users": db.session.scalar(
                select(func.count()).select_from(User)
            ),
            "active_users": db.session.scalar(
                select(func.count()).select_from(User).where(User.is_active.is_(True))
            ),
            "departments": db.session.scalar(
                select(func.count()).select_from(Department)
            ),
            "active_departments": db.session.scalar(
                select(func.count()).select_from(Department).where(Department.is_active.is_(True))
            ),
            "employees": db.session.scalar(
                select(func.count()).select_from(Employee)
            ),
            "plans": db.session.scalar(
                select(func.count()).select_from(Plan)
            ),
            "publications": db.session.scalar(
                select(func.count()).select_from(Publication)
            ),
            "audit_logs": db.session.scalar(
                select(func.count()).select_from(AuditLog)
            ),
        },
    }

    return jsonify(result)


@admin_bp.route("/system/backup", methods=["POST"])
@technical_admin_required
def create_backup():
    database_url = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")

    if not database_url.startswith("postgresql"):
        return jsonify(
            {
                "error": "Резервное копирование поддерживает только PostgreSQL."
            }
        ), 500

    backup_directory = _backup_directory()

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_directory / f"publication_monitor_{timestamp}.dump"

    command = [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--file",
        str(backup_path),
        database_url,
    ]

    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except FileNotFoundError:
        if backup_path.exists():
            backup_path.unlink()
        return jsonify(
            {"error": "pg_dump не найден в PATH сервера."}
        ), 500
    except subprocess.TimeoutExpired:
        if backup_path.exists():
            backup_path.unlink()
        return jsonify(
            {"error": "Создание резервной копии превысило лимит времени."}
        ), 504

    if completed.returncode != 0:
        if backup_path.exists():
            backup_path.unlink()

        return jsonify(
            {
                "error": "pg_dump завершился с ошибкой.",
                "details": completed.stderr[-2000:],
            }
        ), 500

    audit(
        "SYSTEM_BACKUP_CREATED",
        entity_type="System",
        entity_id=None,
        details={
            "filename": backup_path.name,
            "size": backup_path.stat().st_size,
        },
    )
    db.session.commit()

    return send_file(
        backup_path,
        as_attachment=True,
        download_name=backup_path.name,
        mimetype="application/octet-stream",
    )


@admin_bp.route("/system/backups", methods=["GET"])
@technical_admin_required
def list_backups():
    files = []
    for path in sorted(_backup_directory().glob("*.dump"), key=lambda item: item.stat().st_mtime, reverse=True):
        stat = path.stat()
        files.append({
            "filename": path.name,
            "size": stat.st_size,
            "created_at": datetime.utcfromtimestamp(stat.st_mtime).isoformat(),
        })
    return jsonify({"items": files})


@admin_bp.route("/system/backups/<filename>", methods=["GET"])
@technical_admin_required
def download_backup(filename):
    path = _backup_path(filename)
    audit("SYSTEM_BACKUP_DOWNLOADED", entity_type="SystemBackup", details={"filename": path.name})
    db.session.commit()
    return send_file(path, as_attachment=True, download_name=path.name, mimetype="application/octet-stream")
