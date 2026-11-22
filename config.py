import os
from dotenv import load_dotenv

load_dotenv()
basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(basedir, "school.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(basedir, "static", "uploads", "pdfs")
    MAX_CONTENT_LENGTH = 25 * 1024 * 1024  # 25 MB uploads

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    AI_CALLS_PER_HOUR = 20

    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "headmaster")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "ChangeMe123!")

    DEFAULT_PIN = "1234"
    MAX_FAILED_LOGINS = 5
    LOCKOUT_MINUTES = 5