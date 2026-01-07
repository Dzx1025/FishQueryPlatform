import os
from pathlib import Path
from datetime import timedelta

# Build paths inside the project like this: BASE_DIR / "subdir".
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("No SECRET_KEY set in environment variables")

# Session settings for anonymous users
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30  # 30 days in seconds

# Django-ratelimit settings
RATELIMIT_USE_CACHE = "default"
RATELIMIT_VIEW = "chats.utils.ratelimited_error"

AUTH_USER_MODEL = "core.CustomUser"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
]

ALLOWED_HOSTS = [
    "localhost",
    "127.0.0.1",
    "django",
    "django.fishquery.dzx1025.com",
    "fishquery.dzx1025.com",
]

# Application definition
INSTALLED_APPS = [
    "core",  # Custom user model
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Dependencies
    "rest_framework",
    "rest_framework.authtoken",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "drf_yasg",
    "corsheaders",
    # Apps
    "chats",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.JWTCookieMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "FishQueryPlatform.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "FishQueryPlatform.wsgi.application"

# Database configuration
DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": os.getenv("POSTGRES_DB"),
        "USER": os.getenv("POSTGRES_USER"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD"),
        "HOST": os.getenv("POSTGRES_HOST"),
        "PORT": os.getenv("POSTGRES_PORT"),
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Australia/Perth"
USE_I18N = True
USE_L10N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")
STATIC_URL = "/static/"

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# REST Framework settings
REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticatedOrReadOnly",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "EXCEPTION_HANDLER": "chats.utils.custom_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "10/minute",
        "user": "1000/day",
        "register": "5/hour",
        "login": "10/minute",
        "token_refresh": "30/hour",
    },
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}

# Swagger settings
SWAGGER_SETTINGS = {
    "SECURITY_DEFINITIONS": {
        "Token": {
            "type": "apiKey",
            "name": "Authorization",
            "in": "header",
            "description": "Add your token in the format: Token <your_token>",
        }
    }
}

# =============================================================================
# Chat Settings
# =============================================================================
CHAT_DAILY_MESSAGE_LIMIT = 30  # Daily message limit for anonymous users
CHAT_MESSAGE_MAX_LENGTH = 200  # Maximum characters per message
CHAT_DEVICE_COOKIE_MAX_AGE = 365 * 24 * 60 * 60  # 1 year in seconds

# =============================================================================
# RAG (Retrieval Augmented Generation) Settings
# =============================================================================

# Qdrant Vector Database
QDRANT_URL = os.environ.get("QDRANT_URL")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY")
QDRANT_COLLECTION_NAME = os.environ.get("COLLECTION_NAME")

# Nomic Embedding API
NOMIC_TOKEN = os.environ.get("NOMIC_TOKEN")
NOMIC_API_URL = "https://api-atlas.nomic.ai/v1/embedding/text"
NOMIC_EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL")
NOMIC_EMBEDDING_DIMENSION = 768
NOMIC_TASK_TYPE = "search_query"

# Reranking
RERANK_MODEL = os.environ.get("RERANK_MODEL")
RAG_TOP_K = int(os.environ.get("TOP_K", 10))  # Documents to retrieve
RAG_RERANK_TOP_K = int(os.environ.get("RERANK_TOP_K", 5))  # Documents after reranking

# LLM (OpenAI-compatible API)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_API_URL = os.environ.get("OPENAI_API_URL")  # Optional: custom endpoint
OPENAI_MODEL = os.environ.get("OPENAI_MODEL")

# =============================================================================
# Hasura Settings
# =============================================================================
HASURA_ADMIN_SECRET = os.environ.get("HASURA_ADMIN_SECRET")
