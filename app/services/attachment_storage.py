"""Filesystem compensation around the database transaction for evidence files."""

from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from flask import abort, current_app

MIME_TYPES = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "zip": "application/zip",
    "rar": "application/vnd.rar",
}


def upload_root():
    return (Path(current_app.instance_path) / "uploads" / "publications").resolve()


def attachment_path(attachment):
    path = Path(attachment.file_path).resolve()
    if not path.is_relative_to(upload_root()):
        abort(404)
    return path


@contextmanager
def staged_upload(uploaded_file, original_filename):
    """A failed enclosing commit must not leave an orphaned newly uploaded file."""
    root = upload_root()
    root.mkdir(parents=True, exist_ok=True)
    extension = original_filename.rsplit(".", 1)[1].lower()
    path = root / f"{uuid4().hex}.{extension}"
    try:
        uploaded_file.save(path)
        yield path, MIME_TYPES[extension]
    except Exception:
        path.unlink(missing_ok=True)
        raise


def delete_committed_file(path):
    """Delete only after commit; a failed cleanup leaves recoverable orphan data."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        current_app.logger.warning("Attachment record deleted; file cleanup requires a retry.")
