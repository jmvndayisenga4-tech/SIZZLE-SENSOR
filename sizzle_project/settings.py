"""Django settings for Sizzle Sense.

Configured through environment variables so the same code runs locally and in
production (Render / Railway / Fly / a VPS):

    DJANGO_SECRET_KEY         secret key (REQUIRED when DJANGO_DEBUG=0)
    DJANGO_DEBUG              "1" (default) or "0"
    DJANGO_ALLOWED_HOSTS      comma separated, default "*"
    DJANGO_CSRF_TRUSTED       comma separated origins, e.g. https://sizzle.onrender.com
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
    "django.contrib.staticfiles",
    "cooker",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "sizzle_project.urls"
WSGI_APPLICATION = "sizzle_project.wsgi.application"
ASGI_APPLICATION = "sizzle_project.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    }
]

# The simulator keeps its state in memory, so no database is needed.
DATABASES = {}

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
