import os
from pathlib import Path

_test_temp = Path(__file__).resolve().parents[1] / "instance" / "pytest-temp"
_test_temp.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("PYTEST_DEBUG_TEMPROOT", str(_test_temp))

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("SESSION_COOKIE_SECURE", "false")

from app import create_app
from app.extensions import db


@pytest.fixture
def app(tmp_path):
    application = create_app("testing", instance_path=str(tmp_path))

    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()
