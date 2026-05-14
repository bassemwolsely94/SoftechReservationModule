from rest_framework import serializers as drf_serializers, status, viewsets, filters
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.utils import timezone

from .models import StaffProfile, ERPUser, UserActivityLog, RoleModuleAccess, ROLE_CHOICES, MODULE_CHOICES, ACTION_CHOICES
from .serializers import (
    StaffProfileSerializer,
    StaffProfileListSerializer,
    StaffProfileUpdateSerializer,
    UserCreateSerializer,
    UserActivityLogSerializer,
    ERPUserSerializer,
)
from .middleware import get_current_ip
from core.permissions import IsAdminRole


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

    def get_branch_id(self, obj):
        return obj.branch_id  # Django auto-attribute (FK integer)

    class Meta:
        model  = StaffProfile
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name',
            'full_name', 'role', 'role_label',
            'branch_id', 'branch_name',
            'access_all_branches', 'softech_username',
            'phone', 'is_active',
            'can_see_all_customers', 'can_see_customer_phone',
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


def _log_auth(action: str, profile, ip: str, note: str = ''):
    try:
        UserActivityLog.objects.create(
            target_user=profile,
            changed_by=None,
            action=action,
            ip_address=ip,
            note=note,
        )
    except Exception:
        pass


@api_view(['POST'])
@permission_classes([AllowAny])
def login_view(request):
    identifier = request.data.get('username', '').strip()
    password   = request.data.get('password', '')
    ip         = get_current_ip() or request.META.get('REMOTE_ADDR')

    if not identifier or not password:
        return Response({'error': 'يرجى إدخال اسم المستخدم وكلمة المرور'}, status=status.HTTP_400_BAD_REQUEST)

    # Resolve the identifier to a Django User object
    resolved_user = _resolve_user(identifier)

    if resolved_user:
        user = authenticate(username=resolved_user.username, password=password)
    else:
        user = None

    if not user:
        # Log failed attempt if profile found
        profile = getattr(resolved_user, 'staff_profile', None) if resolved_user else None
        _log_auth('login_failed', profile, ip, note=f'identifier={identifier}')
        return Response({'error': 'بيانات الدخول غير صحيحة'}, status=status.HTTP_401_UNAUTHORIZED)

    if not user.is_active:
        return Response({'error': 'الحساب غير مفعل. تواصل مع المدير'}, status=status.HTTP_403_FORBIDDEN)

    profile = getattr(user, 'staff_profile', None)
    if profile and not profile.is_active:
        return Response({'error': 'الحساب موقوف. تواصل مع المدير'}, status=status.HTTP_403_FORBIDDEN)

    _log_auth('login_success', profile, ip)

    refresh = RefreshToken.for_user(user)
    return Response({
        'access':  str(refresh.access_token),
        'refresh': str(refresh),
        'user': _MeSerializer(profile).data if profile else {
            'username': user.username,
            'role': 'admin' if user.is_superuser else 'viewer',
        }
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def refresh_view(request):
    from rest_framework_simplejwt.views import TokenRefreshView
    return TokenRefreshView.as_view()(request._request)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def me_view(request):
    profile = getattr(request.user, 'staff_profile', None)
    if profile:
        return Response(_MeSerializer(profile).data)
    return Response({
        'username': request.user.username,
        'role': 'admin' if request.user.is_superuser else 'viewer',
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

    if len(new_pw) < 6:
        return Response({'error': 'كلمة المرور يجب أن تكون 6 أحرف على الأقل'}, status=status.HTTP_400_BAD_REQUEST)

    user = request.user
    if not user.check_password(old_pw):
        return Response({'error': 'كلمة المرور القديمة غير صحيحة'}, status=status.HTTP_400_BAD_REQUEST)

    user.set_password(new_pw)
    user.save(update_fields=['password'])

    profile = getattr(user, 'staff_profile', None)
    ip      = get_current_ip() or request.META.get('REMOTE_ADDR')
    _log_auth('password_changed', profile, ip)

    return Response({'detail': 'تم تغيير كلمة المرور بنجاح'})


# ── Pagination ─────────────────────────────────────────────────────────────────

class StandardPagination(PageNumberPagination):
    page_size = 30
    page_size_query_param = 'page_size'
    max_page_size = 200


# ── StaffProfile ViewSet ───────────────────────────────────────────────────────

class StaffProfileViewSet(viewsets.ModelViewSet):
    """
    CRUD for staff users.
    Admin-only for create/update/delete; authenticated users can see the list.
    """
    queryset = StaffProfile.objects.select_related('user', 'branch', 'erp_user').order_by('user__username')
    pagination_class = StandardPagination
    filter_backends  = [filters.SearchFilter, filters.OrderingFilter]
    search_fields    = ['user__username', 'user__first_name', 'user__last_name', 'softech_username']
    ordering_fields  = ['user__username', 'role', 'branch__name']

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsAdminRole()]

    def get_serializer_class(self):
        if self.action == 'list':
            return StaffProfileListSerializer
        if self.action in ('update', 'partial_update'):
            return StaffProfileUpdateSerializer
        if self.action == 'create':
            return UserCreateSerializer
        return StaffProfileSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        role   = self.request.query_params.get('role')
        branch = self.request.query_params.get('branch')
        active = self.request.query_params.get('is_active')
        if role:
            qs = qs.filter(role=role)
        if branch:
            qs = qs.filter(branch_id=branch)
        if active is not None:
            qs = qs.filter(is_active=active.lower() in ('1', 'true', 'yes'))
        return qs

    def perform_create(self, serializer):
        profile = serializer.save()
        actor   = getattr(self.request.user, 'staff_profile', None)
        ip      = get_current_ip() or self.request.META.get('REMOTE_ADDR')
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
        if len(new_pw) < 6:
            return Response({'error': 'كلمة المرور يجب أن تكون 6 أحرف على الأقل'}, status=status.HTTP_400_BAD_REQUEST)

        profile.user.set_password(new_pw)
        profile.user.save(update_fields=['password'])

        actor = getattr(request.user, 'staff_profile', None)
        ip    = get_current_ip() or request.META.get('REMOTE_ADDR')
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

        actor  = getattr(request.user, 'staff_profile', None)
        ip     = get_current_ip() or request.META.get('REMOTE_ADDR')
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
        logs    = UserActivityLog.objects.filter(target_user=profile).select_related('changed_by')[:100]
        return Response(UserActivityLogSerializer(logs, many=True).data)


# ── ERPUser ViewSet ────────────────────────────────────────────────────────────

class ERPUserViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only view of SOFTECH ERP users (synced cache).
    Used by the user-creation form to validate usernames exist in ERP.
    """
    queryset = ERPUser.objects.all().order_by('username')
    serializer_class = ERPUserSerializer
    permission_classes = [IsAuthenticated]
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
        """Return the full permissions matrix."""
        rows = RoleModuleAccess.objects.all().values('role', 'module', 'action', 'is_allowed')
        matrix = {}
        for row in rows:
            r = row['role']; m = row['module']; a = row['action']
            matrix.setdefault(r, {}).setdefault(m, {})[a] = row['is_allowed']

        return Response({
            'matrix': matrix,
            'roles':   [{'value': v, 'label': l} for v, l in ROLE_CHOICES if v != 'admin'],
            'modules': [{'value': v, 'label': l} for v, l in MODULE_CHOICES],
            'actions': [{'value': v, 'label': l} for v, l in ACTION_CHOICES],
        })

    def create(self, request):
        """Bulk-upsert permissions from a list of {role, module, action, is_allowed}."""
        if not (request.user.is_superuser or
                getattr(getattr(request.user, 'staff_profile', None), 'role', '') == 'admin'):
            return Response({'error': 'غير مصرح'}, status=status.HTTP_403_FORBIDDEN)

        updates = request.data if isinstance(request.data, list) else request.data.get('updates', [])
        actor   = getattr(request.user, 'staff_profile', None)
        changed = []

        for item in updates:
            role   = item.get('role')
            module = item.get('module')
            act    = item.get('action')
            allow  = bool(item.get('is_allowed', True))

            if not (role and module and act):
                continue

            obj, created = RoleModuleAccess.objects.update_or_create(
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
                    ip_address=get_current_ip() or request.META.get('REMOTE_ADDR'),
                )
            except Exception:
                pass

        return Response({'detail': f'تم تحديث {len(changed)} صلاحية', 'updated': changed})
