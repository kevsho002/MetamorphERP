"""Configuración Django de Metamorph ERP (12-factor: variables de entorno o backend/.env).

Monolito modular:
- Tablas de dominio (core/hcm/wfm/fin): SQL-first en database/scripts, mapeadas
  con modelos `managed = False`.
- Tablas del framework y de seguridad (auth, sesiones, accounts_customuser):
  administradas por migraciones de Django en el esquema dbo.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
load_dotenv(BASE_DIR / ".env")


def env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


# ------------------------------------------------------------------ aplicación
APP_NAME = "Metamorph ERP"
APP_ENV = env("APP_ENV", "development")  # development | test | production
IS_PRODUCTION = APP_ENV == "production"
DEBUG = env_bool("DJANGO_DEBUG", not IS_PRODUCTION)

SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if IS_PRODUCTION:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY es obligatoria en producción")
    SECRET_KEY = "dev-insecure-metamorph-erp-change-me"  # solo desarrollo/test

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "rest_framework",
    # Módulos del ERP
    "apps.common",
    "apps.hcm",
    "apps.payroll",
    "apps.holidays",  # Fase 21: calendario de feriados y Holiday Segments
    "apps.accounts",
    "apps.employees",
    "apps.system",
    "apps.roster",
    "apps.operations",
    "apps.general_ids",
    "apps.scheduling",
    "apps.personnel_actions",
    "apps.acd",
    "apps.adherence",
    "apps.health",
    "apps.web",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.system.middleware.SessionPolicyMiddleware",  # inactividad, duración máxima, mantenimiento
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],  # Fase 23: admin/base_site.html con la paleta y los logos del ERP
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.system.theme.admin_theme",
            ],
        },
    },
]

# ------------------------------------------------------------------ SQL Server
_db_extra = [
    f"Encrypt={'yes' if env_bool('DB_ENCRYPT', True) else 'no'}",
    f"TrustServerCertificate={'yes' if env_bool('DB_TRUST_SERVER_CERTIFICATE', not IS_PRODUCTION) else 'no'}",
    f"APP={APP_NAME}",
]
_db_trusted = env_bool("DB_TRUSTED_CONNECTION", True)

DATABASES = {
    "default": {
        "ENGINE": "mssql",
        "NAME": env("DB_NAME", "MetamorphERP"),
        "HOST": env("DB_SERVER", "localhost"),
        "PORT": env("DB_PORT", ""),
        # Sin USER => autenticación integrada de Windows
        "USER": "" if _db_trusted else env("DB_USER", ""),
        "PASSWORD": "" if _db_trusted else env("DB_PASSWORD", ""),
        "ATOMIC_REQUESTS": True,  # cada request = una transacción (ACID)
        "CONN_MAX_AGE": int(env("DB_CONN_MAX_AGE", "60")),
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {
            "driver": env("DB_DRIVER", "ODBC Driver 18 for SQL Server"),
            "extra_params": ";".join(_db_extra),
        },
        "TEST": {"NAME": env("DB_TEST_NAME", "test_MetamorphERP")},
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ------------------------------------------------------------------ seguridad
AUTH_USER_MODEL = "accounts.CustomUser"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Sesión en cookie HttpOnly + CSRF (mismo origen: el backend sirve el build de React)
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_NAME = "metamorph_sessionid"
SESSION_COOKIE_AGE = int(env("SESSION_COOKIE_AGE", str(8 * 60 * 60)))  # jornada laboral
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_NAME = "metamorph_csrftoken"
CSRF_COOKIE_HTTPONLY = False  # el SPA lo lee y lo envía en X-CSRFToken
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_FAILURE_VIEW = "apps.web.views.csrf_failure"
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = IS_PRODUCTION

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
if IS_PRODUCTION:
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SECURE_HSTS_SECONDS = int(env("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.accounts.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
        "apps.accounts.permissions.PasswordChangeNotRequired",
    ],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"]
    + (["rest_framework.renderers.BrowsableAPIRenderer"] if DEBUG else []),
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_THROTTLE_RATES": {"login": env("LOGIN_THROTTLE_RATE", "10/min")},
    "UNAUTHENTICATED_USER": "django.contrib.auth.models.AnonymousUser",
}

# Cargas masivas: el archivo se valida en apps/employees/parsers.py (máx. 5 MB / 5000 filas).
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024  # cuerpo JSON con "rows"

# Expediente digital (Fase 5): imágenes PNG/JPG/JPEG fuera de cualquier ruta pública.
# Solo se entregan por la API, tras verificar sesión y permisos (nunca por WhiteNoise ni /media/).
PRIVATE_MEDIA_ROOT = (BASE_DIR / env("PRIVATE_MEDIA_ROOT", "private_media")).resolve()
DOCUMENT_MAX_PIXELS = int(env("DOCUMENT_MAX_PIXELS", str(40_000_000)))  # protección contra "bombas" de descompresión
PROFILE_PHOTO_MAX_SIDE = 800  # la foto de perfil se normaliza (sin metadatos EXIF/GPS) a este tamaño máximo

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# ------------------------------------------------------------------ i18n
LANGUAGE_CODE = "es"
TIME_ZONE = "America/El_Salvador"
USE_I18N = True
USE_TZ = True  # la BD guarda UTC (SYSUTCDATETIME)

# ------------------------------------------------------------------ estáticos / SPA
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
FRONTEND_DIST_DIR = (BASE_DIR / env("FRONTEND_DIST_DIR", "../frontend/dist")).resolve()
# WhiteNoise sirve /assets/*, favicon, etc. del build de React en la raíz
WHITENOISE_ROOT = FRONTEND_DIST_DIR if FRONTEND_DIST_DIR.is_dir() else None
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "apps.accounts": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
        "apps.employees": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
        "apps.system": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
        "apps.roster": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
        "apps.general_ids": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
        "apps.scheduling": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
        "apps.personnel_actions": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
        "apps.acd": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    },
}

# ------------------------------------------------------------------ horarios y tiempo (Fase 10)
# La carga MANUAL de registros de tiempo (formulario y archivo) está retirada temporalmente por el riesgo de
# manipulación: los endpoints de escritura responden 403. Los registros existentes se siguen consultando y la
# base (sch_time_record, origen WEB_TIMER) queda lista para el futuro Web Timer interno.
SCHEDULING_MANUAL_TIME_ENTRY = env_bool("SCHEDULING_MANUAL_TIME_ENTRY", False)
