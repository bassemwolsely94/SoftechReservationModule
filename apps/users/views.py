from rest_framework import serializers as drf_serializers, status, viewsets, filters
from rest_framework.decorators import api_view, permission_classes, action, throttle_classes
from rest_framework.permissions import IsAuthenticated, AllowAny

from core.auth_cookies import set_auth_cookies, set_device_cookie
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.throttling import AnonRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


# ── Gap-1: Brute-force throttle on login ──────────────────────────────────────

class LoginRateThrottle(AnonRateThrottle):
    """
    Limits login attempts to 10 per IP per minute.
    Scope 'login' maps to REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['login'].
    Applied ONLY to login_view — no other endpoint is affected.
    """
    scope = 'login'

from .models import StaffProfile, ERPUser, UserActivityLog, RoleModuleAccess, ROLE_CHOICES, MODULE_CHOICES, ACTION_CHOICES
from .serializers import (
    StaffProfileSerializer,
    StaffProfileListSerializer,
    StaffPickerSerializer,
    StaffProfileUpdateSerializer,
    UserCreateSerializer,
    UserActivityLogSerializer,
    ERPUserSerializer,
)
from core.client_ip import client_ip
from core.multi_filter import filter_in, multi_values
from core.stable_ordering import StableOrderingMixin
from .passwords import password_problem
from core.permissions import IsAdminRole, MatrixPermission, matrix_allows, matrix_permission


# ── Inline serializer for auth/me ─────────────────────────────────────────────

class _MeSerializer(drf_serializers.ModelSerializer):
    username   = drf_serializers.CharField(source='user.username',   read_only=True)
    email      = drf_serializers.CharField(source='user.email',      read_only=True)
    first_name = drf_serializers.CharField(source='user.first_name', read_only=True)
    last_name  = drf_serializers.CharField(source='user.last_name',  read_only=True)
    full_name  = drf_serializers.CharField(read_only=True)
    branch_name = drf_serializers.CharField(read_only=True)
    branch_id  = drf_serializers.SerializerMethodField()
    role_label = drf_serializers.CharField(source='get_role_display', read_only=True)
    # /supply + engine access also follows the SOFTECH user group (purchasing/access.py);
    # the frontend only uses these to show menus/buttons — the views enforce them.
    can_supply_write = drf_serializers.SerializerMethodField()
    can_run_engine   = drf_serializers.SerializerMethodField()
    can_stock_audit  = drf_serializers.SerializerMethodField()   # doc 32: management or a named branch manager
    can_pic_analytics = drf_serializers.SerializerMethodField()  # doc 33: management or a named branch manager
    can_usage_print  = drf_serializers.SerializerMethodField()   # Project 5: flag ON + RBAC usage_print view
    can_hr_attendance = drf_serializers.SerializerMethodField()  # admin or a named attendance grantee
    features = drf_serializers.SerializerMethodField()           # switches for features that ship dark

    def get_features(self, obj):
        from django.conf import settings as dj
        return {'camera_scan': bool(getattr(dj, 'CAMERA_SCAN_ENABLED', False)),
                'daily_count': bool(getattr(dj, 'DAILY_COUNT_ENABLED', False))}

    def get_branch_id(self, obj):
        return obj.branch_id  # Django auto-attribute (FK integer)

    def get_can_supply_write(self, obj):
        from apps.purchasing.access import can_supply_write
        return can_supply_write(obj.user)

    def get_can_run_engine(self, obj):
        from apps.purchasing.access import can_run_engine
        return can_run_engine(obj.user)

    def get_can_stock_audit(self, obj):
        from apps.stock_audit.access import can_open
        return can_open(obj.user)

    def get_can_pic_analytics(self, obj):
        from apps.pic_analytics.access import can_open
        return can_open(obj.user)

    def get_can_hr_attendance(self, obj):
        from apps.hr.attendance.access import can_open
        return can_open(obj.user)

    def get_can_usage_print(self, obj):
        from apps.usage_print.access import can_open
        return can_open(obj.user)

    class Meta:
        model  = StaffProfile
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name',
            'full_name', 'role', 'role_label',
            'branch_id', 'branch_name',
            'access_all_branches', 'softech_username',
            'phone', 'is_active',
            'can_see_all_customers', 'can_see_customer_phone',
            'mfa_enabled', 'can_supply_write', 'can_run_engine', 'can_stock_audit', 'can_pic_analytics', 'can_usage_print', 'can_hr_attendance',
            'features',
        ]


# ── Auth endpoints ─────────────────────────────────────────────────────────────

def _resolve_user(identifier: str):
    """
    Given a login identifier (may be Django username OR softech_user_id),
    return the Django User or None.
    Supports case-SENSITIVE exact match on both fields.
    """
    # 1) Try direct Django username lookup
    try:
        return User.objects.get(username=identifier)
    except User.DoesNotExist:
        pass

    # 2) Try softech_user_id on StaffProfile
    profile = StaffProfile.objects.filter(softech_user_id=identifier).select_related('user').first()
    if profile:
        return profile.user

    # 3) Try softech_username
    profile = StaffProfile.objects.filter(softech_username=identifier).select_related('user').first()
    if profile:
        return profile.user

    return None


def _request_network_fields(request):
    """The network label and browser of a request, for the activity log (blank without one)."""
    if request is None:
        return {}
    try:
        from apps.access.network import request_network
        acc = getattr(request, 'access', None)
        net = acc.network if acc else request_network(request)
        return {
            'network': net.zone,
            'network_site': net.site.name if net.site else '',
            'user_agent': (request.META.get('HTTP_USER_AGENT') or '')[:300],
        }
    except Exception:
        return {}


def _log_auth(action: str, profile, ip: str, note: str = '', request=None, device=None):
    try:
        UserActivityLog.objects.create(
            target_user=profile,
            changed_by=None,
            action=action,
            ip_address=ip,
            note=note,
            device=device,
            **_request_network_fields(request),
        )
    except Exception:
        pass


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminRole])
def forget_devices_admin_view(request, pk):
    """Admin cancels another user's saved "remember this device" tokens (N0/H7)."""
    from . import mfa
    profile = StaffProfile.objects.select_related('user').filter(pk=pk).first()
    if not profile:
        return Response({'error': 'المستخدم غير موجود'}, status=status.HTTP_404_NOT_FOUND)
    mfa.forget_devices(profile, getattr(request.user, 'staff_profile', None), client_ip(request))
    return Response({'detail': f'تم إلغاء الأجهزة المحفوظة لـ {profile.full_name or profile.user.username}'})


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([LoginRateThrottle])
def login_view(request):
    identifier = request.data.get('username', '').strip()
    password   = request.data.get('password', '')
    ip         = client_ip(request)

    if not identifier or not password:
        return Response({'error': 'يرجى إدخال اسم المستخدم وكلمة المرور'}, status=status.HTTP_400_BAD_REQUEST)

    # Resolve the identifier to a Django User object
    resolved_user = _resolve_user(identifier)

    # H8: a locked account answers 429 before the password is even checked (the right password
    # included); an identifier that matches no account answers the same way after the same
    # number of misses, so the two cannot be told apart.
    from . import lockout
    lock_profile = getattr(resolved_user, 'staff_profile', None) if resolved_user else None
    if lock_profile:
        if lockout.locked_until(lock_profile):
            return Response({'error': lockout.LOCKED_MESSAGE}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    elif lockout.unknown_identifier_locked(identifier):
        return Response({'error': lockout.LOCKED_MESSAGE}, status=status.HTTP_429_TOO_MANY_REQUESTS)

    if resolved_user:
        user = authenticate(username=resolved_user.username, password=password)
    else:
        user = None

    if not user:
        # Log failed attempt if profile found
        profile = getattr(resolved_user, 'staff_profile', None) if resolved_user else None
        _log_auth('login_failed', profile, ip, note=f'identifier={identifier}', request=request)
        if profile:
            if lockout.locked_until(profile):
                lockout.register_lock(profile, ip, request=request)
        else:
            lockout.note_unknown_failure(identifier)
        return Response({'error': 'بيانات الدخول غير صحيحة'}, status=status.HTTP_401_UNAUTHORIZED)

    if not user.is_active:
        return Response({'error': 'الحساب غير مفعل. تواصل مع المدير'}, status=status.HTTP_403_FORBIDDEN)

    profile = getattr(user, 'staff_profile', None)
    if profile and not profile.is_active:
        return Response({'error': 'الحساب موقوف. تواصل مع المدير'}, status=status.HTTP_403_FORBIDDEN)

    from apps.access import devices as _devices
    if _devices.blocked_cookie(request):         # a blocked device signs nobody in (N2)
        _log_auth('login_refused_device', profile, ip, request=request)   # not login_failed: never counts toward lockout
        return Response({'error': _devices.BLOCKED_MESSAGE}, status=status.HTTP_401_UNAUTHORIZED)

    # ── Access zone (N3) ──────────────────────────────────────────────────────
    # Only after the password succeeded, before 2FA and tokens. A 403 here does tell the caller
    # the password was right (a wrong one answers 401); the lockout bounds how many passwords
    # can be tried. A refusal happens in enforce mode only; log mode writes a line and goes on.
    from . import mfa as _mfa
    from apps.access import session_policy as _session
    zone = _session.request_zone(request)
    subj = _session.subject(user)
    refused = _mfa.zone_refusal_response(request, user, zone)
    if refused is not None:
        return refused

    # ── Two-factor gate ───────────────────────────────────────────────────────
    # Step 1 of login. If the user has 2FA on (or is in a required role once
    # enforcement is enabled, or signs in from a zone that requires it), don't issue
    # tokens yet — hand back a short-lived pre-auth token the client exchanges at
    # /auth/2fa/verify/ (or /enable/). Only the approved-device remember skips it (N2).
    login_note = ''
    if profile and profile.mfa_enabled:
        if _devices.mfa_remembered(request, profile):
            login_note = 'mfa_skipped_device'
        else:
            _log_auth('mfa_challenge', profile, ip, request=request)
            return Response({'mfa_required': True,
                             'mfa_token': _mfa.make_preauth_token(user, 'login')})
    elif _mfa.mfa_required_for(profile) or _session.login_needs_mfa(request, subj, zone):
        # Not yet enrolled and 2FA required (role enforcement, or the zone) → enrol now,
        # but only from inside the network (F1).
        refused = _mfa.enrol_refusal_response(request, user, zone)
        if refused is not None:
            return refused
        _log_auth('mfa_challenge', profile, ip, note='mfa_setup_required', request=request)
        return Response({'mfa_setup_required': True,
                         'mfa_token': _mfa.make_preauth_token(user, 'enroll')})

    device, device_secret = _mfa.enroll_login(request, user)
    _log_auth('login_success', profile, ip, note=login_note, request=request, device=device)
    payload = _mfa.build_login_response(user, request, device=device, zone=zone,
                                        mfa=login_note == 'mfa_skipped_device')
    _session.alert_external_login(profile, zone, request)
    # The SPA uses the httpOnly cookies and ignores the body tokens (kept for
    # scripts / non-browser clients, which need the password anyway).
    return _mfa.session_response(payload, device_secret=device_secret,
                                 refresh_max_age=_mfa.cookie_age(subj, zone, payload))


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminRole])
def unlock_login_view(request, pk):
    """Admin lifts a login lock (H8) before it runs out."""
    from . import lockout
    profile = StaffProfile.objects.select_related('user').filter(pk=pk).first()
    if not profile:
        return Response({'error': 'المستخدم غير موجود'}, status=status.HTTP_404_NOT_FOUND)
    lockout.unlock(profile, getattr(request.user, 'staff_profile', None), client_ip(request), request=request)
    return Response({'detail': f'تم رفع إيقاف الدخول عن {profile.full_name or profile.user.username}'})


@api_view(['POST'])
@permission_classes([AllowAny])
def refresh_view(request):
    """
    Body {"refresh": …} → legacy behaviour (tokens in the body) + cookies set, which
    also migrates a browser that still had tokens in localStorage.
    No body token → rotate from the httpOnly refresh cookie; tokens are NOT
    returned in the body, so script on the page can never obtain one.
    """
    from rest_framework_simplejwt.exceptions import TokenError
    from rest_framework_simplejwt.serializers import TokenRefreshSerializer
    from core.auth_cookies import REFRESH_COOKIE, clear_auth_cookies

    body_token = request.data.get('refresh')
    raw = body_token or request.COOKIES.get(REFRESH_COOKIE)
    if not raw:
        return Response({'detail': 'لا توجد جلسة'}, status=status.HTTP_401_UNAUTHORIZED)
    if not _refresh_owner_active(raw):           # a disabled account never renews (Batch 3, A-3)
        return clear_auth_cookies(Response({'detail': 'الحساب موقوف'}, status=status.HTTP_401_UNAUTHORIZED))
    from apps.access import devices as _devices
    try:
        dev_claim = RefreshToken(raw).get('dev')
    except Exception:
        dev_claim = None
    if _devices.is_revoked(dev_claim):           # a blocked/retired device never renews (N2)
        return clear_auth_cookies(Response({'detail': _devices.BLOCKED_MESSAGE},
                                           status=status.HTTP_401_UNAUTHORIZED))
    # The zone is worked out again on every refresh (N3): a session started inside and carried
    # outside meets the outside rules; the zone's cap counts from the sign-in (auth_at).
    from apps.access import session_policy as _session
    zone, owner, auth_at = _refresh_zone(request, raw)
    old_token = _old_token(raw)
    reason = _session.refresh_refusal(request, owner, old_token, zone) if owner is not None else None
    if reason is not None:
        return clear_auth_cookies(Response({'detail': _session.message(reason), 'zone': zone, 'reason': reason},
                                           status=status.HTTP_401_UNAUTHORIZED))
    ser = TokenRefreshSerializer(data={'refresh': raw})
    try:
        ser.is_valid(raise_exception=True)
    except TokenError:
        return clear_auth_cookies(Response({'detail': 'انتهت الجلسة'}, status=status.HTTP_401_UNAUTHORIZED))
    except Exception:
        return clear_auth_cookies(Response({'detail': 'انتهت الجلسة'}, status=status.HTTP_401_UNAUTHORIZED))
    data = ser.validated_data
    access, new_refresh, device_secret = data.get('access'), data.get('refresh'), None
    if dev_claim is None and new_refresh:
        # A session from before N2 has no device: enrol this browser now and stamp the rotated
        # tokens, so existing users reach the registry without a forced sign-in (I-2).
        access, new_refresh, device_secret = _stamp_device(request, raw, access, new_refresh)
    access, new_refresh = _stamp_zone(access, new_refresh, zone, auth_at,
                                      mfa=_session.mfa_of(old_token))
    resp = Response({'access': access, 'refresh': new_refresh} if body_token and new_refresh
                    else ({'access': access} if body_token else {'ok': True}))
    if device_secret:
        set_device_cookie(resp, device_secret)
    max_age = _session.refresh_max_age(owner, zone, auth_at) if owner is not None else None
    return set_auth_cookies(resp, access, new_refresh, refresh_max_age=max_age)


def _old_token(raw):
    try:
        return RefreshToken(raw)
    except Exception:
        return None


def _refresh_zone(request, raw):
    """(zone, owner policy subject or None, auth_at) for a refresh. auth_at falls back to the old
    token's iat; an unreadable token gives (zone, None, None) — the serializer refuses it. Never raises."""
    from apps.access import session_policy as _session
    zone = _session.request_zone(request)
    try:
        from rest_framework_simplejwt.settings import api_settings
        token = RefreshToken(raw)
        uid = token.get(api_settings.USER_ID_CLAIM)
        user = User.objects.select_related('staff_profile').filter(
            **{api_settings.USER_ID_FIELD: uid}).first()
        return zone, _session.subject(user), _session.auth_at_of(token)
    except Exception:
        return zone, None, None


def _stamp_zone(access, refresh, zone, auth_at, mfa=False):
    """The rotated tokens with the current `zone` and the kept `auth_at` / `mfa`. Never raises."""
    try:
        from rest_framework_simplejwt.tokens import AccessToken
        from apps.access import session_policy as _session
        if not refresh:
            return access, refresh
        new_r = RefreshToken(refresh)
        _session.stamp(new_r, zone, auth_at=auth_at, mfa=mfa)
        new_a = AccessToken(access)
        new_a['zone'] = new_r['zone']
        new_a['auth_at'] = new_r['auth_at']
        new_a['mfa'] = new_r['mfa']
        return str(new_a), str(new_r)
    except Exception:
        logger.error('refresh zone stamp failed; carrying auth_at only', exc_info=True)
    # F5: never let a rotated token start a fresh cap — carry the sign-in time (old iat) at least.
    try:
        from rest_framework_simplejwt.tokens import AccessToken
        if auth_at is None:
            return access, refresh
        new_r = RefreshToken(refresh)
        new_r['auth_at'] = int(auth_at)
        new_r['mfa'] = bool(mfa)
        new_a = AccessToken(access)
        new_a['auth_at'] = int(auth_at)
        new_a['mfa'] = bool(mfa)
        return str(new_a), str(new_r)
    except Exception:
        logger.error('refresh auth_at carry failed', exc_info=True)
        return access, refresh


def _stamp_device(request, old_raw, access, refresh):
    """(access, refresh, new_device_secret) with a `dev` claim added to the rotated tokens.
    Any problem (no SPA header, blocked cookie, bad token) returns the tokens unchanged. Never raises."""
    try:
        from rest_framework_simplejwt.settings import api_settings
        from rest_framework_simplejwt.tokens import AccessToken
        from apps.access import devices as _devices
        if _devices.blocked_cookie(request):
            return access, refresh, None
        uid = RefreshToken(refresh).get(api_settings.USER_ID_CLAIM)
        user = User.objects.select_related('staff_profile').filter(**{api_settings.USER_ID_FIELD: uid}).first()
        profile = getattr(user, 'staff_profile', None)
        if not profile:
            return access, refresh, None
        device, secret, _created = _devices.enroll(request, profile)
        if device is None:
            return access, refresh, None
        new_r = RefreshToken(refresh)
        new_r['dev'] = str(device.public_id)
        new_a = AccessToken(access)
        new_a['dev'] = str(device.public_id)
        return str(new_a), str(new_r), secret
    except Exception as exc:
        logger.warning('refresh device stamp skipped: %s', exc)
        return access, refresh, None


def _refresh_owner_active(raw) -> bool:
    """False when the refresh token belongs to a disabled account. An unreadable token passes
    through — the refresh serializer rejects it with its own message."""
    from rest_framework_simplejwt.exceptions import TokenError
    from rest_framework_simplejwt.settings import api_settings
    from .sessions import account_active
    try:
        uid = RefreshToken(raw).get(api_settings.USER_ID_CLAIM)
    except TokenError:
        return True
    user = User.objects.select_related('staff_profile').filter(**{api_settings.USER_ID_FIELD: uid}).first()
    return account_active(user)


@api_view(['POST'])
@permission_classes([AllowAny])
def logout_view(request):
    """Blacklist the refresh token (cookie or body) and clear the auth cookies."""
    from rest_framework_simplejwt.tokens import RefreshToken as _RT
    from core.auth_cookies import REFRESH_COOKIE, clear_auth_cookies
    raw = request.data.get('refresh') or request.COOKIES.get(REFRESH_COOKIE)
    if raw:
        try:
            _RT(raw).blacklist()
        except Exception:
            pass   # already expired / blacklisted — logging out anyway
    return clear_auth_cookies(Response({'ok': True}))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def me_view(request):
    profile = getattr(request.user, 'staff_profile', None)
    if profile:
        return Response(_MeSerializer(profile).data)
    from apps.purchasing.access import can_supply_write, can_run_engine
    return Response({
        'username': request.user.username,
        'role': 'admin' if request.user.is_superuser else 'viewer',
        'can_supply_write': can_supply_write(request.user),
        'can_run_engine': can_run_engine(request.user),
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password_view(request):
    """Self-service password change. Requires old_password + new_password."""
    old_pw  = request.data.get('old_password', '')
    new_pw  = request.data.get('new_password', '')
    confirm = request.data.get('confirm_password', '')

    if not old_pw or not new_pw:
        return Response({'error': 'يرجى إدخال كلمة المرور القديمة والجديدة'}, status=status.HTTP_400_BAD_REQUEST)

    if new_pw != confirm:
        return Response({'error': 'كلمة المرور الجديدة وتأكيدها غير متطابقتين'}, status=status.HTTP_400_BAD_REQUEST)

    user = request.user
    problem = password_problem(new_pw, user)             # 10 chars + Django's checks (A-5)
    if problem:
        return Response({'error': problem}, status=status.HTTP_400_BAD_REQUEST)

    if not user.check_password(old_pw):
        return Response({'error': 'كلمة المرور القديمة غير صحيحة'}, status=status.HTTP_400_BAD_REQUEST)

    user.set_password(new_pw)
    user.save(update_fields=['password'])

    # Gap-2: Blacklist all outstanding refresh tokens so the old password's
    # sessions cannot be renewed.  The current access token (up to 1 hour
    # remaining) still works — that's the irreducible JWT trade-off.
    # (Remembered devices are cancelled too: their token fingerprints the password — A-3.)
    from .sessions import end_sessions
    end_sessions(user)

    profile = getattr(user, 'staff_profile', None)
    ip      = client_ip(request)
    _log_auth('password_changed', profile, ip, request=request)

    return Response({'detail': 'تم تغيير كلمة المرور بنجاح'})


# ── Pagination ─────────────────────────────────────────────────────────────────

class StandardPagination(PageNumberPagination):
    page_size = 30
    page_size_query_param = 'page_size'
    max_page_size = 200


# ── StaffProfile ViewSet ───────────────────────────────────────────────────────

class StaffProfileViewSet(StableOrderingMixin, viewsets.ModelViewSet):
    """
    CRUD for staff users.
    Admin-only for create/update/delete; authenticated users can see the list.
    """
    queryset = StaffProfile.objects.select_related('user', 'branch', 'erp_user').order_by('user__username')
    pagination_class = StandardPagination
    filter_backends  = [filters.SearchFilter, filters.OrderingFilter]
    search_fields    = ['user__username', 'user__first_name', 'user__last_name', 'softech_username']

    # Header sorting (UserManagementPage / UsersPage). Only columns the viewer can already see may order the
    # list: the slim picker (roles without `users` view) shows names/role/branch/active only, so it cannot
    # order by the SOFTECH user. Never password, e-mail, phone or any secret.
    PICKER_ORDERING_FIELDS = ['user__username', 'user__first_name', 'user__last_name', 'role', 'branch__name', 'is_active']
    FULL_ORDERING_FIELDS = PICKER_ORDERING_FIELDS + ['softech_username']

    def _sees_full_list(self):
        request = getattr(self, 'request', None)
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return False
        profile = getattr(user, 'staff_profile', None)
        return bool(user.is_superuser or matrix_allows(profile, 'users', 'view'))

    @property
    def ordering_fields(self):
        return self.FULL_ORDERING_FIELDS if self._sees_full_list() else self.PICKER_ORDERING_FIELDS

    def get_permissions(self):
        if self.action == 'list':
            return [IsAuthenticated()]        # picker for every screen — slim fields below (Z-4)
        if self.action == 'retrieve':
            return [IsAuthenticated(), matrix_permission('users')()]
        return [IsAuthenticated(), IsAdminRole()]

    def get_serializer_class(self):
        if self.action == 'list':
            if self._sees_full_list():
                return StaffProfileListSerializer
            return StaffPickerSerializer
        if self.action in ('update', 'partial_update'):
            return StaffProfileUpdateSerializer
        if self.action == 'create':
            return UserCreateSerializer
        return StaffProfileSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        branch = self.request.query_params.get('branch')
        active = self.request.query_params.get('is_active')
        # role: one or several (?role=pharmacist,cashier); none = every role
        qs = filter_in(qs, 'role', multi_values(self.request.query_params, 'role'))
        if branch:
            qs = qs.filter(branch_id=branch)
        if active is not None:
            qs = qs.filter(is_active=active.lower() in ('1', 'true', 'yes'))
        if self.action == 'list':
            # alerts-only members (phone alerts, no login) are listed only on request
            wanted = (self.request.query_params.get('alerts_only') or '').lower() in ('1', 'true', 'yes')
            qs = qs.filter(alerts_only=wanted)
        return qs

    def perform_create(self, serializer):
        profile = serializer.save()
        actor   = getattr(self.request.user, 'staff_profile', None)
        ip      = client_ip(self.request)
        try:
            UserActivityLog.objects.create(
                target_user=profile,
                changed_by=actor,
                action='created',
                ip_address=ip,
            )
        except Exception:
            pass

    @action(detail=True, methods=['post'], url_path='reset-password')
    def reset_password(self, request, pk=None):
        """Admin resets a user's password to a given value."""
        profile  = self.get_object()
        new_pw   = request.data.get('new_password', '')
        problem  = password_problem(new_pw, profile.user)  # 10 chars + Django's checks (A-5)
        if problem:
            return Response({'error': problem}, status=status.HTTP_400_BAD_REQUEST)

        profile.user.set_password(new_pw)
        profile.user.save(update_fields=['password'])
        from .sessions import end_sessions              # the old password's sessions end (A-3)
        end_sessions(profile.user)

        actor = getattr(request.user, 'staff_profile', None)
        ip    = client_ip(request)
        UserActivityLog.objects.create(
            target_user=profile,
            changed_by=actor,
            action='password_reset',
            ip_address=ip,
        )
        return Response({'detail': f'تمت إعادة تعيين كلمة مرور {profile.full_name} بنجاح'})

    @action(detail=True, methods=['post'], url_path='toggle-active')
    def toggle_active(self, request, pk=None):
        """Activate or deactivate a user account."""
        profile = self.get_object()
        profile.is_active = not profile.is_active
        profile.save(update_fields=['is_active'])
        if not profile.is_active:                       # disabling logs the account out (A-3)
            from .sessions import end_sessions
            end_sessions(profile.user)

        actor  = getattr(request.user, 'staff_profile', None)
        ip     = client_ip(request)
        action_name = 'activated' if profile.is_active else 'deactivated'
        UserActivityLog.objects.create(
            target_user=profile,
            changed_by=actor,
            action=action_name,
            ip_address=ip,
        )
        return Response({
            'detail': f'تم {"تفعيل" if profile.is_active else "تعطيل"} حساب {profile.full_name}',
            'is_active': profile.is_active,
        })

    @action(detail=True, methods=['get'], url_path='activity-log')
    def activity_log(self, request, pk=None):
        """Return the audit log for a specific staff member."""
        profile = self.get_object()
        logs    = UserActivityLog.objects.filter(target_user=profile).select_related('changed_by', 'device')[:100]
        return Response(UserActivityLogSerializer(logs, many=True).data)


# ── ERPUser ViewSet ────────────────────────────────────────────────────────────

class ERPUserViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only view of SOFTECH ERP users (synced cache).
    Used by the user-creation form to validate usernames exist in ERP.
    """
    queryset = ERPUser.objects.all().order_by('username')
    serializer_class = ERPUserSerializer
    permission_classes = [IsAuthenticated, MatrixPermission]
    rbac_module = 'users'                          # SOFTECH user list — user management (Z-4)
    filter_backends = [filters.SearchFilter]
    search_fields   = ['username', 'full_name', 'user_id']
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = super().get_queryset()
        active = self.request.query_params.get('is_active')
        no_account = self.request.query_params.get('no_account')
        if active is not None:
            qs = qs.filter(is_active=active.lower() in ('1', 'true', 'yes'))
        if no_account in ('1', 'true'):
            # Only ERP users who don't yet have a local staff account
            qs = qs.filter(staff_profile__isnull=True)
        return qs


# ── Permissions Matrix ViewSet ─────────────────────────────────────────────────

class PermissionsMatrixView(viewsets.ViewSet):
    """
    GET  /api/users/permissions/  → full matrix {role: {module: {action: bool}}}
    POST /api/users/permissions/  → bulk update [{role, module, action, is_allowed}]
    """
    permission_classes = [IsAuthenticated]

    def list(self, request):
        """Return the full permissions matrix. Gap-5: restricted to admin role."""
        if not (request.user.is_superuser or
                getattr(getattr(request.user, 'staff_profile', None), 'role', '') == 'admin'):
            return Response({'error': 'غير مصرح — يتطلب دور المسؤول'}, status=status.HTTP_403_FORBIDDEN)

        rows = RoleModuleAccess.objects.all().values('role', 'module', 'action', 'is_allowed')
        matrix = {}
        for row in rows:
            r = row['role']; m = row['module']; a = row['action']
            matrix.setdefault(r, {}).setdefault(m, {})[a] = row['is_allowed']

        # ── Notifier (notification category) visibility matrix ────────────────
        from apps.notifications.models import Notification, RoleNotificationAccess
        from apps.notifications.views import _CATEGORY_MODULE
        categories = [c for c, _ in Notification.CATEGORY_CHOICES]
        explicit = {}
        for r in RoleNotificationAccess.objects.values('role', 'category', 'is_allowed', 'generate'):
            explicit.setdefault(r['role'], {})[r['category']] = (r['is_allowed'], r['generate'])
        # module 'view' grants per role (for the inherit-default)
        role_module_view = {}
        for role, module in (RoleModuleAccess.objects
                             .filter(action='view', is_allowed=True)
                             .values_list('role', 'module')):
            role_module_view.setdefault(role, set()).add(module)
        # Effective 3-state mode per role × notifier: 'show' | 'mute' | 'off'
        notifier_matrix = {}
        for role, _ in ROLE_CHOICES:
            if role == 'admin':
                continue
            rm = {}
            for c in categories:
                if role in explicit and c in explicit[role]:
                    is_allowed, generate = explicit[role][c]
                    rm[c] = 'off' if not generate else ('show' if is_allowed else 'mute')
                else:
                    module = _CATEGORY_MODULE.get(c)   # inherit module 'view' for visibility
                    visible = True if not module else (module in role_module_view.get(role, set()))
                    rm[c] = 'show' if visible else 'mute'   # generated by default
            notifier_matrix[role] = rm

        return Response({
            'matrix': matrix,
            'roles':   [{'value': v, 'label': l} for v, l in ROLE_CHOICES if v != 'admin'],
            'modules': [{'value': v, 'label': l} for v, l in MODULE_CHOICES],
            'actions': [{'value': v, 'label': l} for v, l in ACTION_CHOICES],
            'notifiers':       [{'value': v, 'label': l} for v, l in Notification.CATEGORY_CHOICES],
            'notifier_matrix': notifier_matrix,
        })

    def create(self, request):
        """Bulk-upsert permissions from a list of {role, module, action, is_allowed}."""
        if not (request.user.is_superuser or
                getattr(getattr(request.user, 'staff_profile', None), 'role', '') == 'admin'):
            return Response({'error': 'غير مصرح'}, status=status.HTTP_403_FORBIDDEN)

        updates = request.data if isinstance(request.data, list) else request.data.get('updates', [])
        actor   = getattr(request.user, 'staff_profile', None)
        changed = []

        from apps.notifications.models import RoleNotificationAccess

        for item in updates:
            role   = item.get('role')
            allow  = bool(item.get('is_allowed', True))

            # Notifier (notification category) update — 3-state mode preferred,
            # falls back to a bare is_allowed for backward compatibility.
            category = item.get('category')
            if role and category and not item.get('module'):
                mode = item.get('mode')
                if mode in ('show', 'mute', 'off'):
                    gen, vis = (mode != 'off'), (mode == 'show')
                else:
                    gen, vis, mode = True, allow, ('show' if allow else 'mute')
                RoleNotificationAccess.objects.update_or_create(
                    role=role, category=category,
                    defaults={'is_allowed': vis, 'generate': gen, 'updated_by': actor},
                )
                changed.append({'role': role, 'category': category, 'mode': mode})
                continue

            # Module / action permission update
            module = item.get('module')
            act    = item.get('action')
            if not (role and module and act):
                continue

            RoleModuleAccess.objects.update_or_create(
                role=role, module=module, action=act,
                defaults={'is_allowed': allow, 'updated_by': actor},
            )
            changed.append({'role': role, 'module': module, 'action': act, 'is_allowed': allow})

        # Audit log a single summary entry
        if changed and actor:
            try:
                UserActivityLog.objects.create(
                    target_user=None,
                    changed_by=actor,
                    action='permissions_changed',
                    new_value={'changes': changed},
                    ip_address=client_ip(request),
                )
            except Exception:
                pass

        return Response({'detail': f'تم تحديث {len(changed)} صلاحية', 'updated': changed})


# ── My Permissions ─────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_permissions_view(request):
    """
    GET /api/users/my-permissions/

    Returns the effective permission map for the currently authenticated user's role.
    Format: { module: { action: bool } }

    Admins receive all-true for every module/action.
    Non-admins receive only their role's RoleModuleAccess grants;
    missing entries default to False.
    """
    profile = getattr(request.user, 'staff_profile', None)
    role = getattr(profile, 'role', 'viewer')

    # Admins are unrestricted
    if role == 'admin' or request.user.is_superuser:
        all_modules = [v for v, _ in MODULE_CHOICES]
        all_actions = [v for v, _ in ACTION_CHOICES]
        perms = {m: {a: True for a in all_actions} for m in all_modules}
        return Response({'role': 'admin', 'permissions': perms})

    rows = RoleModuleAccess.objects.filter(role=role).values('module', 'action', 'is_allowed')
    perms = {}
    for row in rows:
        perms.setdefault(row['module'], {})[row['action']] = row['is_allowed']

    return Response({'role': role, 'permissions': perms})
