"""
apps/audit/usage.py

P-57 screen-usage telemetry (docs/product-review/06_SPEC_P-57).

POST /api/audit/screen-view/   {route, tab?}   any signed-in staff member; 204
GET  /api/audit/usage/?view=screens|modules|staff&days=28&known=/a,/b

Who sees what (server-side):
  • admin, or a role holding hr/approve  → everything, incl. the per-staff view
  • pharmacist / supervisor (branch managers) → screens + modules for their own branch only
  • everyone else → 403
"""
import datetime
import re

from django.db.models import Count, Max
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import ScreenView

DEDUP_SECONDS = 30
ZERO_USE_DAYS = 60
BRANCH_MANAGER_ROLES = ('pharmacist', 'supervisor')

_UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)


def route_pattern(raw):
    """'/transits/123?x=1' → '/transits/:id'. Any segment that is a number, a UUID or
    carries 4+ digits (phones, codes, receipt numbers) becomes ':id'."""
    path = str(raw or '').split('?', 1)[0].split('#', 1)[0].strip()
    out = []
    for seg in path.split('/'):
        if not seg:
            continue
        if seg.isdigit() or _UUID.match(seg) or sum(c.isdigit() for c in seg) >= 4:
            out.append(':id')
        else:
            out.append(seg[:40])
    return ('/' + '/'.join(out))[:200]


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


def _sees_people(profile):
    return bool(profile and profile.is_active
                and (profile.role == 'admin' or profile.can_do('hr', 'approve')))


def _module(route):
    return route.strip('/').split('/', 1)[0] or '/'


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def screen_view(request):
    profile = _profile(request)
    if not request.data.get('route'):
        return Response({'detail': 'route required'}, status=status.HTTP_400_BAD_REQUEST)
    if profile is None:
        return Response(status=status.HTTP_204_NO_CONTENT)
    route = route_pattern(request.data.get('route'))
    tab = str(request.data.get('tab') or '')[:60]
    since = timezone.now() - datetime.timedelta(seconds=DEDUP_SECONDS)
    if not ScreenView.objects.filter(staff=profile, route=route, tab=tab, at__gte=since).exists():
        ScreenView.objects.create(staff=profile, role=profile.role, branch_id=profile.branch_id,
                                  route=route, tab=tab)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def usage_report(request):
    profile = _profile(request)
    people = _sees_people(profile)
    manager = bool(profile and profile.is_active and profile.role in BRANCH_MANAGER_ROLES
                   and profile.branch_id)
    if not (people or manager):
        return Response({'detail': 'ليس لديك صلاحية لهذا التقرير'}, status=status.HTTP_403_FORBIDDEN)

    view = request.query_params.get('view', 'screens')
    try:
        days = max(1, min(int(request.query_params.get('days', 28)), 365))
    except (TypeError, ValueError):
        days = 28
    now = timezone.now()
    qs = ScreenView.objects.all()
    if not people:
        qs = qs.filter(branch_id=profile.branch_id)        # a branch manager: own branch only
    else:
        if request.query_params.get('branch'):
            qs = qs.filter(branch_id=request.query_params['branch'])
        if request.query_params.get('role'):
            qs = qs.filter(role=request.query_params['role'])
    window = qs.filter(at__gte=now - datetime.timedelta(days=days))

    if view == 'staff':
        if not people:
            return Response({'detail': 'التقرير الفردي للإدارة والموارد البشرية فقط'},
                            status=status.HTTP_403_FORBIDDEN)
        rows = (window.values('staff_id', 'staff__user__first_name', 'staff__user__username', 'role',
                              'branch__name_ar')
                .annotate(visits=Count('id'), screens=Count('route', distinct=True), last_at=Max('at'))
                .order_by('-visits'))
        return Response({'days': days, 'rows': [{
            'staff_id': r['staff_id'],
            'name': r['staff__user__first_name'] or r['staff__user__username'],
            'role': r['role'], 'branch': r['branch__name_ar'] or '',
            'visits': r['visits'], 'screens': r['screens'],
            'last_at': r['last_at'].isoformat() if r['last_at'] else None,
        } for r in rows]})

    if view == 'modules':
        by_module = {}
        for route in window.values_list('route', flat=True):
            m = _module(route)
            by_module.setdefault(m, {'module': m, 'visits': 0, 'users': set()})['visits'] += 1
        week = qs.filter(at__gte=now - datetime.timedelta(days=7))
        for route, staff_id in week.values_list('route', 'staff_id'):
            m = _module(route)
            by_module.setdefault(m, {'module': m, 'visits': 0, 'users': set()})['users'].add(staff_id)
        rows = sorted(({'module': d['module'], 'visits': d['visits'],
                        'weekly_active_users': len(d['users'])} for d in by_module.values()),
                      key=lambda r: (-r['weekly_active_users'], -r['visits']))
        return Response({'days': days, 'rows': rows})

    rows = list(window.values('route').annotate(visits=Count('id'), users=Count('staff', distinct=True))
                .order_by('-visits', 'route'))
    known = [route_pattern(k) for k in (request.query_params.get('known') or '').split(',') if k.strip()]
    used = set(qs.filter(at__gte=now - datetime.timedelta(days=ZERO_USE_DAYS))
               .values_list('route', flat=True).distinct())
    zero_use = sorted({k for k in known
                       if not any(u == k or u.startswith(k.rstrip('/') + '/') for u in used)})
    return Response({'days': days, 'rows': rows, 'zero_use': zero_use})
