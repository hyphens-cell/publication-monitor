import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY")
    if not SECRET_KEY:
        raise RuntimeError("SECRET_KEY must be set in the environment.")

    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL") or (
        f"postgresql+psycopg://"
        f"{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST', 'localhost')}:"
        f"{os.getenv('DB_PORT', '5432')}/"
        f"{os.getenv('DB_NAME')}"
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "true").lower() == "true"
    PERMANENT_SESSION_LIFETIME = int(os.getenv("SESSION_LIFETIME_SECONDS", "28800"))
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
