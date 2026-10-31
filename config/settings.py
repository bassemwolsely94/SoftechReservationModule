"""
ElRezeiky Pharmacy Operations Platform — Django Settings
Production configuration for Windows Server deployment
"""
import os
import sys
from pathlib import Path
from decouple import config
from datetime import timedelta

# Force UTF-8 (with replacement) on stdout/stderr so emoji / Arabic / em-dash in
# our logs never crash the cp1256 Windows console. Settings load on every entry
# point (manage.py, ASGI/daphne, wsgi, `python -c`), so this covers them all.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# ── Python 3.14 + Django 4.2 compatibility patch ─────────────────────────────
# Django 4.2's BaseContext.__copy__ calls super().__copy__() which in Python
# 3.14 returns a super-proxy object that doesn't support attribute assignment.
# Patched here (before Django initialises) so every changelist/template works.
def _patch_django_context():
    try:
        from django.template.context import BaseContext
        def _py314_copy(self):
            cls = self.__class__
            duplicate = cls.__new__(cls)
            duplicate.__dict__.update(self.__dict__)
            duplicate.dicts = self.dicts[:]
            return duplicate
        BaseContext.__copy__ = _py314_copy
    except Exception:
        pass

if sys.version_info >= (3, 14):
    _patch_django_context()
# ─────────────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY', default='')

DEBUG = config('DEBUG', default=False, cast=bool)

# Django admin has no 2FA (N0/H9): off in production, on in dev. Turn on for a maintenance window only.
DJANGO_ADMIN_ENABLED = config('DJANGO_ADMIN_ENABLED', default=DEBUG, cast=bool)

# Signing key for JWTs, portal sessions, delivery-tracking / PBX-recording links and
# (when OMNI_CREDENTIALS_KEY is unset) the encryption of stored channel credentials.
# A missing or placeholder key would make all of those forgeable, so a non-DEBUG
# process refuses to start without a real one. Dev (DEBUG=True) and the test runner
# fall back to a throwaway per-process key.
_RUNNING_TESTS = len(sys.argv) > 1 and sys.argv[1] == 'test'

# A test run ignores .env for every SOFTECH write / gate / alert switch (…_ENABLED, …_WRITE,
# COUPON_GUARD_…, …_AUTO_APPROVE, …_NOTIFY, …) and takes the code default instead — the value
# the tests are written against. Without this a production .env (writers ON) made every
# "gate off by default" test fail. Tests that need a gate open use override_settings.
# SOFTECH_TESTS_ALLOW_LIVE=True keeps .env for a deliberate run against a TEST server.
if _RUNNING_TESTS and not config('SOFTECH_TESTS_ALLOW_LIVE', default=False, cast=bool):
    import re as _re
    _GATE_KEY = _re.compile(r'(_ENABLED|_WRITE|_WRITER|_AUTO_APPROVE|_AUTO_TOPUP|_UPDATE_PATIENTDATA|_NOTIFY)$'
                            r'|^COUPON_GUARD_')
    _env_config = config

    def config(key, *args, **kwargs):          # noqa: F811 — test-run wrapper
        if _GATE_KEY.search(key) and 'default' in kwargs:
            value, cast = kwargs['default'], kwargs.get('cast')
            if isinstance(value, str) and cast is bool:
                return value.strip().lower() in ('1', 'true', 'yes', 'on')
            return cast(value) if (cast and isinstance(value, str)) else value
        return _env_config(key, *args, **kwargs)

if not SECRET_KEY or SECRET_KEY.startswith('change-me'):
    if DEBUG or _RUNNING_TESTS:
        SECRET_KEY = SECRET_KEY or 'dev-only-insecure-' + os.urandom(16).hex()
    else:
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured(
            'SECRET_KEY is missing or still the placeholder. Set a long random value in .env '
            '(python -c "import secrets; print(secrets.token_urlsafe(50))").'
        )

# Production must list its hostnames; '*' is only a DEBUG convenience.
ALLOWED_HOSTS = [h.strip() for h in config(
    'ALLOWED_HOSTS', default='*' if DEBUG else 'localhost,127.0.0.1',
).split(',') if h.strip()]

# ── HTTPS / reverse-proxy hardening ──────────────────────────────────────────
# Origins allowed to POST to Django-rendered forms (the /admin/ login) — needed
# behind HTTPS on Django 4.x, e.g. "https://erp.example.com".
CSRF_TRUSTED_ORIGINS = [o.strip() for o in config('CSRF_TRUSTED_ORIGINS', default='').split(',') if o.strip()]
# Set BEHIND_HTTPS_PROXY=True ONLY when a proxy (Nginx / tunnel) terminates TLS and
# overwrites X-Forwarded-Proto — otherwise a client could claim https itself.
BEHIND_HTTPS_PROXY = config('BEHIND_HTTPS_PROXY', default=False, cast=bool)
if BEHIND_HTTPS_PROXY:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
# Proxies in front of Django that APPEND the peer to X-Forwarded-For (nginx proxy_params: 1).
# The client address is the NUM_PROXIES-th entry from the right; with 0 the header is ignored.
# Used by core.client_ip (audit IPs) and DRF's throttles (Batch 3, A-6; owner 2026-10-27: 1 on
# the VPS). Defaults to 1 behind the HTTPS proxy — with 0 there, every user would share
# nginx's 127.0.0.1 and one login-throttle bucket.
NUM_PROXIES = config('NUM_PROXIES', default=1 if BEHIND_HTTPS_PROXY else 0, cast=int)
SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=False, cast=bool)
# Secure flag on the JWT cookies (core/auth_cookies.py). On by default whenever the
# site is served over HTTPS; off only for plain-HTTP LAN deployments.
AUTH_COOKIE_SECURE = config('AUTH_COOKIE_SECURE', default=BEHIND_HTTPS_PROXY or SECURE_SSL_REDIRECT, cast=bool)
SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=0, cast=int)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
X_FRAME_OPTIONS = 'DENY'
SESSION_COOKIE_HTTPONLY = True

INSTALLED_APPS = [
    # daphne MUST be first so it can serve WebSocket + HTTP via ASGI
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third party
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',   # Gap-2: blacklist refresh tokens on pw change
    'corsheaders',
    'django_filters',
    'django_extensions',
    'channels',
    # Platform apps
    'apps.branches',
    'apps.catalog',
    'apps.customers',
    'apps.erp',            # ERP transaction mirror (stktransm/stktrans/localcustomers)
    'apps.reservations',
    'apps.users',
    'apps.sync',
    'apps.dashboard',
    'apps.notifications',
    'apps.transfers',
    'apps.transits',
    'apps.demand',
    'apps.chronic',
    'apps.composition',   # SOFTECH active-ingredient reconciliation pipeline
    'apps.followups',
    'apps.callcenter',
    'apps.audit',
    'apps.config',
    'apps.stockcount',
    'apps.shortage',
    'apps.vouchers',
    'apps.invoices',
    'apps.incentives',
    'apps.insurance',
    'apps.commerce',
    'apps.purchasing',
    'apps.delivery',
    'apps.payments',
    'apps.analytics',
    'apps.tasks',
    'apps.procurement',
    'apps.product_experience',
    'apps.finance',
    'apps.recommendations',
    'apps.campaigns',
    'apps.whatsapp',
    'apps.omni',       # Omnichannel unification layer (doc 15) — envelopes whatsapp/pbx/callcenter
    'apps.social',     # Social channels (doc 15 Phase 3) — Messenger/Instagram/Telegram
    'apps.loyalty',
    'apps.offers',     # Offers & promotions engine (Commerce OS Phase 3 — money-critical)
    'apps.vision',     # In-house OCR engine (Phase 1 — OcrSample corpus; sales + purchasing)
    'apps.supply',     # Demand/Allocation/Procurement orchestration spine (doc 24) — reuses engines
    'apps.lineage',    # Shared transaction-lineage graph (DocumentRef/DocumentEdge) — doc 25
    'apps.replacement',  # بدل الروشتة / buy-back case orchestration (doc 25) — Phase 0 read-only
    'apps.referral',
    'apps.pbx',
    'apps.cheques',
    'apps.enrichment',
    'apps.images',
    'apps.discount_approvals',
    'apps.approvals',
    'apps.batches',
    'apps.hr',
    'apps.forecasting',
    'apps.insights',
    'apps.qa',
    'apps.portal',         # Customer-facing self-service portal (external, magic-link auth)
    'apps.pos_orders',     # Indirect-POS pending-order writer (SOFTECH writes gated off)
    'apps.help',           # In-app help (دليل الاستخدام) — repo content + trainer edits
    'apps.personal',       # Personal dashboard — per-user SOFTECH identity claims + configurable widgets
    'apps.gamification',   # Gamification — points, levels/titles, badges, streaks, rankings (recognition only)
    'apps.stock_audit',    # Stock Transactions Audit (doc 32) — read-only stktrans mirror + checks
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION  = 'config.asgi.application'

# ── DJANGO CHANNELS ───────────────────────────────────────────────────────────
# InMemoryChannelLayer: zero-config for single-process dev / small deployments.
# For multi-process production swap to RedisChannelLayer:
#   pip install channels-redis
#   CHANNEL_LAYERS = {'default': {'BACKEND': 'channels_redis.core.RedisChannelLayer',
#                                 'CONFIG': {'hosts': [('127.0.0.1', 6379)]}}}
_REDIS_URL = config('REDIS_URL', default='')
if _REDIS_URL:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {'hosts': [_REDIS_URL]},
        }
    }
else:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        }
    }

# ── DATABASE ──────────────────────────────────────────────────────────────────
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('PG_NAME', default='elrezeiky_db'),
        'USER': config('PG_USER', default='postgres'),
        'PASSWORD': config('PG_PASSWORD', default=''),
        'HOST': config('PG_HOST', default='localhost'),
        'PORT': config('PG_PORT', default='5432'),
        # CONN_MAX_AGE=0: close the PG connection after every request.
        # With Django's ASGI thread-pool each thread holds one connection while
        # CONN_MAX_AGE>0; on a multi-core dev machine that quickly exhausts
        # PostgreSQL's default max_connections=100.
        # For production behind pgbouncer set CONN_MAX_AGE=None instead.
        'CONN_MAX_AGE': 0,
        'CONN_HEALTH_CHECKS': True,   # Django 4.1+ — validate before reuse
        'OPTIONS': {
            'connect_timeout': 10,
        },
        # Optional isolated test-DB name so concurrent `manage.py test` runs (e.g.
        # two sessions) don't fight over the single default `test_<PG_NAME>`.
        # Unset → Django's default naming (unchanged behaviour).
        'TEST': {'NAME': config('TEST_DB_NAME', default=None)},
    }
}

# ── REST FRAMEWORK ─────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        # Bearer header OR the httpOnly access cookie (core/auth_cookies.py)
        'core.auth_cookies.CookieJWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
    'DATETIME_FORMAT': '%Y-%m-%dT%H:%M:%S',
    # Disable DRF's ?format= URL override so our export views can use
    # ?format=csv / ?format=xlsx as their own file-type parameter without
    # DRF intercepting it and returning 404 for unknown renderer types.
    'URL_FORMAT_OVERRIDE': None,
    # Gap-1: Throttle classes applied per-view; no global throttle to avoid
    # breaking authenticated API endpoints.
    'DEFAULT_THROTTLE_CLASSES': [],
    # Throttles key on the real client, not the client-written X-Forwarded-For (A-6).
    'NUM_PROXIES': NUM_PROXIES,
    'DEFAULT_THROTTLE_RATES': {
        'login': '10/min',   # max 10 login attempts per IP per minute
        'personal_person_search': '30/hour',   # live SOFTECH personsdata search (N0/H1)
        # Customer portal (external) magic-link request + token exchange
        'portal_request_link': config('PORTAL_REQUEST_LINK_RATE', default='5/min'),
        'portal_auth':         config('PORTAL_AUTH_RATE',         default='10/min'),
    },
}

# ── CUSTOMER SELF-SERVICE PORTAL (external, magic-link auth) ──────────────────
# Token lifetimes in seconds. Short by design — the magic link is single-use-ish
# (signed + short TTL) and the session is re-issued on demand.
PORTAL_MAGIC_LINK_TTL = config('PORTAL_MAGIC_LINK_TTL', default=900,        cast=int)   # 15 min
PORTAL_SESSION_TTL    = config('PORTAL_SESSION_TTL',    default=12 * 3600,  cast=int)   # 12 h

# ── JWT ───────────────────────────────────────────────────────────────────────
SIMPLE_JWT = {
    # Gap-2: Reduced from 12h → 1h.  An attacker who steals an access token
    # can still use it until expiry (access tokens can't be individually
    # invalidated without a per-request DB check), so a shorter lifetime
    # shrinks the attack window.  Refresh tokens ARE blacklisted on pw change.
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,   # Gap-2: blacklist old refresh token on every rotation
    'UPDATE_LAST_LOGIN': True,
}

# ── CORS ──────────────────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = config(
    'CORS_ORIGINS',
    default='http://localhost:3000,http://localhost:5173'
).split(',')
CORS_ALLOW_CREDENTIALS = True

# ── STATIC & MEDIA ────────────────────────────────────────────────────────────
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
# Uploaded files get signed, expiring URLs (core/storage.py); /media/ is served by
# core.media.serve_media, which checks the signature. Product images stay public.
STORAGES = {
    'default':     {'BACKEND': 'core.storage.SignedMediaStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
MEDIA_URL_TTL = config('MEDIA_URL_TTL', default=6 * 3600, cast=int)   # seconds, minimum link lifetime
# True behind Nginx: Django checks the signature, Nginx sends the bytes via the
# internal /protected-media/ location (deploy/nginx.conf).
MEDIA_ACCEL_REDIRECT = config('MEDIA_ACCEL_REDIRECT', default=False, cast=bool)

# ── INTERNATIONALISATION ──────────────────────────────────────────────────────
LANGUAGE_CODE = 'ar'
TIME_ZONE = 'Africa/Cairo'
USE_I18N = True
USE_TZ = True

# ── PASSWORDS ─────────────────────────────────────────────────────────────────
# 10 characters plus Django's checks (Batch 3, A-5; owner 2026-10-27). Applied by
# apps.users.passwords on change-password, admin reset and user create.
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 10}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ── LOGGING ───────────────────────────────────────────────────────────────────
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
            # Force UTF-8 on Windows so Arabic / arrow characters don't crash
            # the CP1256 console handler with UnicodeEncodeError.
            'stream': 'ext://sys.stdout',
        },
        'file': {
            # SafeTimedRotatingFileHandler rotates at midnight but never crashes
            # if the file is locked by another process (dev server + a management
            # command running concurrently) or by OneDrive sync — it keeps writing
            # to the current file and retries the rollover later.
            'class': 'config.log_handlers.SafeTimedRotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'platform.log',
            'when': 'midnight',
            'backupCount': 7,
            'formatter': 'verbose',
            'encoding': 'utf-8',
            'delay': True,
        },
    },
    'loggers': {
        'elrezeiky': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# ── SYBASE (read-only, via jConnect JDBC) ─────────────────────────────────────
SYBASE_HOST     = config('SYBASE_HOST', default='localhost')
SYBASE_PORT     = config('SYBASE_PORT', default='5000')
SYBASE_USER     = config('SYBASE_USER', default='')
SYBASE_PASSWORD = config('SYBASE_PASSWORD', default='')
# Global kill-switch: True refuses EVERY non-read statement on EVERY SOFTECH
# connection (HQ + branches), whatever the per-feature *_ENABLED flags say.
# Turn it on for staging / UAT / demos. See config/sybase.py.
SOFTECH_READ_ONLY = config('SOFTECH_READ_ONLY', default=False, cast=bool)
# Staging: send every branch-server connection to this host ('host' or 'host:port')
# instead of the production addresses stored in Branch.db_host.
SOFTECH_BRANCH_HOST_OVERRIDE = config('SOFTECH_BRANCH_HOST_OVERRIDE', default='')
# The test runner must never reach a real SOFTECH, whatever the developer's .env
# says (several writer tests drive the live code path to prove a gate is open).
# No HQ host, every branch connection sent to an unresolvable name, and the
# read-only guard on. SOFTECH_TESTS_ALLOW_LIVE=True opts out for a deliberate
# integration run against a TEST server.
if _RUNNING_TESTS and not config('SOFTECH_TESTS_ALLOW_LIVE', default=False, cast=bool):
    SYBASE_HOST = ''
    SOFTECH_BRANCH_HOST_OVERRIDE = 'softech-disabled-in-tests.invalid'
    SOFTECH_READ_ONLY = True
    for _k in ('SOFTECH_DEV_HOST', 'SOFTECH_TEST_HOST', 'SOFTECH_PROD_HOST'):
        os.environ.pop(_k, None)

# Per-feature switches for these SOFTECH writes. Like every other SOFTECH writer they
# default OFF: a write runs only where the environment deliberately turns it on
# (.env / production env — see .env.example). Checked in the view AND in the writer,
# so scheduled jobs and management commands obey them too.
PRICING_SOFTECH_WRITE_ENABLED   = config('PRICING_SOFTECH_WRITE_ENABLED', default=False, cast=bool)   # approved price/discount + classification UPDATE items
REPLICATION_REPAIR_ENABLED      = config('REPLICATION_REPAIR_ENABLED', default=False, cast=bool)      # restamp/push items to branches (manual + scheduled)
LOYALTY_SOFTECH_WRITE_ENABLED   = config('LOYALTY_SOFTECH_WRITE_ENABLED', default=False, cast=bool)   # manual purchase-points INSERT picpoints
PERSONAL_COMMENT_WRITE_ENABLED  = config('PERSONAL_COMMENT_WRITE_ENABLED', default=False, cast=bool)  # stktransm.comments / cheques.chequenote
# SOFTECH rehearsals and diagnostics (core/softech_switches.py): invoice «probe», coupon
# «batch-probe», clone_purchase, every writer probe_* and every diagnostic command mode that
# writes — real DML rolled back or restored; production triggers still fire, locks are held.
SOFTECH_PROBES_ENABLED          = config('SOFTECH_PROBES_ENABLED', default=False, cast=bool)

# Roles allowed to manually add/deduct customer loyalty points (POST
# /api/loyalty/customers/<id>/adjust/ — purchase points write SOFTECH picpoints).
LOYALTY_ADJUST_ROLES = frozenset(
    r.strip() for r in config('LOYALTY_ADJUST_ROLES', default='admin,supervisor,call_center').split(',')
    if r.strip()
)
# Purchase-points safety: largest manual adjustment per request (±), and how long an
# identical adjustment (customer, points, reason) is refused as a probable double post.
LOYALTY_MAX_MANUAL_ADJUST         = config('LOYALTY_MAX_MANUAL_ADJUST', default=1000, cast=int)
LOYALTY_DUPLICATE_WINDOW_SECONDS  = config('LOYALTY_DUPLICATE_WINDOW_SECONDS', default=120, cast=int)
# Default per-statement timeout (seconds) for INTERACTIVE queries — bounds an
# HTTP request against a slow/blocked Sybase read. jConnect enforces this as a
# socket read-timeout (fires as JZ0T3 on fetch), so keep it snappy.
SYBASE_QUERY_TIMEOUT      = config('SYBASE_QUERY_TIMEOUT', default=30, cast=int)
# Generous timeout (seconds) for the background full-sync's heavy stktrans scan,
# passed explicitly per-query. Bounded (not unlimited) so a link that dies
# mid-fetch can't wedge the every-5-min sync job forever.
SYBASE_SYNC_QUERY_TIMEOUT = config('SYBASE_SYNC_QUERY_TIMEOUT', default=300, cast=int)
# ── Tiered sync cadence ───────────────────────────────────────────────────────
# The sync is split into two lanes so fast-changing data (stock, sales) refreshes
# often while the expensive full snapshots (items ~40s, customers ~100s) refresh
# rarely. See apps/sync/tasks.py run_fast_sync / run_slow_sync.
SYNC_FAST_MINUTES = config('SYNC_FAST_MINUTES', default=5, cast=int)
SYNC_SLOW_MINUTES = config('SYNC_SLOW_MINUTES', default=60, cast=int)
# SOFTECH load telemetry (doc 30): count logins / queries / rows per job and caller,
# saved hourly in SoftechLoadStat and shown on /sync. Off under tests (they turn it on).
SOFTECH_LOAD_TELEMETRY = config('SOFTECH_LOAD_TELEMETRY', default=not _RUNNING_TESTS, cast=bool)
# Module SOFTECH writes are attributed to each approver's OWN real usercode
# (synced from the SOFTECH users table). Repairs preserve the item's original
# editor. No fabricated/service ERP user is used — every write maps to a real
# SOFTECH user. ERP_SERVICE_USERCODE is kept only as a last-resort fallback for
# fully-automated writes where no real user context exists.
ERP_SERVICE_USERCODE = config('ERP_SERVICE_USERCODE', default='')

# ── Indirect-POS writer (apps.pos_orders) ─────────────────────────────────────
# MASTER KILL-SWITCH. Default False → the writer never sends INSERT/DELETE to
# SOFTECH; /push returns a dry-run plan only. Flip to True ONLY after the live
# write path is implemented and validated against SOFTECH_TEST_HOST.
POS_WRITER_ENABLED = config('POS_WRITER_ENABLED', default=False, cast=bool)
POS_WRITER_PROFILE = config('POS_WRITER_PROFILE', default='test')   # test|prod
# Wave 3 inc3: batch-write OUR POS item-selection telemetry into SOFTECH pos_cancel (the
# «المبيعات غير المخزنة» activity log — NOT a transactional/financial table). OFF until the
# owner signs off a dry-run. When False, write_pos_cancel_batch runs in dry-run only.
POS_CANCEL_WRITE_ENABLED = config('POS_CANCEL_WRITE_ENABLED', default=False, cast=bool)
# Feature 1 (/supply): write our engine's monthly_avg → SOFTECH stkbal.monthlyqty
# (معدل الإستهلاك). OFF = /supply propose+approve work but execute is refused (409).
# Flip True ONLY after a reviewed dry-run + a validated rollback write-probe.
SALES_RATE_WRITER_ENABLED = config('SALES_RATE_WRITER_ENABLED', default=False, cast=bool)
# Feature 2 (/supply): generate a SOFTECH ISR (طلب توريد, stockisr) from our engine
# for a requesting branch → flows into native اعتماد → إذن الصرف. OFF = dry-run plan
# only. Flip True ONLY after a validated rollback ISR-probe on a real serial.
ISR_WRITER_ENABLED = config('ISR_WRITER_ENABLED', default=False, cast=bool)
# Feature 2: allow scheduled/CLI generation to AUTO-APPROVE (stockisrm.israpp=1) without
# a human review step in /supply. OFF by default (human-in-the-loop). Needs ISR_WRITER_ENABLED.
ISR_AUTO_APPROVE_ENABLED = config('ISR_AUTO_APPROVE_ENABLED', default=False, cast=bool)
# Doc 24 Phase 4: send actionable supply-case alerts (new urgent case / supplier availability
# matching waiting customers / unresolved 3-7 days) from the daily sweep to admin/supervisor/
# purchasing. Once-per-case (dedup_once) + capped per sweep. OFF by default — enable after
# reviewing the queue volume on /supply. The sweep itself still runs and keeps cases current.
SUPPLY_CASE_NOTIFY = config('SUPPLY_CASE_NOTIFY', default=False, cast=bool)
# Batch 2b (/supply): write the max-stock COVERAGE window into SOFTECH
# stkbal.maxnowqtymonths (the field SOFTECH multiplies by monthlyqty to derive the
# maxnowqty ceiling). OFF = dry-run plan only (nothing written). Flip True ONLY after
# a reviewed dry-run + rollback write-probe. Independent of the rate gate on purpose.
COVERAGE_WRITER_ENABLED = config('COVERAGE_WRITER_ENABLED', default=False, cast=bool)
# When the coverage write runs, ALSO set the derived stkbal.maxnowqty
# (= monthlyqty × maxnowqtymonths) instead of leaving it for SOFTECH's own recompute.
# OFF by default — owner confirms from a dry-run whether SOFTECH needs the stored max too.
COVERAGE_WRITE_MAXQTY = config('COVERAGE_WRITE_MAXQTY', default=False, cast=bool)
# After each successful engine run, the scheduler tops up coverage: items with no
# coverage get COVERAGE_AUTO_TOPUP_MONTHS, stale maxes are refreshed; coverages set on
# purpose are never changed. Needs COVERAGE_WRITER_ENABLED too. Owner chose option (a)
# on 2026-09-28 → set 'both' in .env (branch servers + server 100's copies of the
# branches). Code default stays 'node'; branch 100's own rows are never written.
COVERAGE_AUTO_TOPUP_ENABLED = config('COVERAGE_AUTO_TOPUP_ENABLED', default=False, cast=bool)
# SOFTECH user groups (usergroup codes) that may operate /supply (approve/execute rates,
# ISRs, توزيعة) and start a quick engine run, on top of the app roles — see
# apps/purchasing/access.py. Default: 10 Administrator, 19 مخزن, 21 كارت صنف,
# 27 Internal Auditor (owner, 2026-10-02).
SUPPLY_ERP_GROUPS = config('SUPPLY_ERP_GROUPS', default='10,19,21,27')
# Automatic demand-engine runs (owner, 2026-10-02: Sunday + Wednesday nights, Cairo).
# The rates it produces still need a human to approve/execute in /supply; coverage is
# topped up automatically afterwards. OFF by default.
DEMAND_ENGINE_SCHEDULE_ENABLED = config('DEMAND_ENGINE_SCHEDULE_ENABLED', default=False, cast=bool)
DEMAND_ENGINE_SCHEDULE_DAYS    = config('DEMAND_ENGINE_SCHEDULE_DAYS', default='sun,wed')
DEMAND_ENGINE_SCHEDULE_HOUR    = config('DEMAND_ENGINE_SCHEDULE_HOUR', default=1, cast=int)
DEMAND_ENGINE_SCHEDULE_MINUTE  = config('DEMAND_ENGINE_SCHEDULE_MINUTE', default=0, cast=int)
COVERAGE_AUTO_TOPUP_MONTHS  = config('COVERAGE_AUTO_TOPUP_MONTHS', default=1.5, cast=float)
COVERAGE_AUTO_TOPUP_TARGET  = config('COVERAGE_AUTO_TOPUP_TARGET', default='node')
# Optional per-branch storecode override for the rate writer (JSON not needed —
# code map lives in settings if ever required): SALES_RATE_STORE_MAP = {}
# Commerce-OS Phase 3: allow the offers engine to ATTACH computed discounts onto a
# real POS order (still PG-only; the SOFTECH push is the existing writer). OFF until
# an owner-reviewed live dry-run signs it off (design doc step 5).
POS_OFFERS_EXECUTION_ENABLED = config('POS_OFFERS_EXECUTION_ENABLED', default=False, cast=bool)
# Commerce Document engine (quotations / retail invoices / hospital allocation
# grids).  Phase 1 = data + pricing only; the flag gates the UI/API surface that
# later phases add.  OFF until the engine is proven.
COMMERCE_DOCS_ENABLED = config('COMMERCE_DOCS_ENABLED', default=False, cast=bool)
# Channel A: let a FLAT-RATE offer push its % to items.posdiscp (master data, all
# cashier sales) via the discount_approvals writeback. OFF until owner-reviewed.
POS_OFFERS_POSDISCP_WRITE_ENABLED = config('POS_OFFERS_POSDISCP_WRITE_ENABLED', default=False, cast=bool)
# SOFTECH manager-override usercode stamped on stktransm5.supp_main_code for an
# offer-discounted order, so a discount above the seller's normal ceiling is
# pre-authorized (the DB-recorded equivalent of the Ctrl+M / OFFERS override).
POS_OFFERS_OVERRIDE_USERCODE = config('POS_OFFERS_OVERRIDE_USERCODE', default='89')
# Channel B: write our gift/spend-threshold/single-item-percent offers into SOFTECH's
# native `specialoffers` promo table (runs at the cashier). OFF until owner-reviewed.
POS_OFFERS_PROMO_WRITE_ENABLED = config('POS_OFFERS_PROMO_WRITE_ENABLED', default=False, cast=bool)
# (Historically blocked points sales from the writer.) We now compute personnewbal correctly
# (points = Σ floor(net × custdiscounts[rep, itemcode_alt3]/100); SOFTECH copies it at
# finalization), so points-eligible sales are ALLOWED. Set True only to force them native again.
POS_BLOCK_POINTS_SALES = config('POS_BLOCK_POINTS_SALES', default=False, cast=bool)
# Reject out-of-stock items from the live writer (we don't write حجز 80, so an OOS line can't
# finalize — matches native منع الصرف). See apps/pos_orders/stock.py.
POS_ENFORCE_STOCK = config('POS_ENFORCE_STOCK', default=True, cast=bool)
# softech_branch_ids where SOFTECH's reservation system (نظام الحجز) is ENABLED — there an OOS line
# is written as a حجز (item_partno='Reservation', placeholder expiry) and the cashier's finalization
# auto-creates the حجز 80. Elsewhere OOS is rejected (native منع الصرف). Comma-separated, e.g. "130,140".
POS_RESERVATION_BRANCHES = [b.strip() for b in config('POS_RESERVATION_BRANCHES', default='').split(',') if b.strip()]
POS_DEFAULT_SELLER_USERCODE = config('POS_DEFAULT_SELLER_USERCODE', default='')
# Read authoritative branch prices/tax/cost live from the branch DB when preparing
# an order (SELECT only). Default False → use the catalog mirror (offline-safe).
POS_LIVE_PRICING = config('POS_LIVE_PRICING', default=False, cast=bool)
# Connection charset for the POS writeback path. MUST be 'iso_1': the writer pre-encodes each string to
# cp1256 bytes carried as latin-1 and sends them through this connection so Arabic (patientname, comments,
# batch labels…) lands verbatim in the cp1256 columns. CHARSET='cp1256' GARBLES Arabic to '?' (verified);
# 'utf8' is rejected by the server. Only the writer uses it; global reads are unchanged. See writer._enc_arabic.
POS_WRITE_CHARSET = config('POS_WRITE_CHARSET', default='iso_1')
# Authority-aware discount validation at /ready (live read of custdiscounts/managerdiscount).
# ON: joins resolved (item category=items.itemstoreclassif; seller=managerdiscount.personcode;
# customer=channel default CashCust/HomeDlvry for cash/delivery). Acts only on resolved data
# and only escalates ABOVE the contracted rate, so it never false-rejects; contract/insurance
# individual-customer mapping is unconfirmed and skipped. Set False to disable the live read.
POS_DISCOUNT_AUTHORITY = config('POS_DISCOUNT_AUTHORITY', default=True, cast=bool)

# ── Supplier-invoice writeback (apps/invoices Track B) ───────────────────────
# Master kill-switch for writing OCR'd supplier invoices into SOFTECH as FINAL
# purchase documents (stktransm/stktrans, doccode 10 / 120). Default False → the
# writer only PREPARES + builds a dry-run plan; nothing is sent to SOFTECH. Flip
# to True ONLY after validating the live path against SOFTECH_TEST_HOST (the final
# insert fires SOFTECH's stock-receive + weighted-avg-cost + supplier-balance triggers).
# Structured-OCR engine for supplier invoices: 'auto' (Gemini if GEMINI_API_KEY
# set, else the best free local engine — Tesseract+Arabic, then easyOCR),
# 'gemini', 'tesseract' or 'easyocr'. Lets the pharmacy run invoice extraction at
# zero API cost. See apps/invoices/engines.py.
INVOICE_OCR_ENGINE      = config('INVOICE_OCR_ENGINE', default='auto')
# In 'auto' mode, run the free engine first and escalate to Gemini only when the
# free result's quality score (fraction of lines with a name + a plausible price)
# is below this threshold. Higher = escalate more often (more accuracy, more cost).
INVOICE_OCR_ESCALATE_THRESHOLD = config('INVOICE_OCR_ESCALATE_THRESHOLD', default=0.6, cast=float)
# PDF render resolution. 300 DPI is Tesseract's sweet spot for printed Arabic;
# raise for tiny print, lower for speed. Applies to the invoice-bundle renderer.
INVOICE_PDF_DPI         = config('INVOICE_PDF_DPI', default=300, cast=int)
# Pre-enhance scanned pages before free OCR (autocontrast + deskew + upscale).
INVOICE_OCR_ENHANCE     = config('INVOICE_OCR_ENHANCE', default=True, cast=bool)
# Extra, opt-in image-perfecting steps (applied by preprocess.enhance_for_ocr AFTER
# the base enhance). Each is off by default — turn on and A/B via the benchmark,
# since the best combination is scan-quality dependent and they cost time.
INVOICE_OCR_EQUALIZE    = config('INVOICE_OCR_EQUALIZE', default=False, cast=bool)   # histogram equalize (uneven lighting)
INVOICE_OCR_SHARPEN     = config('INVOICE_OCR_SHARPEN', default=False, cast=bool)    # unsharp mask (soft/blurry scans)
INVOICE_OCR_BINARIZE    = config('INVOICE_OCR_BINARIZE', default=False, cast=bool)   # Sauvola adaptive binarization (faint/shadowed scans)
# Field voting: also run RapidOCR and prefer its digits for the numeric columns
# (slower — adds a second OCR pass — but more accurate prices). Off by default.
INVOICE_OCR_FIELD_VOTING = config('INVOICE_OCR_FIELD_VOTING', default=False, cast=bool)
# Tesseract (free local OCR). The binary path and a tessdata dir that contains
# ara.traineddata (+ eng). On Windows the binary is usually at
# 'C:\\Program Files\\Tesseract-OCR\\tesseract.exe'. Leave TESSDATA_PREFIX blank
# to use the binary's bundled tessdata (must already include Arabic).
TESSERACT_CMD             = config('TESSERACT_CMD', default='')
TESSERACT_TESSDATA_PREFIX = config('TESSERACT_TESSDATA_PREFIX', default='')
INVOICE_WRITER_ENABLED  = config('INVOICE_WRITER_ENABLED', default=False, cast=bool)
INVOICE_WRITER_PROFILE  = config('INVOICE_WRITER_PROFILE', default='test')   # test|prod
INVOICE_DEFAULT_USERCODE = config('INVOICE_DEFAULT_USERCODE', default='')    # fallback buyer usercode
INVOICE_WRITE_CHARSET   = config('INVOICE_WRITE_CHARSET', default='cp1256')

# ── Gift-coupon stocking (apps/vouchers/coupons.py) ──────────────────────────
# One coupon serial = one purchase line on EACH item from supplier 1268 into HQ.
# See docs/architecture/SOFTECH_GIFT_VOUCHER_STOCKING.md
COUPON_POINTS_ITEM      = config('COUPON_POINTS_ITEM', default='102230')   # COUPON FOR POINTS
COUPON_SERVED_ITEM      = config('COUPON_SERVED_ITEM', default='118639')   # COUPON SERVED TO CUSTOMER
COUPON_SUPPLIER         = config('COUPON_SUPPLIER', default='1268')        # هدايا الاداره لخدمة العملاء
COUPON_BRANCH           = config('COUPON_BRANCH', default='100')           # HQ
COUPON_BATCH_SIZE       = config('COUPON_BATCH_SIZE', default=200, cast=int)
COUPON_MIN_EXPIRY_DAYS  = config('COUPON_MIN_EXPIRY_DAYS', default=730, cast=int)
COUPON_PRINT_TITLE      = config('COUPON_PRINT_TITLE', default='قسيمة مشتروات من صيدليات الرزيقى بقيمة 50ج.م')
# ── A/P reconciliation writeback (سداد allocations → chequestrans + stktransm) ──
# Records reconstructed allocations of EXISTING vouchers to invoices. NEVER creates
# a cheques row (irreversible). OFF by default (human-in-the-loop, no rollback net).
AP_RECONCILE_WRITER_ENABLED    = config('AP_RECONCILE_WRITER_ENABLED', default=False, cast=bool)
# A test run must NEVER reach live SOFTECH, whatever .env says (tests that exercise
# the live path opt back in with override_settings + a mocked connection).
if len(sys.argv) > 1 and sys.argv[1] == 'test':
    AP_RECONCILE_WRITER_ENABLED = False
AP_RECONCILE_UPDATE_PATIENTDATA = config('AP_RECONCILE_UPDATE_PATIENTDATA', default=False, cast=bool)
# Kill-switch for the owner's auto-approve policy (recon_actions.auto_approve). When
# False, rounds propose + hold but approve nothing, so nothing new reaches the writer.
AP_RECONCILE_AUTO_APPROVE      = config('AP_RECONCILE_AUTO_APPROVE', default=True, cast=bool)
AP_RECONCILE_DEFAULT_USERCODE  = config('AP_RECONCILE_DEFAULT_USERCODE', default='')

# ── بدل الروشتة live workflow (doc 25 Phase 1) ──
# Master switch for SOFTECH postings FROM a case (purchase / contract sale / product sale legs).
# OFF ⇒ every leg returns the writer's dry-run plan. The invoices / POS writers keep their own
# gates (INVOICE_WRITER_ENABLED / POS_WRITER_ENABLED) as a second, independent lock.
REPLACEMENT_POSTING_ENABLED = config('REPLACEMENT_POSTING_ENABLED', default=False, cast=bool)
if len(sys.argv) > 1 and sys.argv[1] == 'test':
    REPLACEMENT_POSTING_ENABLED = False

# ── Market-shortage SOFTECH writeback (items.itemmodified=صنف نواقص, itemcode_alt2=تحذير) ──
# Kill-switch: keep False until validated on the demo item; confirm/revert then stays
# LOCAL (queued) and the retry job pushes when SOFTECH is reachable.
SHORTAGE_SOFTECH_WRITE_ENABLED = config('SHORTAGE_SOFTECH_WRITE_ENABLED', default=False, cast=bool)
SHORTAGE_WARNING_TEXT = config('SHORTAGE_WARNING_TEXT', default='صنف ناقص جدا بالسوق المصري!!!')

# ── Phantom substitution (مبيعات وهمية) detector ─────────────────────────────
# Flag items whose "sales" are mostly patient buy-backs (bought from internal
# buy-back accounts, re-sold on contract) — over-ordered by the demand sheet.
# STRONG = ratio ≥ 0.50; WATCH = ratio ≥ 0.30 with ≥100 buyback units (massively-
# sold items). Detector runs inline in the engine run unless disabled here.
PHANTOM_FLAG_THRESHOLD    = config('PHANTOM_FLAG_THRESHOLD',    default=0.50, cast=float)
PHANTOM_WATCH_THRESHOLD   = config('PHANTOM_WATCH_THRESHOLD',   default=0.30, cast=float)
PHANTOM_WATCH_MIN_BUYBACK = config('PHANTOM_WATCH_MIN_BUYBACK', default=100,  cast=float)
PHANTOM_SCAN_IN_ENGINE_RUN = config('PHANTOM_SCAN_IN_ENGINE_RUN', default=True, cast=bool)
# Order-qty reduction is DORMANT by default — flag/monitor only. When enabled (or
# passed per engine run), the recommended qty is scaled by the order-% but kept
# above a small genuine cushion (SAFETY_FLOOR_WEEKS × weekly genuine demand).
PHANTOM_APPLY_REDUCTION   = config('PHANTOM_APPLY_REDUCTION',   default=False, cast=bool)
PHANTOM_SAFETY_FLOOR_WEEKS = config('PHANTOM_SAFETY_FLOOR_WEEKS', default=1.0, cast=float)
# 'strong' (ease-in default) → reduce STRONG-tier only; WATCH stays monitor-only.
# 'all' → reduce both tiers. Overridable per run via phantom_reduce_tier.
PHANTOM_REDUCE_TIER       = config('PHANTOM_REDUCE_TIER',       default='strong')

# ── Cash & inventory optimization (docs/architecture/22) ─────────────────────
# 📈 Demand-spike over-purchase: recent=qty_90d/3, prior=(qty_365d−qty_90d)/9.
# STRONG = new-burst (prior<0.15) OR recent/prior≥10× (cap-eligible); WATCH = 6–10×.
# The order cap is REVIEW-GATED (item.spike_confirmed) AND opt-in per run — cut to
# CAP_MONTHS of coverage at the recent rate only when both hold.
CASH_SPIKE_MIN_RECENT      = config('CASH_SPIKE_MIN_RECENT',      default=5.0,  cast=float)
CASH_SPIKE_STRONG_RATIO    = config('CASH_SPIKE_STRONG_RATIO',    default=10.0, cast=float)
CASH_SPIKE_WATCH_RATIO     = config('CASH_SPIKE_WATCH_RATIO',     default=6.0,  cast=float)
CASH_SPIKE_NEW_BURST_PRIOR = config('CASH_SPIKE_NEW_BURST_PRIOR', default=0.15, cast=float)
CASH_SPIKE_CAP_MONTHS      = config('CASH_SPIKE_CAP_MONTHS',      default=1.0,  cast=float)
CASH_SPIKE_DETECT_IN_ENGINE_RUN = config('CASH_SPIKE_DETECT_IN_ENGINE_RUN', default=True, cast=bool)
CASH_APPLY_SPIKE_CAP       = config('CASH_APPLY_SPIKE_CAP',       default=False, cast=bool)
INVOICE_RETURN_REASON_CODE = config('INVOICE_RETURN_REASON_CODE', default='4')  # docnumber2 on a 120 doc
# Write confirmed vendor_item_code → SOFTECH itemssuppliers.suppitemcode (trigger-free
# master data). Default off; enables first-invoice code→item resolution once seeded.
INVOICE_SUPPLIER_ITEM_WRITE_ENABLED = config('INVOICE_SUPPLIER_ITEM_WRITE_ENABLED', default=False, cast=bool)

# Kill-switch for the insurance receipt re-price writeback (edits stktrans/stktransm/
# branchesales on HQ + branch so a reprinted receipt matches a re-priced claim).
# HIGHEST-RISK write; keep False until validated live on one receipt. Even when True,
# every apply is per-receipt, confirm-gated, draft-only, and blocked if the branch
# node is unreachable. See docs/architecture/21_SOFTECH_INSURANCE_REPRICE_WRITEBACK.md.
INSURANCE_SOFTECH_WRITE_ENABLED = config('INSURANCE_SOFTECH_WRITE_ENABLED', default=False, cast=bool)

# ── Switches read from .env (same defaults as the code's getattr fallbacks) ─────
# Gift-coupon POS guard (apps/vouchers/coupon_guard.py) — off until verified with the guard-test panel.
COUPON_POS_GUARD_ENABLED          = config('COUPON_POS_GUARD_ENABLED', default=False, cast=bool)
COUPON_GUARD_REQUIRE_ISSUED       = config('COUPON_GUARD_REQUIRE_ISSUED', default=True, cast=bool)
COUPON_GUARD_REQUIRE_OWNER        = config('COUPON_GUARD_REQUIRE_OWNER', default=True, cast=bool)
COUPON_GUARD_REQUIRE_BRANCH_STOCK = config('COUPON_GUARD_REQUIRE_BRANCH_STOCK', default=True, cast=bool)
# WhatsApp refill reminders (apps/followups/refill_reminders.py, doc 26) — sending off by default.
REFILL_REMINDER_SEND_ENABLED = config('REFILL_REMINDER_SEND_ENABLED', default=False, cast=bool)
REFILL_REMINDER_TEMPLATE     = config('REFILL_REMINDER_TEMPLATE', default='refill_reminder')
REFILL_REMINDER_LANGUAGE     = config('REFILL_REMINDER_LANGUAGE', default='ar')
REFILL_REMINDER_DAILY_CAP    = config('REFILL_REMINDER_DAILY_CAP', default=300, cast=int)
# بدل الروشتة daily read-only check (apps/sync/tasks._run_replacement_check).
REPLACEMENT_DAILY_CHECK_ENABLED = config('REPLACEMENT_DAILY_CHECK_ENABLED', default=True, cast=bool)
REPLACEMENT_DAILY_CHECK_DAYS    = config('REPLACEMENT_DAILY_CHECK_DAYS', default=60, cast=int)
# B7 customer account state (doc 27): daily HQ vs branch check (read-only) and the branch-copy writer.
CUSTOMER_STATUS_DRIFT_CHECK_ENABLED = config('CUSTOMER_STATUS_DRIFT_CHECK_ENABLED', default=True, cast=bool)
CUSTOMER_BRANCH_COPY_WRITE_ENABLED  = config('CUSTOMER_BRANCH_COPY_WRITE_ENABLED', default=False, cast=bool)
CUSTOMER_BRANCH_COPY_MAX_PER_RUN    = config('CUSTOMER_BRANCH_COPY_MAX_PER_RUN', default=1, cast=int)
CUSTOMER_BRANCH_COPY_BATCH_MAX      = config('CUSTOMER_BRANCH_COPY_BATCH_MAX', default=50, cast=int)
CUSTOMER_BRANCH_COPY_HOLD           = config('CUSTOMER_BRANCH_COPY_HOLD', default='07HD11663')  # never batch-copied
# B7 Option B — points flag off + balance cleared at HQ (apps/customers/points_removal.py). Off by default.
POINTS_REMOVAL_WRITE_ENABLED = config('POINTS_REMOVAL_WRITE_ENABLED', default=False, cast=bool)
POINTS_REMOVAL_BATCH_MAX     = config('POINTS_REMOVAL_BATCH_MAX', default=50, cast=int)
# B7 duplicate-code merge queue (apps/customers/duplicates.py) — weekly READ-ONLY rebuild; review roles
# (maker-checker: the one who marks a pair cannot approve it).
CUSTOMER_MERGE_QUEUE_ENABLED = config('CUSTOMER_MERGE_QUEUE_ENABLED', default=True, cast=bool)

# Stock Transactions Audit (apps/stock_audit, doc 32). Read-only stktrans mirror from HQ:
# every 2 h replaces the last 3 docdate days; 03:15 catch-up replaces 7 days and prunes.
STOCK_AUDIT_ENABLED     = config('STOCK_AUDIT_ENABLED', default=True, cast=bool)
STOCK_AUDIT_WINDOW_DAYS = config('STOCK_AUDIT_WINDOW_DAYS', default=365, cast=int)

# Gamification (apps/gamification) — points / levels / badges / rankings, recognition only.
# Scheduler scores today every 30 min and closes yesterday at 00:20. Reads our tables only.
GAMIFICATION_ENABLED = config('GAMIFICATION_ENABLED', default=True, cast=bool)
# Monthly champions: a branch × role group needs this many players to crown a champion;
# branch of the month needs this many active players.
GAMIFICATION_CHAMPION_MIN_PLAYERS = config('GAMIFICATION_CHAMPION_MIN_PLAYERS', default=2, cast=int)
GAMIFICATION_BRANCH_OF_MONTH_MIN_PLAYERS = config('GAMIFICATION_BRANCH_OF_MONTH_MIN_PLAYERS', default=3, cast=int)
# Roles that never compete for a monthly title (management).
GAMIFICATION_CHAMPION_EXCLUDED_ROLES = config('GAMIFICATION_CHAMPION_EXCLUDED_ROLES', default='admin,viewer',
                                              cast=lambda v: [r.strip() for r in v.split(',') if r.strip()])
CUSTOMER_MERGE_ROLES         = ['admin', 'supervisor', 'call_center']
# B7 merge part 2 — approved pairs merged at HQ (apps/customers/merge_write.py). Off by default (dry run).
CUSTOMER_MERGE_WRITE_ENABLED = config('CUSTOMER_MERGE_WRITE_ENABLED', default=False, cast=bool)
CUSTOMER_MERGE_BATCH_MAX     = config('CUSTOMER_MERGE_BATCH_MAX', default=20, cast=int)

# ── Supplier-invoice save-time validations (replicate SofTech; apps/invoices/validations.py) ──
INVOICE_MAX_COST_INCREASE_PCT = config('INVOICE_MAX_COST_INCREASE_PCT', default=25, cast=float)  # W2 price spike
INVOICE_MAX_COST_DECREASE_PCT = config('INVOICE_MAX_COST_DECREASE_PCT', default=40, cast=float)  # W3 price drop
INVOICE_HIGH_DISCOUNT_PCT     = config('INVOICE_HIGH_DISCOUNT_PCT', default=50, cast=float)       # W6
INVOICE_ENFORCE_CREDIT_LIMIT  = config('INVOICE_ENFORCE_CREDIT_LIMIT', default=True, cast=bool)   # E8

# ── SOFTECH Connector profiles ────────────────────────────────────────────────
# Used by config.sybase.SoftechConnector when profile-specific hosts are set.
# Falls back to SYBASE_HOST / SYBASE_PORT when these are absent.
SOFTECH_PROFILE    = config('SOFTECH_PROFILE', default='prod')
SOFTECH_DEV_HOST   = config('SOFTECH_DEV_HOST', default='')
SOFTECH_DEV_PORT   = config('SOFTECH_DEV_PORT', default='5000')
SOFTECH_TEST_HOST  = config('SOFTECH_TEST_HOST', default='')
SOFTECH_TEST_PORT  = config('SOFTECH_TEST_PORT', default='5000')
SOFTECH_PROD_HOST  = config('SOFTECH_PROD_HOST', default='')
SOFTECH_PROD_PORT  = config('SOFTECH_PROD_PORT', default='5000')

# ── WhatsApp Business Platform ────────────────────────────────────────────────
WHATSAPP_TOKEN           = config('WHATSAPP_TOKEN', default='')
WHATSAPP_PHONE_NUMBER_ID = config('WHATSAPP_PHONE_NUMBER_ID', default='')
WHATSAPP_APP_SECRET      = config('WHATSAPP_APP_SECRET', default='')
WHATSAPP_VERIFY_TOKEN    = config('WHATSAPP_VERIFY_TOKEN', default='')
WHATSAPP_API_VERSION     = config('WHATSAPP_API_VERSION', default='v19.0')

# ── Omni (CEP) ────────────────────────────────────────────────────────────────
# Fernet key for ChannelAccount credential encryption (doc 15 §2.6).
# Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Falls back to a SECRET_KEY-derived key when empty (dev only).
OMNI_CREDENTIALS_KEY     = config('OMNI_CREDENTIALS_KEY', default='')
# Meta Graph webhook (Messenger + Instagram share one endpoint — doc 15 Phase 3)
META_GRAPH_VERIFY_TOKEN  = config('META_GRAPH_VERIFY_TOKEN', default='')
META_GRAPH_APP_SECRET    = config('META_GRAPH_APP_SECRET', default='')

# ── Issabel PBX / Asterisk AMI ────────────────────────────────────────────────
# Supervisor ChanSpy (listen/whisper) — doc 15 Phase 2
AMI_SPY_CONTEXT  = config('AMI_SPY_CONTEXT', default='from-internal')
AMI_CHANNEL_TECH = config('AMI_CHANNEL_TECH', default='SIP')
# Call recordings: local mount of the Asterisk monitor dir, and/or an HTTP
# base URL where Issabel serves recordings. Either enables timeline playback.
PBX_RECORDINGS_DIR      = config('PBX_RECORDINGS_DIR', default='')
PBX_RECORDINGS_URL_BASE = config('PBX_RECORDINGS_URL_BASE', default='')
AMI_HOST   = config('AMI_HOST', default='127.0.0.1')
AMI_PORT   = config('AMI_PORT', default=5038, cast=int)
AMI_USER   = config('AMI_USER', default='')
AMI_SECRET = config('AMI_SECRET', default='')
AMI_DIAL_CONTEXT = config('AMI_DIAL_CONTEXT', default='')
# Recordings over SFTP (read-only download of single files from the monitor dir)
PBX_RECORDINGS_ROOT          = config('PBX_RECORDINGS_ROOT', default='/var/spool/asterisk/monitor')
PBX_RECORDINGS_SFTP_HOST     = config('PBX_RECORDINGS_SFTP_HOST', default='')
PBX_RECORDINGS_SFTP_PORT     = config('PBX_RECORDINGS_SFTP_PORT', default=22, cast=int)
PBX_RECORDINGS_SFTP_USER     = config('PBX_RECORDINGS_SFTP_USER', default='')
PBX_RECORDINGS_SFTP_PASSWORD = config('PBX_RECORDINGS_SFTP_PASSWORD', default='')
PBX_RECORDINGS_SFTP_KEY_FILE = config('PBX_RECORDINGS_SFTP_KEY_FILE', default='')

# ── Call transcription ────────────────────────────────────────────────────────
CALLCENTER_AUTO_TRANSCRIBE             = config('CALLCENTER_AUTO_TRANSCRIBE', default=False, cast=bool)
CALLCENTER_AUTO_TRANSCRIBE_MIN_SECONDS = config('CALLCENTER_AUTO_TRANSCRIBE_MIN_SECONDS', default=20, cast=int)
WHISPER_ENABLED     = config('WHISPER_ENABLED', default=False, cast=bool)
WHISPER_MIN_SECONDS = config('WHISPER_MIN_SECONDS', default=20, cast=int)
WHISPER_MODEL_DIR   = config('WHISPER_MODEL_DIR', default='')
WHISPER_EXTRA_TERMS = [t.strip() for t in config('WHISPER_EXTRA_TERMS', default='').split(',') if t.strip()]

# ── Frontend base URL ─────────────────────────────────────────────────────────
FRONTEND_BASE_URL = config('FRONTEND_BASE_URL', default='https://app.elrezeiky.com')

# ── Web Push (VAPID) ──────────────────────────────────────────────────────────
# Powers browser push notifications so the in-app bell stays "alive" when the
# tab/app is closed. Generate a key pair once with:
#   python -c "from py_vapid import Vapid01; v=Vapid01(); v.generate_keys(); \
#       import base64; \
#       print('PUBLIC ', base64.urlsafe_b64encode(v.public_key.public_bytes(... )))"
# or the simpler `vapid --gen` / web-push CLI. Both keys are base64url strings.
# Leave empty to disable Web Push entirely (send_web_push() then no-ops).
# NOTE: iOS delivers Web Push only to an INSTALLED PWA (Safari 16.4+).
WEBPUSH_VAPID_PUBLIC_KEY  = config('WEBPUSH_VAPID_PUBLIC_KEY',  default='')
WEBPUSH_VAPID_PRIVATE_KEY = config('WEBPUSH_VAPID_PRIVATE_KEY', default='')
WEBPUSH_VAPID_ADMIN_EMAIL = config('WEBPUSH_VAPID_ADMIN_EMAIL', default='')

# ── Scheduler ─────────────────────────────────────────────────────────────────
# True  → the web process auto-starts APScheduler (legacy single-process mode).
# False → run it separately via `python manage.py run_scheduler`.
# Either way the scheduler writes a heartbeat that /api/sync/scheduler-status/
# reports, so the UI can warn if jobs aren't running.
SCHEDULER_AUTOSTART = config('SCHEDULER_AUTOSTART', default=False, cast=bool)

# ── AI Enrichment — Multi-provider fallback chain ─────────────────────────────
# The enrichment pipeline tries providers in order; first non-empty result wins.
# Configure keys in your .env file (or environment variables).
#
# Provider 1 — Gemini primary account (https://aistudio.google.com/)
GEMINI_API_KEY = config('GEMINI_API_KEY',  default='')
GEMINI_MODEL   = config('GEMINI_MODEL',    default='gemini-2.5-flash')
# In-house fine-tuned OCR model (P3): a directory of a saved Donut/VisionEncoderDecoder
# model. Empty = no in-house engine (run_engines skips it). Set after training on a GPU box.
INHOUSE_OCR_MODEL_DIR = config('INHOUSE_OCR_MODEL_DIR', default='')
GEMINI_RPM     = config('GEMINI_RPM',      default=10, cast=float)   # free tier: 10 RPM
#
# Provider 2 — Gemini secondary account (second Google account / Gemini Pro)
GEMINI_API_KEY_2 = config('GEMINI_API_KEY_2', default='')
GEMINI_MODEL_2   = config('GEMINI_MODEL_2',   default='gemini-2.5-flash')
#
# Mistral vision OCR (paid; never hits the Gemini free-tier daily cap). Registered
# as the 'mistral' engine; active only when this key is set + `mistralai` installed.
MISTRAL_API_KEY  = config('MISTRAL_API_KEY',  default='')
MISTRAL_OCR_MODEL = config('MISTRAL_OCR_MODEL', default='pixtral-12b-latest')
#
# Generic self-hosted / OpenAI-compatible VLM OCR endpoint. Point this at a served
# vision model (PaddleOCR-VL, Qwen2.5-VL, Nanonets-OCR2, …) via vLLM / Ollama / HF
# TGI / any /v1/chat/completions server, and it registers as the 'vlm' engine for
# A/B in the benchmark (--engine vlm). Empty URL = engine disabled.
VLM_OCR_URL      = config('VLM_OCR_URL',   default='')     # e.g. http://gpu-box:8000/v1/chat/completions
VLM_OCR_MODEL    = config('VLM_OCR_MODEL', default='')     # the served model id
VLM_OCR_KEY      = config('VLM_OCR_KEY',   default='')     # bearer token if the server needs one
#
# PaddleOCR box sidecar — PaddlePaddle has NO Python 3.14 wheel, so PaddleOCR
# PP-OCRv5 runs in a SEPARATE Python ≤3.12 venv as a tiny local HTTP server
# (see ocr_sidecar/). Set this URL and the `paddleocr` engine reads boxes from it
# and feeds them through the SAME band/template pipeline as Tesseract. Empty = the
# in-process paddleocr is used instead (only works where paddlepaddle is installable).
PADDLE_OCR_URL   = config('PADDLE_OCR_URL', default='')     # e.g. http://127.0.0.1:8077/boxes
#
# Provider 3 — OpenAI fallback (https://platform.openai.com/api-keys)
OPENAI_API_KEY = config('OPENAI_API_KEY', default='')
OPENAI_MODEL   = config('OPENAI_MODEL',   default='gpt-4o-mini')
OPENAI_RPM     = config('OPENAI_RPM',     default=3, cast=float)    # free tier: 3 RPM


MIDDLEWARE += [
    'core.middleware.db_cleanup.CloseConnectionsMiddleware',
    # Stores current StaffProfile in thread-local for serializer audit helpers
    'apps.users.middleware.CurrentUserMiddleware',
    # Server-side RoleModuleAccess check for /api/<module>/ (see core/middleware/module_access.py)
    'core.middleware.module_access.ModuleAccessMiddleware',
]

# off | log | enforce — roll out as: log in production, clean up the matrix until the
# "elrezeiky.rbac" log is quiet, then enforce. The test runner defaults to off so
# existing endpoint tests keep exercising view-level permissions only.
RBAC_ENFORCEMENT = config('RBAC_ENFORCEMENT', default='off' if _RUNNING_TESTS else 'log')
# Seconds the role matrix is cached per process; 0 under tests so no test sees another's rows.
RBAC_GRANTS_TTL = config('RBAC_GRANTS_TTL', default=0 if _RUNNING_TESTS else 60, cast=float)
