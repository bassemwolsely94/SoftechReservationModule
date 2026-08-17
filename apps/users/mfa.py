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
import io
import secrets

import pyotp
import qrcode
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.models import User
from django.core import signing
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
# Trusted-device token — lets a user skip 2FA on the same device for 30 days.
_DEVICE_SALT = 'mfa-device'
_DEVICE_MAX_AGE = 30 * 24 * 3600


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
    return signing.dumps({'uid': user.id, 'purpose': purpose}, salt=_PREAUTH_SALT)


def read_preauth_token(token: str, purpose: str):
    """Return the User for a valid, unexpired pre-auth token of the given purpose, else None."""
    try:
        data = signing.loads(token, salt=_PREAUTH_SALT, max_age=_PREAUTH_MAX_AGE)
    except signing.BadSignature:
        return None
    if data.get('purpose') != purpose:
        return None
    return User.objects.filter(id=data.get('uid')).first()


def make_device_token(user) -> str:
    return signing.dumps({'uid': user.id}, salt=_DEVICE_SALT)


def valid_device_token(token: str, user) -> bool:
    if not token:
        return False
    try:
        data = signing.loads(token, salt=_DEVICE_SALT, max_age=_DEVICE_MAX_AGE)
    except signing.BadSignature:
        return False
    return data.get('uid') == user.id


# ── TOTP + backup codes ──────────────────────────────────────────────────────────

def verify_totp(profile, code: str) -> bool:
    if not profile.mfa_secret or not code:
        return False
    code = str(code).strip().replace(' ', '')
    # valid_window=1 tolerates ±30s clock drift between phone and server.
    return pyotp.TOTP(profile.mfa_secret).verify(code, valid_window=1)


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

def build_login_response(user) -> dict:
    from rest_framework_simplejwt.tokens import RefreshToken
    from .views import _MeSerializer
    profile = getattr(user, 'staff_profile', None)
    refresh = RefreshToken.for_user(user)
    return {
        'access':  str(refresh.access_token),
        'refresh': str(refresh),
        'user': _MeSerializer(profile).data if profile else {
            'username': user.username,
            'role': 'admin' if user.is_superuser else 'viewer',
        },
    }


def _actor_from_request(request, purposes=('enroll', 'login')):
    """Resolve the acting user from either a JWT session (voluntary enrollment from
    settings) or a pre-auth mfa_token in the body (forced enrollment at login)."""
    if request.user and request.user.is_authenticated:
        return request.user, False  # via_jwt
    token = request.data.get('mfa_token', '')
    for p in purposes:
        u = read_preauth_token(token, p)
        if u:
            return u, True  # via_preauth
    return None, False


def _log(action, profile, request, note=''):
    from .views import _log_auth
    from .middleware import get_current_ip
    ip = get_current_ip() or request.META.get('REMOTE_ADDR')
    _log_auth(action, profile, ip, note=note)


# ── Endpoints ────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def verify_2fa_view(request):
    """Step 2 of login: exchange a pre-auth token + TOTP/backup code for JWTs."""
    user = read_preauth_token(request.data.get('mfa_token', ''), 'login')
    if not user:
        return Response({'error': 'انتهت صلاحية الجلسة، يرجى تسجيل الدخول مجدداً'},
                        status=status.HTTP_401_UNAUTHORIZED)
    profile = getattr(user, 'staff_profile', None)
    code = request.data.get('code', '')

    if not (profile and profile.mfa_enabled):
        return Response({'error': 'المصادقة الثنائية غير مفعّلة'}, status=status.HTTP_400_BAD_REQUEST)

    if not (verify_totp(profile, code) or consume_backup_code(profile, code)):
        _log('mfa_failed', profile, request)
        return Response({'error': 'رمز التحقق غير صحيح'}, status=status.HTTP_401_UNAUTHORIZED)

    _log('mfa_verified', profile, request)
    resp = build_login_response(user)
    if request.data.get('remember_device'):
        resp['device_token'] = make_device_token(user)
    return Response(resp)


@api_view(['POST'])
@permission_classes([AllowAny])
def setup_2fa_view(request):
    """Generate a fresh (pending) TOTP secret + QR. Callable via JWT or enroll token."""
    user, _ = _actor_from_request(request)
    if not user:
        return Response({'error': 'غير مصرح'}, status=status.HTTP_401_UNAUTHORIZED)
    profile = getattr(user, 'staff_profile', None)
    if not profile:
        return Response({'error': 'لا يوجد ملف موظف لهذا الحساب'}, status=status.HTTP_400_BAD_REQUEST)

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
    if via_preauth:
        # Enrolled as part of a forced login → log them in now.
        resp.update(build_login_response(user))
    return Response(resp)


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
