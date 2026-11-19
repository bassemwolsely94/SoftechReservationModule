from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from core.permissions import MatrixPermission, deny_unless, matrix_allows
from django.db.models import Prefetch

from .models import SystemSetting, DropdownOption, PharmacyProfile
from .serializers import (
    SystemSettingSerializer, SystemSettingUpdateSerializer,
    DropdownOptionSerializer, DropdownOptionWriteSerializer,
)
from core.permissions import RouteModulePermission  # round 2, D6

_AUDIT_VALUE_MAX = 500


def _short(value):
    text = '' if value is None else str(value)
    return text if len(text) <= _AUDIT_VALUE_MAX else text[:_AUDIT_VALUE_MAX] + '…'


def _audit(request, action, obj=None, changes=None, note=''):
    """Every write on the settings screen is recorded: who, what, before → after (owner 2026-11-19)."""
    from apps.audit.models import AuditLog
    AuditLog.log(action, user=getattr(request.user, 'staff_profile', None), obj=obj,
                 changes=changes or None, note=note, request=request)


class SystemSettingViewSet(viewsets.ModelViewSet):
    """
    GET  /api/config/settings/              → list all
    GET  /api/config/settings/?category=X   → filter by category
    GET  /api/config/settings/{id}/         → detail
    PATCH /api/config/settings/{id}/        → update value
    POST /api/config/settings/by_key/       → bulk fetch by key names
    """
    queryset         = SystemSetting.objects.all()
    permission_classes = [permissions.IsAuthenticated, MatrixPermission]
    rbac_module = 'settings'
    rbac_actions = {'list': (), 'retrieve': (), 'by_key': ('view',), 'bulk_update': ('edit',)}

    def get_serializer_class(self):
        if self.action in ('update', 'partial_update'):
            return SystemSettingUpdateSerializer
        return SystemSettingSerializer

    def perform_update(self, serializer):
        before = serializer.instance.value
        setting = serializer.save()
        if setting.value != before:
            _audit(self.request, 'settings_changed', setting,
                   {'value': [_short(before), _short(setting.value)]}, note=setting.key)

    def perform_create(self, serializer):
        setting = serializer.save()
        _audit(self.request, 'settings_created', setting,
               {'value': [None, _short(setting.value)]}, note=setting.key)

    def perform_destroy(self, instance):
        _audit(self.request, 'settings_deleted', instance,
               {'value': [_short(instance.value), None]}, note=instance.key)
        instance.delete()

    def get_queryset(self):
        qs = super().get_queryset()
        # Without settings view only `is_public` settings are readable (Batch 4, Z-4).
        user = self.request.user
        if not (user.is_superuser or matrix_allows(getattr(user, 'staff_profile', None), 'settings', 'view')):
            qs = qs.filter(is_public=True)
        category = self.request.query_params.get('category')
        if category:
            qs = qs.filter(category=category)
        return qs

    @action(detail=False, methods=['post'])
    def by_key(self, request):
        """POST {keys: ['key1','key2']} → dict of key→value"""
        keys = request.data.get('keys', [])
        settings = SystemSetting.objects.filter(key__in=keys)
        return Response({s.key: s.typed_value() for s in settings})

    @action(detail=False, methods=['post'])
    def bulk_update(self, request):
        """POST {key1: val1, key2: val2} → update multiple settings at once"""
        updated = []
        for key, value in request.data.items():
            try:
                s = SystemSetting.objects.get(key=key)
                before, s.value = s.value, str(value)
                s.save(update_fields=['value', 'updated_at'])
                updated.append(key)
                if s.value != before:
                    _audit(request, 'settings_changed', s, {'value': [_short(before), _short(s.value)]}, note=key)
            except SystemSetting.DoesNotExist:
                pass
        return Response({'updated': updated})


class DropdownOptionViewSet(viewsets.ModelViewSet):
    """
    GET  /api/config/dropdowns/                      → all options
    GET  /api/config/dropdowns/?key=reservation_channel → filter by key
    GET  /api/config/dropdowns/keys/                 → list distinct keys
    POST /api/config/dropdowns/                      → create
    PATCH /api/config/dropdowns/{id}/                → update
    DELETE /api/config/dropdowns/{id}/               → delete (non-system only)
    POST /api/config/dropdowns/reorder/              → bulk reorder
    """
    queryset           = DropdownOption.objects.all()
    permission_classes = [permissions.IsAuthenticated, MatrixPermission]
    rbac_module = 'settings'
    rbac_actions = {'list': (), 'retrieve': ()}

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return DropdownOptionWriteSerializer
        return DropdownOptionSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        key       = self.request.query_params.get('key')
        is_active = self.request.query_params.get('is_active')
        if key:
            qs = qs.filter(dropdown_key=key)
        if is_active is not None:
            qs = qs.filter(is_active=is_active in ('true', '1', 'True'))
        return qs

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_system:
            return Response(
                {'detail': 'لا يمكن حذف هذا الخيار لأنه ثابت في النظام'},
                status=status.HTTP_400_BAD_REQUEST
            )
        return super().destroy(request, *args, **kwargs)

    def _dropdown_audit(self, option, changes, verb):
        _audit(self.request, 'dropdown_option_changed', option, changes,
               note=f'{verb}: {option.dropdown_key} / {_short(getattr(option, "label", "") or option.pk)}')

    def perform_create(self, serializer):
        option = serializer.save()
        self._dropdown_audit(option, None, 'إضافة')

    def perform_update(self, serializer):
        fields = list(serializer.validated_data)
        before = {f: getattr(serializer.instance, f, None) for f in fields}
        option = serializer.save()
        changes = {f: [_short(before[f]), _short(getattr(option, f, None))]
                   for f in fields if before[f] != getattr(option, f, None)}
        if changes:
            self._dropdown_audit(option, changes, 'تعديل')

    def perform_destroy(self, instance):
        self._dropdown_audit(instance, None, 'حذف')
        instance.delete()

    @action(detail=False, methods=['get'])
    def keys(self, request):
        """Return list of distinct dropdown_key values."""
        keys = (
            DropdownOption.objects
            .values_list('dropdown_key', flat=True)
            .distinct()
            .order_by('dropdown_key')
        )
        return Response(list(keys))

    @action(detail=False, methods=['post'])
    def reorder(self, request):
        """POST [{id:1, order:0}, {id:2, order:1}, …] → bulk reorder"""
        moved = []
        for item in request.data:
            before = DropdownOption.objects.filter(pk=item['id']).values_list('order', flat=True).first()
            if DropdownOption.objects.filter(pk=item['id']).update(order=item['order']) and before != item['order']:
                moved.append([item['id'], before, item['order']])
        if moved:
            _audit(request, 'dropdown_option_changed', changes={'order': moved}, note='ترتيب')
        return Response({'detail': 'تم إعادة الترتيب'})

    @action(detail=False, methods=['get'])
    def grouped(self, request):
        """Return all options grouped by dropdown_key."""
        all_opts = DropdownOption.objects.filter(is_active=True).order_by('dropdown_key', 'order')
        result = {}
        for opt in all_opts:
            result.setdefault(opt.dropdown_key, []).append(
                DropdownOptionSerializer(opt).data
            )
        return Response(result)


# ── Appearance / Theme ─────────────────────────────────────────────────────────

# Stored as a single SystemSetting row (key='theme', value_type='json',
# is_public=True). Public GET so the login screen / customer portal can theme
# themselves before authentication; admin-only PUT to change it.
THEME_KEY = 'theme'
DEFAULT_THEME = {
    'primary':    '#022871',   # navy  — brand-600 + generated scale
    'secondary':  '#3880bb',   # sky   — brand-400
    'accent':     '#ea0000',   # red   — danger / brand-red
    'arabicFont': 'cairo',     # cairo | jozoor | tajawal
}
ALLOWED_FONTS = {'cairo', 'jozoor', 'tajawal'}


def _load_theme():
    stored = SystemSetting.get(THEME_KEY, default={}) or {}
    theme = dict(DEFAULT_THEME)
    if isinstance(stored, dict):
        theme.update({k: stored[k] for k in DEFAULT_THEME if k in stored})
    return theme


@api_view(['GET', 'PUT'])
@permission_classes([permissions.AllowAny])
def theme(request):
    """
    GET /api/config/theme/  → current appearance theme (public, unauthenticated).
    PUT /api/config/theme/  → update it (admin only).
    """
    if request.method == 'PUT':
        # Admin only — role lives on request.user.staff_profile (see apps/users)
        profile = getattr(request.user, 'staff_profile', None)
        if not (profile and profile.role == 'admin' and profile.is_active):
            return Response({'detail': 'يتطلب صلاحية مدير'}, status=status.HTTP_403_FORBIDDEN)

        import re
        incoming = request.data or {}
        merged = _load_theme()
        hex_re = re.compile(r'^#[0-9a-fA-F]{6}$')
        for key in ('primary', 'secondary', 'accent'):
            if key in incoming:
                val = str(incoming[key]).strip()
                if not hex_re.match(val):
                    return Response({'detail': f'قيمة لون غير صحيحة: {key}'},
                                    status=status.HTTP_400_BAD_REQUEST)
                merged[key] = val.lower()
        if 'arabicFont' in incoming:
            font = str(incoming['arabicFont']).strip().lower()
            if font not in ALLOWED_FONTS:
                return Response({'detail': 'خط غير مدعوم'}, status=status.HTTP_400_BAD_REQUEST)
            merged['arabicFont'] = font

        import json
        before = _load_theme()
        setting, _ = SystemSetting.objects.update_or_create(
            key=THEME_KEY,
            defaults={
                'value':      json.dumps(merged),
                'value_type': 'json',
                'category':   'general',
                'is_public':  True,
                'label':      'مظهر النظام (الألوان والخط)',
                'description': 'ألوان الهوية البصرية وخط الواجهة — عام لكل المستخدمين',
            },
        )
        changes = {k: [before.get(k), merged[k]] for k in merged if before.get(k) != merged[k]}
        if changes:
            _audit(request, 'theme_changed', setting, changes, note=THEME_KEY)
        return Response(merged)

    return Response(_load_theme())


# ── Pharmacy Profile ───────────────────────────────────────────────────────────

@api_view(['GET', 'PATCH'])
@permission_classes([permissions.IsAuthenticated, RouteModulePermission])
def pharmacy_profile(request):
    """
    GET  /api/config/pharmacy/ → pharmacy profile + active branches
    PATCH /api/config/pharmacy/ → update pharmacy profile fields
    """
    from apps.branches.models import Branch

    if request.method == 'PATCH':
        denied = deny_unless(request, 'settings', 'edit')
        if denied:
            return denied
        profile = PharmacyProfile.get()
        allowed = {
            'name_ar', 'name_en', 'tagline_ar', 'website',
            'whatsapp_number', 'call_center_numbers', 'extra_footer_ar',
        }
        changes = {}
        for field, value in request.data.items():
            if field in allowed:
                before = getattr(profile, field)
                setattr(profile, field, value)
                if before != value:
                    changes[field] = [_short(before), _short(value)]
        profile.save()
        if changes:
            _audit(request, 'pharmacy_profile_changed', profile, changes)

    profile  = PharmacyProfile.get()
    # Only live, not-paused branches appear on customer receipts/WhatsApp
    branches = list(
        Branch.objects.live()
        .filter(is_operational=True)
        .order_by('name')
        .values('id', 'name', 'name_ar', 'address', 'phone')
    )

    return Response({
        'name_ar':             profile.name_ar,
        'name_en':             profile.name_en,
        'tagline_ar':          profile.tagline_ar,
        'website':             profile.website,
        'whatsapp_number':     profile.whatsapp_number,
        'call_center_numbers': profile.call_center_list(),
        'extra_footer_ar':     profile.extra_footer_ar,
        'branches':            branches,
    })
