"""
Settings for the role-by-role UAT on a restored copy of production data
(docs/superpowers/specs/2026-11-16-role-uat-design.md).

    . scripts/uat/uat-env.ps1          # sets UAT_PG_* from the dev .env's database login only
    python manage.py runserver 127.0.0.1:8200 --settings=config.settings_uat

What this file guarantees, whatever the developer's .env or process environment says:
  * The dev .env is NEVER read (it is the live SOFTECH writer on the office PC). The database
    login comes from UAT_PG_* process variables only.
  * A reader copy: SOFTECH_READ_ONLY=True, WRITER_INSTANCE=False, no SOFTECH host, every branch
    connection sent to an unresolvable name, every writer / posting / send switch off.
  * Only a UAT database (name starts with `elrezeiky_uat`); anything else refuses to start.
  * No outbound sends: no WhatsApp / SMS / Web Push / e-mail / PBX / AI-OCR / tax credentials,
    the scheduler never starts.
  * RBAC_ENFORCEMENT=enforce — what production uses from cutover day.
  * The login throttle is raised so ~40 UAT users can sign in back to back.
"""
import os

import decouple

# ── 1. never read the dev .env ───────────────────────────────────────────────
decouple.config = decouple.Config(decouple.RepositoryEmpty())

_DB = os.environ.get('UAT_PG_NAME', 'elrezeiky_uat')
if not _DB.startswith('elrezeiky_uat'):
    raise RuntimeError(f'config.settings_uat must not use database {_DB!r}; only elrezeiky_uat*')
os.environ['PG_NAME'] = _DB
for _k in ('USER', 'PASSWORD', 'HOST', 'PORT'):
    os.environ.pop(f'PG_{_k}', None)
    if f'UAT_PG_{_k}' in os.environ:
        os.environ[f'PG_{_k}'] = os.environ[f'UAT_PG_{_k}']

os.environ.setdefault('DEBUG', 'True')
# Never the office keys: with them the restored channel credentials would decrypt (review 2026-11-17).
os.environ['SECRET_KEY'] = os.environ.get('UAT_SECRET_KEY') or 'uat-only-not-a-secret-' + 'x' * 32
os.environ.pop('OMNI_CREDENTIALS_KEY', None)
# Nothing that can reach SOFTECH or switch on a writer may come from the process environment.
for _k in list(os.environ):
    if _k.endswith(('_WRITE_ENABLED', '_WRITER_ENABLED', '_POSTING_ENABLED', '_SEND_ENABLED',
                    '_AUTO_APPROVE', '_AUTO_APPROVE_ENABLED', '_AUTO_TOPUP_ENABLED')):
        os.environ.pop(_k)
for _k in ('SYBASE_HOST', 'SOFTECH_DEV_HOST', 'SOFTECH_TEST_HOST', 'SOFTECH_PROD_HOST',
           'SOFTECH_BRANCH_HOST_OVERRIDE', 'WRITER_INSTANCE', 'SOFTECH_READ_ONLY',
           'WHATSAPP_TOKEN', 'AMI_HOST', 'RBAC_ENFORCEMENT', 'MISSED_CALL_CALLBACKS_ENABLED'):
    os.environ.pop(_k, None)

from config.settings import *  # noqa: E402,F401,F403 — this module extends the real settings
from config import settings as _base
from config.settings import BASE_DIR, DATABASES, LOGGING, MIDDLEWARE, REST_FRAMEWORK
from config.writers import WRITER_FLAGS  # only reads django.conf lazily

if _base._RUNNING_TESTS:  # pragma: no cover — guard against `manage.py test --settings=…uat`
    raise RuntimeError('config.settings_uat is for the UAT copy only; use config.settings for manage.py test')

UAT_SETTINGS = True

# ── 2. reader copy, no SOFTECH ───────────────────────────────────────────────
WRITER_INSTANCE = False
SOFTECH_READ_ONLY = True
SYBASE_HOST = ''
SOFTECH_DEV_HOST = SOFTECH_TEST_HOST = SOFTECH_PROD_HOST = ''
SOFTECH_BRANCH_HOST_OVERRIDE = 'softech-disabled-in-uat.invalid'
SOFTECH_PROBES_ENABLED = False
SCHEDULER_AUTOSTART = False

for _name in [n for n in dir(_base) if n.isupper()]:
    if _name.endswith(('_WRITE_ENABLED', '_WRITER_ENABLED', '_POSTING_ENABLED', '_SEND_ENABLED',
                       '_AUTO_APPROVE', '_AUTO_APPROVE_ENABLED', '_AUTO_TOPUP_ENABLED')):
        globals()[_name] = False

for _name in WRITER_FLAGS:
    globals()[_name] = False
POS_WRITER_ENABLED = False
POS_CANCEL_WRITE_ENABLED = False
INVOICE_WRITER_ENABLED = False
REPLACEMENT_POSTING_ENABLED = False
POS_LIVE_PRICING = False
POS_SERVER_CHECKOUT = False          # D-18: the UAT copy keeps today's POS checkout

# ── 3. its own database ──────────────────────────────────────────────────────
DATABASES['default']['NAME'] = _DB
DATABASES['audit_log'] = {**DATABASES['default'], 'TEST': {'MIRROR': 'default'}}

# ── 4. no outbound sends ─────────────────────────────────────────────────────
WHATSAPP_TOKEN = WHATSAPP_PHONE_NUMBER_ID = WHATSAPP_APP_SECRET = ''
OMNI_CREDENTIALS_KEY = ''          # stored channel credentials stay unreadable
MISSED_CALL_CALLBACKS_ENABLED = False
SMS_PROVIDER = SMS_HTTP_URL = ''
WEBPUSH_VAPID_PUBLIC_KEY = WEBPUSH_VAPID_PRIVATE_KEY = ''
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
AMI_HOST = ''
AMI_USER = AMI_SECRET = ''
PBX_RECORDINGS_SFTP_HOST = ''
GEMINI_API_KEY = GEMINI_API_KEY_2 = MISTRAL_API_KEY = OPENAI_API_KEY = ''
VLM_OCR_URL = PADDLE_OCR_URL = ''
CALLCENTER_AUTO_TRANSCRIBE = False
WHISPER_ENABLED = False
REDIS_URL = ''
CHANNEL_LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}

# ── 5. production-like access, many test logins ──────────────────────────────
RBAC_ENFORCEMENT = 'enforce'
REST_FRAMEWORK = {**REST_FRAMEWORK,
                  'DEFAULT_THROTTLE_RATES': {**REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'], 'login': '1000/min'}}

# ── 6. every response names the copy (frontend/uat/lib/guard.js checks it before any login) ──
MIDDLEWARE = [*MIDDLEWARE, 'config.uat_marker.UatCopyMarker']

# ── 7. its own log file ──────────────────────────────────────────────────────
os.makedirs(BASE_DIR / 'logs', exist_ok=True)
LOGGING['handlers']['file']['filename'] = BASE_DIR / 'logs' / 'uat.log'
