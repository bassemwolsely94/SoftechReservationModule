"""
Self-hosted guard for the public (anonymous) forms (security N6, Task 2).

No third-party CAPTCHA or script. A public form first fetches a challenge
(GET /api/public/challenge/?form=...): a signed {id, form, iat}. The browser
(frontend/src/utils/publicGuard.js) searches for a nonce such that
sha256(f'{challenge}:{nonce}') starts with PUBLIC_POW_DIFFICULTY zero bits, then
submits challenge + nonce with the form. check_submission() then refuses:

  bot          the hidden honeypot field `website` was filled
  expired      no / tampered challenge, or older than PUBLIC_POW_TTL_SECONDS
  wrong_form   the challenge was issued for another form
  too_fast     submitted under PUBLIC_MIN_FILL_SECONDS after the challenge was issued
  bad_solution the nonce does not give enough leading zero bits
  replayed     the challenge was already used once
  phone_limit  this phone already sent its daily cap of this form today (Cairo day):
               'notify' PUBLIC_NOTIFY_DAILY_MAX (default 10 - shelf-QR customers scan several
               items), 'portal_link' PUBLIC_PHONE_DAILY_MAX (default 3)

'bot' and 'phone_limit' must look like success to the caller's client: callers return
their normal success response for those two codes and log one INFO line.
"""
import hashlib
import logging
import re
import time
import uuid

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger('elrezeiky.public_guard')

SALT = 'public-pow'
HONEYPOT_FIELD = 'website'
FORMS = ('notify', 'portal_link')
NONCE_MAX_LEN = 32

PUBLIC_OK_MESSAGE = 'تم استلام طلبك بنجاح'

GUARD_MESSAGES = {
    'bot': PUBLIC_OK_MESSAGE,
    'phone_limit': PUBLIC_OK_MESSAGE,
    'expired': 'انتهت صلاحية الصفحة، حدّث الصفحة وحاول مرة أخرى',
    'replayed': 'تم إرسال هذا الطلب من قبل، حدّث الصفحة وحاول مرة أخرى',
    'too_fast': 'تم الإرسال بسرعة كبيرة، انتظر لحظات وحاول مرة أخرى',
    'bad_solution': 'تعذّر التحقق من الطلب، حدّث الصفحة وحاول مرة أخرى',
    'wrong_form': 'تعذّر التحقق من الطلب، حدّث الصفحة وحاول مرة أخرى',
}

# Codes the caller answers with its normal success response (no signal to a bot).
SILENT_CODES = frozenset({'bot', 'phone_limit'})


class GuardError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code
        self.message = GUARD_MESSAGES[code]


def _ttl() -> int:
    return int(settings.PUBLIC_POW_TTL_SECONDS)


def leading_zero_bits(digest: bytes) -> int:
    """Leading zero bits of a digest, most significant bit of the first byte first."""
    n = 0
    for b in digest:
        if b == 0:
            n += 8
            continue
        return n + 8 - b.bit_length()
    return n


def issue_challenge(form: str) -> dict:
    payload = {'id': uuid.uuid4().hex, 'form': form, 'iat': int(time.time())}
    return {'challenge': signing.dumps(payload, salt=SALT),
            'difficulty': int(settings.PUBLIC_POW_DIFFICULTY)}


def normalize_phone(phone) -> str:
    """One counter key per Egyptian number however it was typed: digits only, a 20 / 0020
    country prefix on a 12-digit number becomes a leading 0, then the last 11 digits."""
    digits = re.sub(r'\D', '', str(phone or ''))
    if digits.startswith('0020'):
        digits = digits[2:]
    if len(digits) == 12 and digits.startswith('20'):
        digits = '0' + digits[2:]
    return digits[-11:]


def daily_max(form: str) -> int:
    if form == 'notify':
        return int(getattr(settings, 'PUBLIC_NOTIFY_DAILY_MAX', 10))
    return int(settings.PUBLIC_PHONE_DAILY_MAX)


def _phone_key(form: str, phone: str) -> str:
    return f'public:phone:{form}:{phone}:{timezone.localdate():%Y%m%d}'


def _masked(phone) -> str:
    digits = normalize_phone(phone)
    return f'***{digits[-4:]}' if digits else '-'


def check_submission(data: dict, form: str, phone: str | None = None) -> None:
    """Raise GuardError(code) unless the submission passes every check (see module docstring).
    Every refusal is logged once at INFO with its real code, even where the user sees success."""
    try:
        _check(data, form, phone)
    except GuardError as e:
        logger.info('public guard refused code=%s form=%s phone=%s', e.code, form, _masked(phone))
        raise


def _check(data: dict, form: str, phone) -> None:
    if str(data.get(HONEYPOT_FIELD) or '').strip():
        raise GuardError('bot')

    challenge = data.get('challenge')
    if not isinstance(challenge, str) or not challenge:
        raise GuardError('expired')
    try:
        payload = signing.loads(challenge, salt=SALT)
        pid, pform, iat = payload['id'], payload['form'], int(payload['iat'])
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        raise GuardError('expired')
    now = time.time()
    if now - iat > _ttl():
        raise GuardError('expired')
    if pform != form:
        raise GuardError('wrong_form')
    if now - iat < int(settings.PUBLIC_MIN_FILL_SECONDS):
        raise GuardError('too_fast')

    nonce = data.get('nonce')
    nonce = '' if nonce is None else str(nonce)
    if not nonce or len(nonce) > NONCE_MAX_LEN:
        raise GuardError('bad_solution')
    digest = hashlib.sha256(f'{challenge}:{nonce}'.encode()).digest()
    if leading_zero_bits(digest) < int(settings.PUBLIC_POW_DIFFICULTY):
        raise GuardError('bad_solution')

    if not cache.add(f'public:pow:{pid}', 1, _ttl()):
        raise GuardError('replayed')

    phone = normalize_phone(phone)
    if phone:
        key = _phone_key(form, phone)
        if (cache.get(key) or 0) >= daily_max(form):
            raise GuardError('phone_limit')
        if cache.add(key, 1, 86400 + 3600):   # outlives the Cairo day the key names
            return
        try:
            cache.incr(key)
        except ValueError:                     # expired between get and incr
            cache.add(key, 1, 86400 + 3600)
