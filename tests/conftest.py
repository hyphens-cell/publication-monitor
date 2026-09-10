import os

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("SESSION_COOKIE_SECURE", "false")

from app import create_app
from app.extensions import db


@pytest.fixture
def app():
    application = create_app()
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()
