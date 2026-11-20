"""C23 — /api/personal/saved-views/: per-user saved filters on worklist screens.

Own data only (the `personal` prefix is EXEMPT in core/middleware/module_access.py and listed in
apps/tests/security/baselines/open_to_all_staff.txt): every staff member may keep views for any
allow-listed screen, because a view holds filters, not data — the screen's own endpoints still apply
their module grants and branch scope when the filters are used. You read your own views plus views a
colleague shared with YOUR role; you change or delete only your own (another person's view answers
404, so ids are not probed). Sharing is to your own role only.
"""
from django.db import IntegrityError, transaction
from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import SavedView
from .saved_views import MAX_VIEWS_PER_SCREEN, SCREENS, clean_filters, valid_role


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


def _row(v, profile):
    mine = v.staff_id == profile.id
    return {'id': v.id, 'screen': v.screen, 'name': v.name, 'filters': v.filters,
            'is_default': bool(mine and v.is_default), 'shared': bool(v.shared_role), 'mine': mine,
            'owner_name': '' if mine else v.staff.full_name}


def _name(data):
    return str(data.get('name') or '').strip()[:80]


def _set_default(profile, view):
    SavedView.objects.filter(staff=profile, screen=view.screen, is_default=True).exclude(pk=view.pk) \
        .update(is_default=False)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def saved_views(request):
    profile = _profile(request)
    if not profile:
        return Response({'detail': 'لا يوجد ملف موظف'}, status=403)
    if request.method == 'GET':
        screen = request.query_params.get('screen') or ''
        if screen not in SCREENS:
            return Response({'detail': 'شاشة غير معروفة.'}, status=400)
        mine = Q(staff=profile)
        role = getattr(profile, 'role', '') or ''
        shared = Q(shared_role=role) & ~Q(staff=profile) if valid_role(role) else Q(pk__in=[])
        qs = SavedView.objects.filter(Q(screen=screen) & (mine | shared)).select_related('staff__user')
        rows = [_row(v, profile) for v in qs]
        rows.sort(key=lambda r: (not r['mine'], r['name']))
        return Response({'results': rows})

    data = request.data
    screen = str(data.get('screen') or '')
    if screen not in SCREENS:
        return Response({'detail': 'شاشة غير معروفة.'}, status=400)
    name = _name(data)
    if not name:
        return Response({'detail': 'اكتب اسماً للعرض.'}, status=400)
    try:
        filters, dropped = clean_filters(screen, data.get('filters') or {})
    except ValueError as e:
        return Response({'detail': str(e)}, status=400)
    if SavedView.objects.filter(staff=profile, screen=screen).count() >= MAX_VIEWS_PER_SCREEN:
        return Response({'detail': f'الحد الأقصى {MAX_VIEWS_PER_SCREEN} عرضاً لكل شاشة.'}, status=400)
    role = getattr(profile, 'role', '') or ''
    try:
        with transaction.atomic():
            v = SavedView(staff=profile, screen=screen, name=name, filters=filters,
                          shared_role=role if (data.get('shared') and valid_role(role)) else '')
            if data.get('is_default'):
                SavedView.objects.filter(staff=profile, screen=screen, is_default=True).update(is_default=False)
                v.is_default = True
            v.save()
    except IntegrityError:
        return Response({'detail': 'يوجد عرض بنفس الاسم.'}, status=400)
    v.staff = profile
    return Response({**_row(v, profile), 'dropped': dropped}, status=201)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def saved_view_detail(request, pk):
    profile = _profile(request)
    if not profile:
        return Response({'detail': 'لا يوجد ملف موظف'}, status=403)
    v = SavedView.objects.filter(pk=pk, staff=profile).first()
    if v is None:
        return Response({'detail': 'غير موجود'}, status=404)
    if request.method == 'DELETE':
        v.delete()
        return Response(status=204)
    data = request.data
    dropped = []
    if 'name' in data:
        if not _name(data):
            return Response({'detail': 'اكتب اسماً للعرض.'}, status=400)
        v.name = _name(data)
    if 'filters' in data:
        try:
            v.filters, dropped = clean_filters(v.screen, data.get('filters') or {})
        except ValueError as e:
            return Response({'detail': str(e)}, status=400)
    if 'shared' in data:
        role = getattr(profile, 'role', '') or ''
        v.shared_role = role if (data.get('shared') and valid_role(role)) else ''
    try:
        with transaction.atomic():
            if 'is_default' in data:
                v.is_default = bool(data.get('is_default'))
                if v.is_default:
                    _set_default(profile, v)
            v.save()
    except IntegrityError:
        return Response({'detail': 'يوجد عرض بنفس الاسم.'}, status=400)
    return Response({**_row(v, profile), 'dropped': dropped})
