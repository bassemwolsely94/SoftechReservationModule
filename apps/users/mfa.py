"""
Two-factor authentication (TOTP) for the ElRezeiky platform.

Approval-capable roles (MFA_REQUIRED_ROLES) must pass a TOTP check at login once
enforcement is switched on via the config SystemSetting `security.mfa_enforced`.
Until then enrollment is opt-in (grace period): a user who has enabled 2FA is
always challenged; everyone else logs in normally.

Login becomes two-step:
  1. POST /auth/login/        → if 2FA applies, returns {mfa_required|mfa_setup_required, mfa_token}
                                instead of {access, refresh}. mfa_token is a short-lived
                                signed pre-auth token that grants NO API access.
  2. POST /auth/2fa/verify/   → {mfa_token, code} → {access, refresh, user}

Enrollment (self-service from settings, or forced at login during enforcement):
  POST /auth/2fa/setup/   → {secret, otpauth_uri, qr_png}
  POST /auth/2fa/enable/  → {code} → confirms + returns one-time backup_codes
  POST /auth/2fa/disable/ → {password, code}
  GET  /auth/2fa/status/  → enrollment + enforcement state
"""
import base64
import hmac
import io
import secrets
import time

import pyotp
import qrcode
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.models import User
from django.core import signing
from django.core.cache import cache
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from .models import StaffProfile, MFA_REQUIRED_ROLES

ISSUER = 'ElRezeiky Pharmacy'

# Pre-auth token (between login step 1 and 2) — short TTL, no API access.
_PREAUTH_SALT = 'mfa-preauth'
_PREAUTH_MAX_AGE = 300          # 5 minutes
# Wrong codes allowed per login token; then the token is dead → log in again
# (Batch 3, A-2; owner 2026-10-27).
MAX_CODE_TRIES = 5
# "Remember this device" is the approved-device remember (apps/access/devices.py, N2); the old
# signed device_token kept in localStorage was removed in N3.


# ── Enforcement flag ───────────────────────────────────────────────────────────

def mfa_enforced() -> bool:
    """Read the admin-flippable enforcement toggle (default: off / grace period)."""
    try:
        from apps.config.models import SystemSetting
        s = SystemSetting.objects.filter(key='security.mfa_enforced').first()
        return bool(s.typed_value) if s else False
    except Exception:
        return False


def mfa_required_for(profile) -> bool:
    """True if this user's role is in scope AND enforcement is on."""
    return bool(profile) and profile.role in MFA_REQUIRED_ROLES and mfa_enforced()


# ── Signed tokens ────────────────────────────────────────────────────────────────

def make_preauth_token(user, purpose: str) -> str:
    # 'n' names this one login, so its wrong codes are counted and it opens one session (A-2).
    return signing.dumps({'uid': user.id, 'purpose': purpose, 'n': secrets.token_hex(8)},
                         salt=_PREAUTH_SALT)


def _read_preauth(token: str, purpose: str):
    """(User, login id) for a valid, unexpired pre-auth token of the given purpose, else (None, '')."""
    try:
        data = signing.loads(token, salt=_PREAUTH_SALT, max_age=_PREAUTH_MAX_AGE)
    except signing.BadSignature:
        return None, ''
    if data.get('purpose') != purpose:
        return None, ''
    return User.objects.filter(id=data.get('uid')).first(), str(data.get('n') or '')


def read_preauth_token(token: str, purpose: str):
    """Return the User for a valid, unexpired pre-auth token of the given purpose, else None."""
    return _read_preauth(token, purpose)[0]


def _device_fingerprint(user) -> str:
    """Changes whenever the password, the 2FA secret or the device epoch does, so a password
    change, an admin reset, a 2FA reset or "forget saved devices" cancels every "remember this
    device" (Batch 3, A-3; owner 2026-10-27; N0/H7)."""
    from django.utils.crypto import salted_hmac
    profile = getattr(user, 'staff_profile', None)
    material = (f'{user.password}|{getattr(profile, "mfa_secret", "") or ""}'
                f'|{getattr(profile, "mfa_device_epoch", 0) or 0}')
    return salted_hmac('mfa-device-fingerprint', material).hexdigest()[:24]


def forget_devices(profile, by_profile, ip) -> int:
    """Cancel every "remember this device" of `profile` (the epoch is part of the fingerprint the
    approved-device remember stores); returns the new epoch (N0/H7)."""
    from django.db.models import F
    from .models import UserActivityLog
    StaffProfile.objects.filter(pk=profile.pk).update(mfa_device_epoch=F('mfa_device_epoch') + 1)
    profile.refresh_from_db(fields=['mfa_device_epoch'])
    UserActivityLog.objects.create(target_user=profile, changed_by=by_profile,
                                   action='mfa_devices_forgotten', ip_address=ip,
                                   note='إلغاء الأجهزة المحفوظة')
    return profile.mfa_device_epoch


# ── TOTP + backup codes ──────────────────────────────────────────────────────────

def verify_totp(profile, code: str) -> bool:
    if not profile.mfa_secret or not code:
        return False
    code = str(code).strip().replace(' ', '')
    # valid_window=1 tolerates ±30s clock drift between phone and server.
    return pyotp.TOTP(profile.mfa_secret).verify(code, valid_window=1)


def _totp_step(profile, code: str):
    """The 30-second time step `code` belongs to (now, ±1 for clock drift), or None."""
    totp = pyotp.TOTP(profile.mfa_secret)
    now = time.time()
    for offset in (0, -1, 1):
        t = now + offset * totp.interval
        if hmac.compare_digest(totp.at(t), code):
            return int(t // totp.interval)
    return None


def verify_login_code(profile, code: str) -> bool:
    """verify_totp for the LOGIN step, where a code is accepted once: the step it belongs to,
    and every earlier one, is refused afterwards — an observed code can't open a second
    session (Batch 3, A-2; RFC 6238 §5.2)."""
    if not profile.mfa_secret or not code:
        return False
    step = _totp_step(profile, str(code).strip().replace(' ', ''))
    if step is None:
        return False
    last_key = f'mfa-last-step:{profile.pk}'
    if step <= (cache.get(last_key) or -1):
        return False
    if not cache.add(f'mfa-step:{profile.pk}:{step}', 1, 120):    # two requests, same code
        return False
    cache.set(last_key, step, 120)
    return True


def generate_backup_codes(n=10):
    """Return (plaintext_codes, hashed_codes). Plaintext is shown to the user once."""
    plain = ['-'.join((secrets.token_hex(2), secrets.token_hex(2))) for _ in range(n)]
    hashed = [make_password(c) for c in plain]
    return plain, hashed


def consume_backup_code(profile, code: str) -> bool:
    """If `code` matches an unused backup code, remove it and return True."""
    if not code or not profile.mfa_backup_codes:
        return False
    code = str(code).strip()
    for h in list(profile.mfa_backup_codes):
        if check_password(code, h):
            profile.mfa_backup_codes.remove(h)
            profile.save(update_fields=['mfa_backup_codes'])
            return True
    return False


def _qr_png_data_url(uri: str) -> str:
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


# ── Shared login-response builder (lazy import to avoid an import cycle) ──────────

def session_response(payload: dict, status_code=200, device_secret=None, refresh_max_age=None):
    """Response for a completed login: body as before + httpOnly JWT cookies (+ the device cookie
    when a new device was enrolled). `refresh_max_age` caps the refresh cookie (zone cap, N3)."""
    from core.auth_cookies import set_auth_cookies, set_device_cookie
    resp = Response(payload, status=status_code)
    set_auth_cookies(resp, payload.get('access'), payload.get('refresh'), refresh_max_age=refresh_max_age)
    if device_secret:
        set_device_cookie(resp, device_secret)
    return resp


def blocked_device_response(request, profile):
    """401 (and a login_failed log row) when the request carries a BLOCKED device's cookie, else None."""
    from apps.access import devices
    if request is None or not devices.blocked_cookie(request):
        return None
    _log('login_refused_device', profile, request)   # not login_failed: never counts toward lockout
    return Response({'error': devices.BLOCKED_MESSAGE}, status=status.HTTP_401_UNAUTHORIZED)


def enroll_login(request, user):
    """Enroll the browser's device for a completed sign-in: (device, new_secret) or (None, None)."""
    profile = getattr(user, 'staff_profile', None)
    if request is None or not profile:
        return None, None
    from apps.access import devices
    device, secret, _created = devices.enroll(request, profile)
    return device, secret


def _zone_refused(request, user, zone, reason):
    from apps.access import session_policy
    _log('login_refused_zone', getattr(user, 'staff_profile', None), request, note=f'zone={zone} reason={reason}')
    # 'error' (not 'detail'): the login page reads .error (ruling F6)
    return Response({'error': session_policy.message(reason), 'zone': zone, 'reason': reason},
                    status=status.HTTP_403_FORBIDDEN)


def zone_refusal_response(request, user, zone):
    """403 (and a login_refused_zone log row) when the role is blocked in this zone and the policy
    is enforced, else None. Never counts toward the lockout (N3)."""
    from apps.access import session_policy
    reason = session_policy.login_refusal(request, session_policy.subject(user), zone)
    return None if reason is None else _zone_refused(request, user, zone, reason)


def enrol_refusal_response(request, user, zone):
    """403 when a first 2FA enrolment at sign-in comes from outside the network and the policy is
    enforced (F1: riders and everyone else enrol once inside), else None."""
    from apps.access import session_policy
    reason = session_policy.enrol_refusal(request, session_policy.subject(user), zone)
    return None if reason is None else _zone_refused(request, user, zone, reason)


def cookie_age(profile, zone, payload):
    """Refresh-cookie max_age for a completed sign-in (zone cap, enforce only), or None."""
    try:
        from rest_framework_simplejwt.tokens import RefreshToken
        from apps.access import session_policy
        auth_at = RefreshToken(payload['refresh']).get('auth_at')
        return session_policy.refresh_max_age(profile, zone, auth_at)
    except Exception:
        return None


def build_login_response(user, request=None, device=None, zone=None) -> dict:
    """Tokens + user for a completed sign-in. `device` (from enroll_login) adds the `dev` claim;
    without a request or device there is no enrollment and no claim. Every token gets the `zone`
    (worked out from the request when not given) and `auth_at` claims (N3)."""
    from rest_framework_simplejwt.tokens import RefreshToken
    from apps.access import session_policy
    from .views import _MeSerializer
    profile = getattr(user, 'staff_profile', None)
    refresh = RefreshToken.for_user(user)
    if device is not None:
        refresh['dev'] = str(device.public_id)   # before .access_token: the access token copies it
    if zone is None and request is not None:
        zone = session_policy.request_zone(request)
    session_policy.stamp(refresh, zone)
    return {
        'access':  str(refresh.access_token),
        'refresh': str(refresh),
        'user': _MeSerializer(profile).data if profile else {
            'username': user.username,
            'role': 'admin' if user.is_superuser else 'viewer',
        },
    }


def _actor_from_request(request, purposes=('enroll',)):
    """Resolve the acting user from either a JWT session (voluntary enrollment from
    settings) or a pre-auth mfa_token in the body (forced enrollment at login).
    Only an ENROLL token counts: the 'login' token an enrolled user gets after the password
    step is for /2fa/verify/ alone — accepting it here let the password by itself install a
    new secret and come back with JWTs (Batch 3, A-1)."""
    if request.user and request.user.is_authenticated:
        return request.user, False  # via_jwt
    token = request.data.get('mfa_token', '')
    for p in purposes:
        u = read_preauth_token(token, p)
        if u:
            return u, True  # via_preauth
    return None, False


def _log(action, profile, request, note='', device=None):
    from .views import _log_auth
    from core.client_ip import client_ip
    ip = client_ip(request)
    _log_auth(action, profile, ip, note=note, request=request, device=device)


# ── Endpoints ────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def verify_2fa_view(request):
    """Step 2 of login: exchange a pre-auth token + TOTP/backup code for JWTs."""
    user, login_id = _read_preauth(request.data.get('mfa_token', ''), 'login')
    tries_key, done_key = f'mfa-tries:{login_id}', f'mfa-done:{login_id}'
    # A-2: a login token opens ONE session and takes at most MAX_CODE_TRIES wrong codes.
    if (not user or not login_id or cache.get(done_key)
            or (cache.get(tries_key) or 0) >= MAX_CODE_TRIES):
        return Response({'error': 'انتهت صلاحية الجلسة، يرجى تسجيل الدخول مجدداً'},
                        status=status.HTTP_401_UNAUTHORIZED)
    profile = getattr(user, 'staff_profile', None)
    code = request.data.get('code', '')

    from . import lockout          # H8: a locked account takes no more codes
    if profile and lockout.locked_until(profile):
        return Response({'error': lockout.LOCKED_MESSAGE}, status=status.HTTP_429_TOO_MANY_REQUESTS)

    if not (profile and profile.mfa_enabled):
        return Response({'error': 'المصادقة الثنائية غير مفعّلة'}, status=status.HTTP_400_BAD_REQUEST)

    refused = blocked_device_response(request, profile)
    if refused is not None:
        return refused
    from apps.access import session_policy
    zone = session_policy.request_zone(request)
    refused = zone_refusal_response(request, user, zone)
    if refused is not None:
        return refused

    if not (verify_login_code(profile, code) or consume_backup_code(profile, code)):
        cache.add(tries_key, 0, _PREAUTH_MAX_AGE)
        tries = cache.incr(tries_key)
        _log('mfa_failed', profile, request, note=f'try {tries}/{MAX_CODE_TRIES}')
        if lockout.locked_until(profile):
            from core.client_ip import client_ip
            lockout.register_lock(profile, client_ip(request), request=request)
        if tries >= MAX_CODE_TRIES:
            return Response({'error': 'محاولات كثيرة خاطئة — سجّل الدخول من جديد'},
                            status=status.HTTP_401_UNAUTHORIZED)
        return Response({'error': 'رمز التحقق غير صحيح'}, status=status.HTTP_401_UNAUTHORIZED)

    cache.set(done_key, 1, _PREAUTH_MAX_AGE)
    device, device_secret = enroll_login(request, user)
    _log('mfa_verified', profile, request, device=device)
    resp = build_login_response(user, request, device=device, zone=zone)
    if request.data.get('remember_device'):
        from apps.access import devices
        devices.remember_mfa(device, profile)     # approved devices only (N2)
    session_policy.alert_external_login(profile, zone, request)
    return session_response(resp, device_secret=device_secret,
                            refresh_max_age=cookie_age(session_policy.subject(user), zone, resp))


@api_view(['POST'])
@permission_classes([AllowAny])
def setup_2fa_view(request):
    """Generate a fresh (pending) TOTP secret + QR. Callable via JWT or enroll token."""
    user, via_preauth = _actor_from_request(request)
    if not user:
        return Response({'error': 'غير مصرح'}, status=status.HTTP_401_UNAUTHORIZED)
    profile = getattr(user, 'staff_profile', None)
    if not profile:
        return Response({'error': 'لا يوجد ملف موظف لهذا الحساب'}, status=status.HTTP_400_BAD_REQUEST)
    if via_preauth:              # enrolment at sign-in: only from inside the network (F1)
        from apps.access import session_policy
        refused = enrol_refusal_response(request, user, session_policy.request_zone(request))
        if refused is not None:
            return refused
    if profile.mfa_enabled:      # never replace a working authenticator (A-1) — disable it first
        return Response({'error': 'المصادقة الثنائية مفعّلة بالفعل — أوقفها أولاً لربط هاتف جديد'},
                        status=status.HTTP_400_BAD_REQUEST)

    secret = pyotp.random_base32()
    profile.mfa_secret = secret           # pending until confirmed by /enable
    profile.save(update_fields=['mfa_secret'])

    label = profile.full_name or user.username
    uri = pyotp.TOTP(secret).provisioning_uri(name=label, issuer_name=ISSUER)
    return Response({'secret': secret, 'otpauth_uri': uri, 'qr_png': _qr_png_data_url(uri)})


@api_view(['POST'])
@permission_classes([AllowAny])
def enable_2fa_view(request):
    """Confirm the pending secret with a code, enable 2FA, return one-time backup codes.
    When called during forced login enrollment, also completes login (returns JWTs)."""
    user, via_preauth = _actor_from_request(request)
    if not user:
        return Response({'error': 'غير مصرح'}, status=status.HTTP_401_UNAUTHORIZED)
    profile = getattr(user, 'staff_profile', None)
    if not profile or not profile.mfa_secret:
        return Response({'error': 'ابدأ الإعداد أولاً'}, status=status.HTTP_400_BAD_REQUEST)
    zone = None
    if via_preauth:
        refused = blocked_device_response(request, profile)
        if refused is not None:
            return refused
        from apps.access import session_policy
        zone = session_policy.request_zone(request)
        refused = (zone_refusal_response(request, user, zone)
                   or enrol_refusal_response(request, user, zone))
        if refused is not None:
            return refused
    if profile.mfa_enabled:      # A-1: no second set of backup codes / no login through here
        return Response({'error': 'المصادقة الثنائية مفعّلة بالفعل'}, status=status.HTTP_400_BAD_REQUEST)

    if not verify_totp(profile, request.data.get('code', '')):
        return Response({'error': 'رمز التحقق غير صحيح — تأكد من الوقت في هاتفك'},
                        status=status.HTTP_400_BAD_REQUEST)

    plain, hashed = generate_backup_codes()
    profile.mfa_enabled = True
    profile.mfa_confirmed_at = timezone.now()
    profile.mfa_backup_codes = hashed
    profile.save(update_fields=['mfa_enabled', 'mfa_confirmed_at', 'mfa_backup_codes'])
    _log('mfa_enabled', profile, request)

    resp = {'enabled': True, 'backup_codes': plain}
    device_secret, max_age = None, None
    if via_preauth:
        # Enrolled as part of a forced login → log them in now.
        device, device_secret = enroll_login(request, user)
        resp.update(build_login_response(user, request, device=device, zone=zone))
        _log('login_success', profile, request, note='دخول بعد تفعيل المصادقة الثنائية', device=device)
        session_policy.alert_external_login(profile, zone, request)
        max_age = cookie_age(session_policy.subject(user), zone, resp)
    return session_response(resp, device_secret=device_secret, refresh_max_age=max_age)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def disable_2fa_view(request):
    """Turn off 2FA. Requires the account password AND a current code (or backup code)."""
    user = request.user
    profile = getattr(user, 'staff_profile', None)
    if not (profile and profile.mfa_enabled):
        return Response({'error': 'المصادقة الثنائية غير مفعّلة'}, status=status.HTTP_400_BAD_REQUEST)

    if not user.check_password(request.data.get('password', '')):
        return Response({'error': 'كلمة المرور غير صحيحة'}, status=status.HTTP_400_BAD_REQUEST)

    code = request.data.get('code', '')
    if not (verify_totp(profile, code) or consume_backup_code(profile, code)):
        return Response({'error': 'رمز التحقق غير صحيح'}, status=status.HTTP_400_BAD_REQUEST)

    profile.mfa_enabled = False
    profile.mfa_secret = ''
    profile.mfa_backup_codes = []
    profile.mfa_confirmed_at = None
    profile.save(update_fields=['mfa_enabled', 'mfa_secret', 'mfa_backup_codes', 'mfa_confirmed_at'])
    _log('mfa_disabled', profile, request)
    return Response({'detail': 'تم إيقاف المصادقة الثنائية'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def forget_devices_view(request):
    """The signed-in user cancels every saved "remember this device" (N0/H7)."""
    from core.client_ip import client_ip
    profile = getattr(request.user, 'staff_profile', None)
    if not profile:
        return Response({'error': 'لا يوجد ملف موظف'}, status=status.HTTP_400_BAD_REQUEST)
    forget_devices(profile, profile, client_ip(request))
    return Response({'detail': 'تم إلغاء كل الأجهزة المحفوظة'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def status_2fa_view(request):
    profile = getattr(request.user, 'staff_profile', None)
    return Response({
        'enabled':           bool(profile and profile.mfa_enabled),
        'confirmed_at':      profile.mfa_confirmed_at if profile else None,
        'required_for_role': bool(profile and profile.role in MFA_REQUIRED_ROLES),
        'enforcement_on':    mfa_enforced(),
        'backup_codes_left': len(profile.mfa_backup_codes) if profile else 0,
    })
