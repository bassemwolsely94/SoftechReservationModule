"""
Settings for the Playwright browser tests (frontend/e2e, test plan R8).

    DJANGO_SETTINGS_MODULE=config.settings_e2e python manage.py migrate
    DJANGO_SETTINGS_MODULE=config.settings_e2e python manage.py seed_e2e_users
    DJANGO_SETTINGS_MODULE=config.settings_e2e python manage.py runserver 127.0.0.1:8000

What this file guarantees, whatever the developer's .env says:
  * The dev .env is NEVER read. python-decouple normally walks up from config/ and finds the
    repository .env (on the office laptop that is the WRITER copy). Here decouple is pointed at
    an empty repository before config.settings is imported, so every value is either a process
    environment variable or the code default.
  * A reader copy: SOFTECH_READ_ONLY=True, WRITER_INSTANCE=False, no SOFTECH host at all, every
    branch-server connection sent to an unresolvable name, every SOFTECH writer switch off.
  * Its own database (E2E_PG_NAME, default `elrezeiky_e2e`), never the dev `elrezeiky_db`.
  * No outbound sends: no WhatsApp / SMS / Web Push / e-mail / PBX / AI-OCR credentials, every
    message switch off, the scheduler never starts.

The e2e test users and their passwords live in E2E_USERS below (test-only values for a throwaway
database; `seed_e2e_users` refuses to run under any other settings module).
"""
import os

import decouple

# ── 1. never read the dev .env ────────────────────────────────────────────────
decouple.config = decouple.Config(decouple.RepositoryEmpty())

# The database comes from E2E_PG_* (CI: the postgres service; local: your own postgres login).
os.environ['PG_NAME'] = os.environ.get('E2E_PG_NAME', 'elrezeiky_e2e')
for _k in ('USER', 'PASSWORD', 'HOST', 'PORT'):
    if f'E2E_PG_{_k}' in os.environ:
        os.environ[f'PG_{_k}'] = os.environ[f'E2E_PG_{_k}']

os.environ.setdefault('DEBUG', 'True')
os.environ.setdefault('SECRET_KEY', 'e2e-only-not-a-secret-' + 'x' * 32)
# A SOFTECH host must never come from the process environment either.
for _k in ('SYBASE_HOST', 'SOFTECH_DEV_HOST', 'SOFTECH_TEST_HOST', 'SOFTECH_PROD_HOST',
           'SOFTECH_BRANCH_HOST_OVERRIDE', 'WRITER_INSTANCE', 'SOFTECH_READ_ONLY'):
    os.environ.pop(_k, None)

from config.settings import *  # noqa: E402,F401,F403 — this module extends the real settings
from config import settings as _base  # noqa: E402

if _base._RUNNING_TESTS:  # pragma: no cover — guard against `manage.py test --settings=…e2e`
    raise RuntimeError('config.settings_e2e is for the browser tests only; use config.settings for manage.py test')

E2E_SETTINGS = True

# ── 2. reader copy, no SOFTECH ────────────────────────────────────────────────
WRITER_INSTANCE = False
SOFTECH_READ_ONLY = True
SYBASE_HOST = ''
SOFTECH_DEV_HOST = SOFTECH_TEST_HOST = SOFTECH_PROD_HOST = ''
SOFTECH_BRANCH_HOST_OVERRIDE = 'softech-disabled-in-e2e.invalid'
SOFTECH_PROBES_ENABLED = False
SCHEDULER_AUTOSTART = False

# Every SOFTECH writer / posting / message switch off (they already default off; this pins them
# so a process environment variable cannot turn one on).
for _name in [n for n in dir(_base) if n.isupper()]:
    if _name.endswith(('_WRITE_ENABLED', '_WRITER_ENABLED', '_POSTING_ENABLED', '_SEND_ENABLED',
                       '_AUTO_APPROVE', '_AUTO_APPROVE_ENABLED', '_AUTO_TOPUP_ENABLED')):
        globals()[_name] = False
from config.writers import WRITER_FLAGS  # noqa: E402 — only reads django.conf lazily

for _name in WRITER_FLAGS:
    globals()[_name] = False
POS_WRITER_ENABLED = False
POS_CANCEL_WRITE_ENABLED = False
INVOICE_WRITER_ENABLED = False
REPLACEMENT_POSTING_ENABLED = False

# ── 3. its own database ───────────────────────────────────────────────────────
DATABASES['default']['NAME'] = os.environ['PG_NAME']  # noqa: F405
DATABASES['audit_log'] = {**DATABASES['default'], 'TEST': {'MIRROR': 'default'}}  # noqa: F405
if DATABASES['default']['NAME'] == 'elrezeiky_db':  # noqa: F405
    raise RuntimeError('config.settings_e2e must not use the dev database elrezeiky_db')

# ── 4. no outbound sends ──────────────────────────────────────────────────────
WHATSAPP_TOKEN = WHATSAPP_PHONE_NUMBER_ID = WHATSAPP_APP_SECRET = ''
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

# ── 5. the e2e users (test-only credentials, one per role) ────────────────────
# Read by `seed_e2e_users` and by frontend/e2e (through E2E_USERS_JSON, which the
# Playwright config builds from frontend/e2e/users.js — the same values).
E2E_PASSWORD = 'E2e-Only-Pass-7351'
E2E_ROLES = ['admin', 'call_center', 'pharmacist', 'salesperson', 'purchasing', 'delivery',
             'viewer', 'supervisor', 'quality_manager', 'accountant']
E2E_USERS = {role: f'e2e_{role}' for role in E2E_ROLES}
# Minimal fixtures for the flows (reservation, transfer, POS): two operational test branches
# (the users sit in the first) and two catalog items. Codes that no real SOFTECH row uses.
E2E_GL_ACCOUNTS = [
    ('E2E النقدية', 'balance_sheet', '9901', 'E2E الخزينة', 'debit', 'asset'),
    ('E2E الايرادات', 'pl', '9902', 'E2E المبيعات', 'credit', 'revenue'),
]
E2E_BRANCHES = [
    {'softech_branch_id': '991', 'code': 'E91', 'name': 'فرع الاختبار ١'},
    {'softech_branch_id': '992', 'code': 'E92', 'name': 'فرع الاختبار ٢'},
]
E2E_ITEMS = [
    {'softech_id': 'E2E001', 'name': 'E2E PARACETAMOL 500MG 20 TAB', 'pack_price': '25.00', 'unit_price': '12.50'},
    {'softech_id': 'E2E002', 'name': 'E2E VITAMIN C 1000MG 10 TAB', 'pack_price': '40.00', 'unit_price': '40.00'},
]
# POS ready uses the offline price (no SOFTECH read); it is the default, pinned here.
POS_LIVE_PRICING = False

# ── 6. its own log file (never the dev platform.log) ──────────────────────────
os.makedirs(BASE_DIR / 'logs', exist_ok=True)  # noqa: F405
LOGGING['handlers']['file']['filename'] = BASE_DIR / 'logs' / 'e2e.log'  # noqa: F405
