"""
apps/pic_analytics/views.py — mounted at /api/pic-analytics/ (doc 33)

  GET   access/ options/ overview/ pics/ groups/<kind>/ retention/ retention/overdue/
  GET   calls/center/ calls/missed/ calls/missed/rows/ calls/unanswered/   (management only)
  GET   numbers/ numbers/conversions/   POST numbers/label/ numbers/<number_id>/dial/ calls/missed/<id>/dial/
  GET   export/                    audited .xlsx
  GET|POST grants/                 named branch managers (admin only)
  POST     grants/<id>/revoke/
  GET      grants/candidates/?q=   staff to grant

Every rule is enforced here; the screen only hides what the user cannot do.
"""
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .access import Access
from .models import PicAnalyticsAccess
from .queries import groups as q_groups
from .queries import missed as q_missed
from .queries import numbers as q_numbers
from .queries import options as q_options
from .queries import overview as q_overview
from .queries import pics as q_pics
from .queries import retention as q_retention
from .queries.calls import call_center
from .queries.filters import FilterError, Filters
from .queries.retention import MAX_PAGE_SIZE, _int_param


def _deny(msg='ليس لديك صلاحية — Not allowed'):
    return Response({'detail': msg}, status=status.HTTP_403_FORBIDDEN)


def _bad(msg):
    return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)


def _grant_json(g):
    return {'id': g.id, 'staff_id': g.staff_id, 'staff_name': g.staff.full_name,
            'role': g.staff.role, 'branch': g.staff.branch_name, 'note': g.note,
            'granted_by': g.granted_by.full_name if g.granted_by_id else '', 'granted_at': g.granted_at,
            'revoked_by': g.revoked_by.full_name if g.revoked_by_id else '', 'revoked_at': g.revoked_at}


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def grants(request):
    acc = Access(request)
    if not acc.can_manage_access:
        return _deny()
    if request.method == 'GET':
        qs = PicAnalyticsAccess.objects.select_related('staff__user', 'staff__branch', 'granted_by__user',
                                                       'revoked_by__user')[:200]
        return Response({'rows': [_grant_json(g) for g in qs]})
    from apps.users.models import StaffProfile
    staff = StaffProfile.objects.filter(pk=request.data.get('staff_id'), is_active=True).first()
    if staff is None:
        return _bad('موظف غير موجود — unknown staff')
    if PicAnalyticsAccess.objects.filter(staff=staff, revoked_at__isnull=True).exists():
        return _bad('لديه الصلاحية بالفعل — already granted')
    g = PicAnalyticsAccess.objects.create(staff=staff, granted_by=acc.profile,
                                          note=str(request.data.get('note') or '')[:255])
    from apps.audit.models import AuditLog
    AuditLog.log('pic_analytics_access_granted', user=acc.profile, obj=g, note=g.note, request=request,
                 extra={'staff_id': staff.pk, 'staff': staff.full_name})
    return Response(_grant_json(g), status=201)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def grant_revoke(request, pk):
    acc = Access(request)
    if not acc.can_manage_access:
        return _deny()
    g = PicAnalyticsAccess.objects.filter(pk=pk, revoked_at__isnull=True).select_related('staff__user').first()
    if g is None:
        return Response({'detail': 'غير موجود — Not found'}, status=404)
    g.revoked_at, g.revoked_by = timezone.now(), acc.profile
    g.save(update_fields=['revoked_at', 'revoked_by'])
    from apps.audit.models import AuditLog
    AuditLog.log('pic_analytics_access_revoked', user=acc.profile, obj=g, request=request,
                 note=str(request.data.get('note') or '')[:255], extra={'staff_id': g.staff_id})
    return Response(_grant_json(g))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def grant_candidates(request):
    acc = Access(request)
    if not acc.can_manage_access:
        return _deny()
    from apps.users.models import StaffProfile
    q = (request.query_params.get('q') or '').strip()
    granted = set(PicAnalyticsAccess.objects.filter(revoked_at__isnull=True).values_list('staff_id', flat=True))
    qs = StaffProfile.objects.filter(is_active=True).exclude(role='admin').select_related('user', 'branch')
    if q:
        qs = qs.filter(Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q) |
                       Q(user__username__icontains=q) | Q(softech_username__icontains=q) |
                       Q(softech_user_id=q))
    rows = [{'id': p.id, 'name': p.full_name, 'role': p.role, 'branch': p.branch_name,
             'granted': p.id in granted} for p in qs.order_by('branch__softech_branch_id')[:30]]
    return Response({'rows': rows})


# ── the dashboard's read endpoints ───────────────────────────────────────────────────────────────
# /api/pic-analytics/ is exempt from the RBAC middleware: every view checks Access itself.

def _run(request, fn, calls=False):
    """Access gate + filter bar + error mapping shared by every read endpoint. fn(f, access) -> data."""
    acc = Access(request)
    if not acc.can_view or (calls and not acc.sees_calls_tabs):
        return _deny()
    try:
        f = Filters.from_request(request, acc)
        return Response(fn(f, acc))
    except FilterError as exc:
        return _bad(str(exc))
    except PermissionError as exc:
        return _deny(str(exc))
    except ValueError as exc:
        return _bad(str(exc))


def _paging(request, default_size=50):
    q = request.query_params
    return (_int_param(q.get('page', 1), 'الصفحة', 1),
            _int_param(q.get('page_size', default_size), 'حجم الصفحة', 1, MAX_PAGE_SIZE))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def access_info(request):
    acc = Access(request)
    if not acc.can_view:
        return _deny()
    from apps.customers.models import Customer
    out = acc.as_dict()
    out['new_reliable_from'] = (None if Customer.objects.filter(softech_created_at__isnull=False).exists()
                                else q_overview.NEW_RELIABLE_FROM)
    return Response(out)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def filter_options(request):
    return _run(request, q_options.filter_options)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def overview(request):
    return _run(request, q_overview.overview)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def pic_list(request):
    def go(f, acc):
        page, size = _paging(request)
        return q_pics.pic_rows(f, acc, request.query_params.get('order') or '-net', page, size)
    return _run(request, go)


GROUPS = {'branch': q_groups.by_branch, 'salesperson': q_groups.by_salesperson,
          'channel': q_groups.by_channel, 'category': q_groups.by_category}


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def group_list(request, kind):
    acc = Access(request)
    if not acc.can_view:
        return _deny()
    if kind not in GROUPS:
        return Response({'detail': 'غير موجود — Not found'}, status=404)
    return _run(request, GROUPS[kind])


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def retention(request):
    return _run(request, lambda f, acc: {'frequency': q_retention.frequency(f, acc),
                                         'retention': q_retention.retention_summary(f, acc),
                                         'cohorts': q_retention.cohorts(f, acc)})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def retention_overdue(request):
    def go(f, acc):
        page, size = _paging(request)
        return q_retention.overdue_list(f, acc, page, size)
    return _run(request, go)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def calls_center(request):
    return _run(request, call_center, calls=True)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def calls_missed(request):
    return _run(request, q_missed.missed_summary, calls=True)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def calls_missed_rows(request):
    def go(f, acc):
        only = _int_param(request.query_params.get('only_not_returned', 0), 'غير المردودة', 0, 1)
        page, size = _paging(request)
        return q_missed.missed_rows(f, acc, bool(only), page, size)
    return _run(request, go, calls=True)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def calls_unanswered(request):
    return _run(request, lambda f, acc: {'rows': q_missed.unanswered_summary(f, acc)}, calls=True)


def _opaque(result):
    """The browser never gets a phone key (last 10 digits): swap it for the id of that number's
    latest call, which the server resolves back on dial/label."""
    from apps.pbx.models import CdrCall
    rows = result.get('rows', [])
    keys = {r['phone_key'] for r in rows if 'phone_key' in r}
    latest = {}
    if keys:
        for pk, key in (CdrCall.objects.filter(phone_key__in=keys, is_transfer=False)
                        .exclude(customer_number='').order_by('call_at', 'pk')
                        .values_list('pk', 'phone_key')):
            latest[key] = pk                                  # last assignment = latest call
    for row in rows:
        if 'phone_key' in row:
            row['number_id'] = latest.get(row.pop('phone_key'))
    return result


def _resolve_number_id(number_id):
    """-> the still-unlinked CdrCall behind a number handle, 'gone' or 'linked'."""
    from apps.pbx.models import CdrCall
    try:
        pk = int(number_id)
    except (TypeError, ValueError):
        return 'gone'
    call = (CdrCall.objects.filter(pk=pk, is_transfer=False).exclude(phone_key='').first())
    if call is None:
        return 'gone'
    return call if call.pic_match == 'none' else 'linked'


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def numbers_list(request):
    def go(f, acc):
        page, size = _paging(request)
        return _opaque(q_numbers.new_numbers(f, acc, page, size))
    return _run(request, go, calls=True)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def numbers_conversions(request):
    return _run(request, lambda f, acc: _opaque(q_numbers.conversions(f, acc)), calls=True)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def numbers_label(request):
    acc = Access(request)
    if not acc.can_view or not acc.sees_calls_tabs:
        return _deny()
    call = _resolve_number_id(request.data.get('number_id'))
    if call == 'gone':
        return _bad('معرّف الرقم غير صالح — Invalid number_id')
    if call == 'linked':
        return _bad('الرقم أصبح عميلاً')
    try:
        pl = q_numbers.label_number(call.phone_key, request.data.get('label'),
                                    request.data.get('note'), acc.profile)
    except ValueError as exc:
        return _bad(str(exc))
    return Response({'number_id': request.data.get('number_id'), 'label': pl.label, 'note': pl.note})


# ── server-side dial: unknown numbers stay masked, so the browser never receives them ──────────

def _dial(request, acc, number, what, ref):
    from apps.customers.access import mask
    from apps.pbx.actions import DialError, dial_for
    try:
        dial_for(acc.profile, number, request=request)
    except DialError as exc:
        return Response({'detail': exc.detail}, status=exc.status)
    from apps.audit.models import AuditLog
    AuditLog.log('pic_analytics_dialled', user=acc.profile, request=request, note=what, extra=ref)
    return Response({'detail': 'سيرن هاتفك الآن — عند الرد سيُحوَّل إلى الرقم المطلوب', 'number': mask(number)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def missed_dial(request, call_id):
    acc = Access(request)
    if not acc.can_view or not acc.sees_calls_tabs:
        return _deny()
    from apps.pbx.models import CdrCall
    call = (CdrCall.objects.filter(pk=call_id, is_transfer=False, direction='inbound')
            .exclude(status='answered').exclude(customer_number='').first())
    if call is None:
        return Response({'detail': 'غير موجود — Not found'}, status=404)
    return _dial(request, acc, call.customer_number, 'missed call',
                 {'call_id': call.pk, 'phone_key': call.phone_key})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def number_dial(request, number_id):
    acc = Access(request)
    if not acc.can_view or not acc.sees_calls_tabs:
        return _deny()
    call = _resolve_number_id(number_id)
    if call == 'linked':
        return _bad('الرقم أصبح عميلاً')
    if call == 'gone' or not call.customer_number:
        return Response({'detail': 'غير موجود — Not found'}, status=404)
    return _dial(request, acc, call.customer_number, 'new number', {'call_id': call.pk})


# ── Excel ────────────────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def export(request):
    from django.http import HttpResponse

    from .export import build_workbook, filters_dict
    acc = Access(request)
    if not acc.can_view or not acc.can_export:
        return _deny()
    try:
        f = Filters.from_request(request, acc)
        data, counts = build_workbook(f, acc, exported_by=acc.profile.full_name if acc.profile else '')
    except ValueError as exc:                  # FilterError is a ValueError
        return _bad(str(exc))
    name = f'pic-analytics_{f.start.isoformat()}_{f.end.isoformat()}.xlsx'
    from apps.audit.models import AuditLog
    AuditLog.log('pic_analytics_exported', user=acc.profile, request=request, note=name,
                 extra={'filters': filters_dict(f), 'rows': counts})
    resp = HttpResponse(data, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = f'attachment; filename="{name}"'
    return resp
