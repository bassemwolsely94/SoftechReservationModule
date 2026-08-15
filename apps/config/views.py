from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from django.db.models import Prefetch

from .models import SystemSetting, DropdownOption, PharmacyProfile
from .serializers import (
    SystemSettingSerializer, SystemSettingUpdateSerializer,
    DropdownOptionSerializer, DropdownOptionWriteSerializer,
)


class SystemSettingViewSet(viewsets.ModelViewSet):
    """
    GET  /api/config/settings/              → list all
    GET  /api/config/settings/?category=X   → filter by category
    GET  /api/config/settings/{id}/         → detail
    PATCH /api/config/settings/{id}/        → update value
    POST /api/config/settings/by_key/       → bulk fetch by key names
    """
    queryset         = SystemSetting.objects.all()
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action in ('update', 'partial_update'):
            return SystemSettingUpdateSerializer
        return SystemSettingSerializer

    def get_queryset(self):
        qs = super().get_queryset()
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
                s.value = str(value)
                s.save(update_fields=['value', 'updated_at'])
                updated.append(key)
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
    permission_classes = [permissions.IsAuthenticated]

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
        for item in request.data:
            DropdownOption.objects.filter(pk=item['id']).update(order=item['order'])
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
        SystemSetting.objects.update_or_create(
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
        return Response(merged)

    return Response(_load_theme())


# ── Pharmacy Profile ───────────────────────────────────────────────────────────

@api_view(['GET', 'PATCH'])
@permission_classes([permissions.IsAuthenticated])
def pharmacy_profile(request):
    """
    GET  /api/config/pharmacy/ → pharmacy profile + active branches
    PATCH /api/config/pharmacy/ → update pharmacy profile fields
    """
    from apps.branches.models import Branch

    if request.method == 'PATCH':
        profile = PharmacyProfile.get()
        allowed = {
            'name_ar', 'name_en', 'tagline_ar', 'website',
            'whatsapp_number', 'call_center_numbers', 'extra_footer_ar',
        }
        for field, value in request.data.items():
            if field in allowed:
                setattr(profile, field, value)
        profile.save()

    profile  = PharmacyProfile.get()
    # Only active + operational branches appear on customer receipts/WhatsApp
    branches = list(
        Branch.objects
        .filter(is_active=True, is_operational=True)
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
