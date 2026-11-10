"""Resolve configuration at factory time, never at module import time."""

import os

from dotenv import load_dotenv
from sqlalchemy.engine import URL


class Config:
    DEBUG = False
    TESTING = False
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    BABEL_DEFAULT_LOCALE = "ru"
    BABEL_TRANSLATION_DIRECTORIES = "translations"
    MAX_FORM_MEMORY_SIZE = 500_000
    MAX_FORM_PARTS = 200
    RATELIMIT_STORAGE_URI = "memory://"
    RATELIMIT_HEADERS_ENABLED = True
    LOGIN_RATE_LIMIT = "10 per minute; 100 per hour"


class DevelopmentConfig(Config):
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False


class TestingConfig(DevelopmentConfig):
    TESTING = True
    SECRET_KEY = "test-only-secret-not-for-deployment"
    SQLALCHEMY_DATABASE_URI = "sqlite+pysqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class ProductionConfig(Config):
    pass


CONFIGS = {"development": DevelopmentConfig, "testing": TestingConfig, "production": ProductionConfig}


def configure_app(app, config=None):
    """Testing never inherits a real database from the developer's environment."""
    load_dotenv()
    profile = config if isinstance(config, str) else os.getenv("APP_ENV", "development")
    if profile not in CONFIGS:
        raise ValueError("APP_ENV must be development, testing or production.")
    app.config.from_object(CONFIGS[profile])
    app.config["APP_ENV"] = profile
    if profile != "testing":
        app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
        app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL") or URL.create(
            "postgresql+psycopg",
            username=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            database=os.getenv("DB_NAME"),
        )
        app.config["SESSION_COOKIE_SECURE"] = (
            os.getenv("SESSION_COOKIE_SECURE", str(app.config["SESSION_COOKIE_SECURE"])).lower() == "true"
        )
        app.config["REMEMBER_COOKIE_SECURE"] = app.config["SESSION_COOKIE_SECURE"]
        app.config["RATELIMIT_STORAGE_URI"] = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
        app.config["LOGIN_RATE_LIMIT"] = os.getenv("LOGIN_RATE_LIMIT", Config.LOGIN_RATE_LIMIT)
    app.config.update(
        PERMANENT_SESSION_LIFETIME=int(os.getenv("SESSION_LIFETIME_SECONDS", "28800")),
        MAX_CONTENT_LENGTH=int(os.getenv("MAX_UPLOAD_BYTES", str(20 * 1024 * 1024))),
        MAIL_SERVER=os.getenv("MAIL_SERVER", ""),
        MAIL_PORT=int(os.getenv("MAIL_PORT", "587")),
        MAIL_USE_TLS=os.getenv("MAIL_USE_TLS", "true").lower() == "true",
        MAIL_USERNAME=os.getenv("MAIL_USERNAME", ""),
        MAIL_PASSWORD=os.getenv("MAIL_PASSWORD", ""),
        MAIL_DEFAULT_SENDER=os.getenv("MAIL_DEFAULT_SENDER", ""),
        APPLICATION_URL=os.getenv("APPLICATION_URL", ""),
        TRUSTED_HOSTS=[v.strip() for v in os.getenv("TRUSTED_HOSTS", "").split(",") if v.strip()] or None,
    )
    if isinstance(config, dict):
        app.config.update(config)
    elif config is not None and not isinstance(config, str):
        app.config.from_object(config)
    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY must be set in the environment.")
    if profile == "production":
        secret = app.config["SECRET_KEY"]
        if len(secret) < 32 or str(secret).startswith("replace-with"):
            raise RuntimeError("Production requires a random SECRET_KEY of at least 32 characters.")
        if not app.config["SESSION_COOKIE_SECURE"]:
            raise RuntimeError("Production requires HTTPS and SESSION_COOKIE_SECURE=true.")
        app.config["DEBUG"] = False
