"""Django settings for Sizzle Sense.

Configured through environment variables so the same code runs locally and in
production (Render / Railway / Fly / a VPS):

    DJANGO_SECRET_KEY         secret key (REQUIRED when DJANGO_DEBUG=0)
    DJANGO_DEBUG              "1" (default) or "0"
    DJANGO_ALLOWED_HOSTS      comma separated, default "*"
    DJANGO_CSRF_TRUSTED       comma separated origins, e.g. https://sizzle.onrender.com
    DATABASE_URL              optional postgres://user:pass@host:5432/dbname (default: SQLite file)
    DJANGO_DB_PATH            optional path of the SQLite file (default: ./db.sqlite3)
    DJANGO_REQUIRE_APPROVAL   "1" (default) = new sign-ups stay inactive until an admin approves them
    DJANGO_ALLOW_SIGNUP       "1" (default) lets anyone register; "0" = admin-created accounts only
    MAX_COOKERS_PER_USER      how many cookers one account may own (default 5)
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_list(name, default=""):
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-insecure-key-change-me"
    else:
        raise RuntimeError("Set DJANGO_SECRET_KEY when DJANGO_DEBUG=0")

ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS", "*")
CSRF_TRUSTED_ORIGINS = _env_list("DJANGO_CSRF_TRUSTED")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "cooker",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "sizzle_project.urls"
WSGI_APPLICATION = "sizzle_project.wsgi.application"
ASGI_APPLICATION = "sizzle_project.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": [
            "django.template.context_processors.request",
            "django.contrib.auth.context_processors.auth",
            "django.contrib.messages.context_processors.messages",
        ]},
    }
]

def _database():
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith(("postgres://", "postgresql://")):
        from urllib.parse import unquote, urlparse

        u = urlparse(url)
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": u.path.lstrip("/"),
            "USER": unquote(u.username or ""),
            "PASSWORD": unquote(u.password or ""),
            "HOST": u.hostname or "",
            "PORT": u.port or "",
            "CONN_MAX_AGE": 60,
        }
    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DJANGO_DB_PATH", str(BASE_DIR / "db.sqlite3")),
        "OPTIONS": {"timeout": 20},
    }


DATABASES = {"default": _database()}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"
ALLOW_SIGNUP = os.environ.get("DJANGO_ALLOW_SIGNUP", "1") == "1"   # "0" = only admins create accounts
REQUIRE_APPROVAL = os.environ.get("DJANGO_REQUIRE_APPROVAL", "1") == "1"   # new sign-ups wait for an admin
MAX_COOKERS_PER_USER = int(os.environ.get("MAX_COOKERS_PER_USER", "5"))

# Cookies only travel over HTTPS in production.
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Behind a proxy (Render, Railway, ...) trust the forwarded scheme.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
