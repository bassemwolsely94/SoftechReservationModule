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

SECRET_KEY = config('SECRET_KEY', default='change-me-in-production-abc123xyz')
DEBUG = config('DEBUG', default=False, cast=bool)

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='*').split(',')

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
    'apps.personal',       # Personal dashboard — per-user SOFTECH identity claims + configurable widgets
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
    }
}

# ── REST FRAMEWORK ─────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
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
    'DEFAULT_THROTTLE_RATES': {
        'login': '10/min',   # max 10 login attempts per IP per minute
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

# ── INTERNATIONALISATION ──────────────────────────────────────────────────────
LANGUAGE_CODE = 'ar'
TIME_ZONE = 'Africa/Cairo'
USE_I18N = True
USE_TZ = True

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
INVOICE_WRITER_ENABLED  = config('INVOICE_WRITER_ENABLED', default=False, cast=bool)
INVOICE_WRITER_PROFILE  = config('INVOICE_WRITER_PROFILE', default='test')   # test|prod
INVOICE_DEFAULT_USERCODE = config('INVOICE_DEFAULT_USERCODE', default='')    # fallback buyer usercode
INVOICE_WRITE_CHARSET   = config('INVOICE_WRITE_CHARSET', default='cp1256')

# ── Market-shortage SOFTECH writeback (items.itemmodified=صنف نواقص, itemcode_alt2=تحذير) ──
# Kill-switch: keep False until validated on the demo item; confirm/revert then stays
# LOCAL (queued) and the retry job pushes when SOFTECH is reachable.
SHORTAGE_SOFTECH_WRITE_ENABLED = config('SHORTAGE_SOFTECH_WRITE_ENABLED', default=False, cast=bool)
SHORTAGE_WARNING_TEXT = config('SHORTAGE_WARNING_TEXT', default='صنف ناقص جدا بالسوق المصري!!!')
INVOICE_RETURN_REASON_CODE = config('INVOICE_RETURN_REASON_CODE', default='4')  # docnumber2 on a 120 doc
# Write confirmed vendor_item_code → SOFTECH itemssuppliers.suppitemcode (trigger-free
# master data). Default off; enables first-invoice code→item resolution once seeded.
INVOICE_SUPPLIER_ITEM_WRITE_ENABLED = config('INVOICE_SUPPLIER_ITEM_WRITE_ENABLED', default=False, cast=bool)

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
GEMINI_RPM     = config('GEMINI_RPM',      default=10, cast=float)   # free tier: 10 RPM
#
# Provider 2 — Gemini secondary account (second Google account / Gemini Pro)
GEMINI_API_KEY_2 = config('GEMINI_API_KEY_2', default='')
GEMINI_MODEL_2   = config('GEMINI_MODEL_2',   default='gemini-2.5-flash')
#
# Provider 3 — OpenAI fallback (https://platform.openai.com/api-keys)
OPENAI_API_KEY = config('OPENAI_API_KEY', default='')
OPENAI_MODEL   = config('OPENAI_MODEL',   default='gpt-4o-mini')
OPENAI_RPM     = config('OPENAI_RPM',     default=3, cast=float)    # free tier: 3 RPM


MIDDLEWARE += [
    'core.middleware.db_cleanup.CloseConnectionsMiddleware',
    # Stores current StaffProfile in thread-local for serializer audit helpers
    'apps.users.middleware.CurrentUserMiddleware',
]