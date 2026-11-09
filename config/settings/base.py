"""Sameiginlegar stillingar. Öll umhverfisgildi koma úr .env í gegnum python-decouple."""

from pathlib import Path

import dj_database_url
from decouple import Csv, config
from django.utils.csp import CSP
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config("SECRET_KEY", default="dev-only-insecure-key")
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", default="", cast=Csv())
# Aðallénið; beiðnum á önnur leyfð lén (www., jólahjól.is) er vísað þangað. Tómt = engin tilvísun.
CANONICAL_HOST = config("CANONICAL_HOST", default="")

INSTALLED_APPS = [
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "django_htmx",
    "django_cotton",
    "apps.core",
    "apps.accounts",
    "apps.households",
    "apps.gifts",
    "apps.wishlists",
    "apps.legacy",
]

MIDDLEWARE = [
    "apps.core.middleware.CanonicalHostMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.ContentSecurityPolicyMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.csp",
                "apps.core.context_processors.site",
            ],
        },
    },
]

DATABASES = {
    "default": dj_database_url.parse(
        config("DATABASE_URL", default="postgres://jolahjol:jolahjol@127.0.0.1:5433/jolahjol"),
        conn_max_age=config("DB_CONN_MAX_AGE", default=60, cast=int),
    )
}
# Gefast upp fljótt ef gagnagrunnurinn svarar ekki (t.d. Docker ekki í gangi) í stað þess að hanga
DATABASES["default"].setdefault("OPTIONS", {})["connect_timeout"] = 5
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Cache í gagnagrunninum svo takmörkun á beiðnum (allauth, óskalistar) gildi þvert á gunicorn-ferla.
# Taflan verður til með `manage.py createcachetable` (just migrate og entrypoint.sh).
CACHES = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "cache"}}
RATELIMIT_USE_CACHE = "default"
# Á bak við Cloudflare + nginx er REMOTE_ADDR alltaf nginx; þá deila allir einni takmörkun.
# Í prod: RATELIMIT_IP_META_KEY=HTTP_CF_CONNECTING_IP (raunveruleg IP-tala frá Cloudflare).
RATELIMIT_IP_META_KEY = config("RATELIMIT_IP_META_KEY", default=None) or None
# Sama fyrir takmarkanir allauth (innskráningarkóðar). Í prod: CF-Connecting-IP.
ALLAUTH_TRUSTED_CLIENT_IP_HEADER = config("ALLAUTH_TRUSTED_CLIENT_IP_HEADER", default=None) or None

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",  # admin
    "allauth.account.auth_backends.AuthenticationBackend",
]
LOGIN_URL = "account_request_login_code"
LOGIN_REDIRECT_URL = "home"

# Innskráning: netfang → kóði í tölvupósti. Nýskráning og innskráning eru eitt skref
# (sjá apps.accounts.forms.EmailCodeForm). Eftir fyrstu innskráningu má velja lykilorð og
# skrá sig svo inn með því á /accounts/login/; kóðinn virkar alltaf áfram (og kemur í stað endurstillingar).
ACCOUNT_ADAPTER = "apps.accounts.adapter.AccountAdapter"
ACCOUNT_FORMS = {
    "request_login_code": "apps.accounts.forms.EmailCodeForm",
    "login": "apps.accounts.forms.PasswordLoginForm",
    "set_password": "apps.accounts.forms.SetPasswordForm",
    "change_password": "apps.accounts.forms.ChangePasswordForm",
}
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_LOGIN_BY_CODE_ENABLED = True
ACCOUNT_LOGIN_BY_CODE_TIMEOUT = 15 * 60
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_SESSION_REMEMBER = True
ACCOUNT_LOGOUT_REDIRECT_URL = "home"
ALLAUTH_USER_CODE_FORMAT = {"numeric": True, "length": 6, "dashed": False}
# Fastur innskráningarkóði, aðeins fyrir þróun (sjá dev.py og apps.accounts.checks)
DEV_LOGIN_CODE = ""

# Google: virkt aðeins þegar lyklar eru komnir
GOOGLE_CLIENT_ID = config("GOOGLE_CLIENT_ID", default="")
GOOGLE_CLIENT_SECRET = config("GOOGLE_CLIENT_SECRET", default="")
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": ["profile", "email"],
        "EMAIL_AUTHENTICATION": True,  # Google-netfang tengist aðgangi með sama netfangi
        "EMAIL_AUTHENTICATION_AUTO_CONNECT": True,
        **(
            {"APPS": [{"client_id": GOOGLE_CLIENT_ID, "secret": GOOGLE_CLIENT_SECRET}]}
            if GOOGLE_CLIENT_ID
            else {}
        ),
    }
}
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_LOGIN_ON_GET = False
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Íslenska fyrst; allir textar fara í gegnum gettext svo enska bætist við án endurskrifta
LANGUAGE_CODE = "is"
LANGUAGES = [("is", _("Íslenska")), ("en", _("Enska"))]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Atlantic/Reykjavik"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

ADMIN_URL = config("DJANGO_ADMIN_URL", default="admin/")

EMAIL_BACKEND = config("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
# SMTP (í prod Gmail með app-lykilorði; önnur þjónusta = aðeins nýjar umhverfisbreytur)
EMAIL_HOST = config("EMAIL_HOST", default="localhost")
EMAIL_PORT = config("EMAIL_PORT", default=25, cast=int)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=False, cast=bool)
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="Jólahjól <noreply@localhost>")
# Full slóð vefsins fyrir hlekki í pósti sem er sendur utan beiðna (t.d. afmælisáminningar)
SITE_URL = config("SITE_URL", default="http://127.0.0.1:8000").rstrip("/")

# Öryggishausar (virkjaðir í prod með umhverfisbreytum)
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=False, cast=bool)
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]  # docker healthcheck kemur inn yfir HTTP
SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=0, cast=int)
SESSION_COOKIE_SECURE = config("SESSION_COOKIE_SECURE", default=False, cast=bool)
CSRF_COOKIE_SECURE = config("CSRF_COOKIE_SECURE", default=False, cast=bool)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# CSP: ekkert inline, allt hýst sjálf. Admin (unfold) er undanþegið, sjá apps.core.middleware.
SECURE_CSP = {
    "default-src": [CSP.SELF],
    "script-src": [CSP.SELF],
    "style-src": [CSP.SELF],
    "img-src": [CSP.SELF, "data:"],
    "font-src": [CSP.SELF],
    "connect-src": [CSP.SELF],
    "form-action": [CSP.SELF, "https://accounts.google.com"],
    "frame-ancestors": [CSP.NONE],
    "base-uri": [CSP.SELF],
    "object-src": [CSP.NONE],
}

# Á bak við Cloudflare: beiðnir koma inn yfir HTTP en eru HTTPS hjá notandanum
if config("SECURE_PROXY_SSL_HEADER", default="", cast=str):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Sentry virkjast aðeins þegar SENTRY_DSN er sett
SENTRY_DSN = config("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=config("SENTRY_TRACES_SAMPLE_RATE", default=0.2, cast=float),
        send_default_pii=False,
        environment=config("SENTRY_ENVIRONMENT", default="production"),
    )

UNFOLD = {
    "SITE_TITLE": "Jólahjól",
    "SITE_HEADER": "Jólahjól",
}
