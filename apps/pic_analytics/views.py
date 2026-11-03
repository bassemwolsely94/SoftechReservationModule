"""
apps/pic_analytics/views.py — mounted at /api/pic-analytics/ (doc 33)

  GET   access/ options/ overview/ pics/ groups/<kind>/ retention/ retention/overdue/
  GET   calls/center/ calls/missed/ calls/missed/rows/ calls/unanswered/   (management only)
  GET   numbers/ numbers/conversions/ numbers/labels/   POST numbers/label/ numbers/labels/<id>/delete/ numbers/<number_id>/dial/ calls/missed/<id>/dial/
  GET   export/                    audited .xlsx
  GET|POST exclusions/  GET exclusions/suggestions/  POST exclusions/<id>/remove/   PIC exclusion list (management only)
  GET|POST grants/                 named branch managers (admin only)
  POST     grants/<id>/revoke/
  GET      grants/candidates/?q=   staff to grant

Every rule is enforced here; the screen only hides what the user cannot do.
"""
from django.db import transaction
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
from .queries.ordering import parse_ordering, sort_items
from .queries.retention import MAX_PAGE_SIZE, _int_param
from .settings import DEFAULTS, setting


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
    from django.db import IntegrityError, transaction

    from apps.users.models import StaffProfile
    try:
        staff_id = int(request.data.get('staff_id'))
    except (TypeError, ValueError):
        return _bad('معرّف الموظف غير صالح — invalid staff_id')
    staff = StaffProfile.objects.filter(pk=staff_id, is_active=True).first()
    if staff is None:
        return _bad('موظف غير موجود — unknown staff')
    try:
        with transaction.atomic():
            if PicAnalyticsAccess.objects.filter(staff=staff, revoked_at__isnull=True).exists():
                return _bad('لديه الصلاحية بالفعل — already granted')
            g = PicAnalyticsAccess.objects.create(staff=staff, granted_by=acc.profile,
                                                  note=str(request.data.get('note') or '')[:255])
            from apps.audit.models import AuditLog
            AuditLog.log('pic_analytics_access_granted', user=acc.profile, obj=g, note=g.note, request=request,
                         extra={'staff_id': staff.pk, 'staff': staff.full_name})
    except IntegrityError:                     # a concurrent grant won the unique constraint
        return _bad('لديه الصلاحية بالفعل — تم منحها للتو')
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


# ── the PIC exclusion list (management only; doc 33 §15) ────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def exclusions(request):
    acc = Access(request)
    if not acc.can_view or not acc.can_manage_exclusions:
        return _deny()
    from . import exclusions as ex
    if request.method == 'GET':
        return Response({'rows': ex.exclusion_rows()})
    try:
        x = ex.add_exclusion(request.data.get('pic'), request.data.get('reason'), acc.profile, request=request)
    except ex.ExclusionError as exc:
        return _bad(str(exc))
    return Response(ex.exclusion_json(x), status=201)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def exclusion_remove(request, pk):
    acc = Access(request)
    if not acc.can_view or not acc.can_manage_exclusions:
        return _deny()
    from . import exclusions as ex
    x = ex.remove_exclusion(pk, acc.profile, request=request, note=request.data.get('note'))
    if x is None:
        return Response({'detail': 'غير موجود — Not found'}, status=404)
    return Response({'id': x.pk, 'pic': x.pic, 'removed_at': x.removed_at})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def exclusion_suggestions(request):
    from . import exclusions as ex
    acc = Access(request)
    if not acc.can_view or not acc.can_manage_exclusions:
        return _deny()
    return _run(request, lambda f, a: {'rows': ex.suggestions(f, a)})


# ── the dashboard's read endpoints ───────────────────────────────────────────────────────────────
# /api/pic-analytics/ is exempt from the RBAC middleware: every view checks Access itself.

def _thresholds():
    """The tunables the screen quotes; a bad setting value falls back to its default, never a 500."""
    out = {}
    for key, name, cast in (('pic_loyal_months', 'loyal_months', int), ('pic_overdue_factor', 'overdue_factor', float),
                            ('pic_call_return_hours', 'return_hours', int), ('pic_call_purchase_days', 'purchase_days', int)):
        try:
            out[name] = cast(setting(key))
        except (TypeError, ValueError):
            out[name] = cast(DEFAULTS[key])
    return out


def _run(request, fn, calls=False):
    """Access gate + filter bar + error mapping shared by every read endpoint. fn(f, access) -> data."""
    acc = Access(request)
    if not acc.can_view or (calls and not acc.sees_calls_tabs):
        return _deny()
    try:
        f = Filters.from_request(request, acc, live=calls)
        data = fn(f, acc)
        if isinstance(data, dict):
            data['period'] = {'from': f.start, 'to': f.end, 'data_from': f.data_from,
                              'data_to': f.data_to, 'clamped': f.clamped}
            # the tunables the on-screen explanations quote (the screen never hard-codes them)
            data['thresholds'] = _thresholds()
        return Response(data)
    except FilterError as exc:
        return _bad(str(exc))
    except PermissionError as exc:
        return _deny(str(exc))
    except ValueError as exc:
        return _bad(str(exc))


# whitelisted `ordering` fields of the lists sorted here (the number itself is masked, so not sortable)
NUMBER_ORDERS = {'kind': lambda r: r['kind'], 'calls_in': lambda r: r['calls_in'], 'calls_out': lambda r: r['calls_out'],
                 'answered': lambda r: r['answered'], 'missed': lambda r: r['missed'],
                 'first_call': lambda r: r['first_call'], 'last_call': lambda r: r['last_call'],
                 'talk_seconds': lambda r: r['talk_seconds'],
                 'last_agent': lambda r: (r['last_agent'] or {}).get('staff_name') or (r['last_agent'] or {}).get('pbx_name')
                                          or (r['last_agent'] or {}).get('agent_ext')}
LABEL_ORDERS = {'label': lambda r: r['label_display'], 'note': lambda r: r['note'],
                'created_by': lambda r: r['created_by'], 'created_at': lambda r: r['created_at']}


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
        # `ordering` (DRF style) like every other list; `order` stays as a backward-compatible alias
        raw = request.query_params.get('ordering') or request.query_params.get('order') or ''
        key, desc = parse_ordering(raw, q_pics.ORDERS)          # unknown field -> 400
        return q_pics.pic_rows(f, acc, (('-' if desc else '') + key) if key else '-net', page, size)
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
        return q_retention.overdue_list(f, acc, page, size, request.query_params.get('ordering', ''))
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
        return q_missed.missed_rows(f, acc, bool(only), page, size, request.query_params.get('ordering', ''))
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
        key, desc = parse_ordering(request.query_params.get('ordering', ''), NUMBER_ORDERS)
        if not key:
            return _opaque(q_numbers.new_numbers(f, acc, page, size))
        data = q_numbers.new_numbers(f, acc, 1, None)             # every number, then sort, then page
        rows = sort_items(data['rows'], NUMBER_ORDERS[key], desc)
        return _opaque({'count': data['count'], 'rows': rows[(page - 1) * size: page * size]})
    return _run(request, go, calls=True)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def numbers_conversions(request):
    return _run(request, lambda f, acc: _opaque(q_numbers.conversions(f, acc)), calls=True)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def numbers_labels(request):
    acc = Access(request)
    if not acc.can_view or not acc.sees_calls_tabs:
        return _deny()
    try:
        page, size = _paging(request)
        key, desc = parse_ordering(request.query_params.get('ordering', ''), LABEL_ORDERS)
        if not key:
            return Response(_opaque(q_numbers.labelled_numbers(acc, page, size)))
        rows, got = [], 1                                          # a small table: read it all, sort, then page
        while True:
            part = q_numbers.labelled_numbers(acc, got, MAX_PAGE_SIZE)
            rows += part['rows']
            if len(rows) >= part['count'] or not part['rows']:
                break
            got += 1
        rows = sort_items(rows, LABEL_ORDERS[key], desc)
        return Response(_opaque({'count': len(rows), 'rows': rows[(page - 1) * size: page * size]}))
    except PermissionError as exc:
        return _deny(str(exc))
    except ValueError as exc:
        return _bad(str(exc))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def numbers_label_delete(request, label_id):
    acc = Access(request)
    if not acc.can_view or not acc.sees_calls_tabs:
        return _deny()
    if q_numbers.unlabel_number(label_id, acc.profile, request=request) is None:
        return Response({'detail': 'غير موجود — Not found'}, status=404)
    return Response({'label_id': label_id, 'deleted': True})


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
def missed_callback(request, call_id):
    """Schedule a call-back for a missed call: a CallLog(status='callback') that lands in the
    call center's existing pending-callbacks list. The browser never gets the raw number."""
    acc = Access(request)
    if not acc.can_view or not acc.sees_calls_tabs:
        return _deny()
    from django.utils.dateparse import parse_datetime

    from apps.callcenter.models import CallLog
    from apps.customers.access import mask
    from apps.pbx.models import CdrCall
    call = (CdrCall.objects.filter(pk=call_id, is_transfer=False, direction='inbound')
            .exclude(status='answered').exclude(customer_number='').first())
    if call is None:
        return Response({'detail': 'غير موجود — Not found'}, status=404)
    raw_due = request.data.get('due')
    due = parse_datetime(str(raw_due)) if raw_due else None
    if due is None:
        return _bad('موعد المعاودة مطلوب — due is required')
    if timezone.is_naive(due):
        due = timezone.make_aware(due)
    if due <= timezone.now():
        return _bad('موعد المعاودة يجب أن يكون في المستقبل')
    note = str(request.data.get('note') or '').strip()
    if len(note) > 500:
        return _bad('الملاحظة أطول من 500 حرف')
    with transaction.atomic():
        # lock every call of this number, then re-check: two clicks can never book two call-backs
        locked = list(CdrCall.objects.select_for_update().filter(
            Q(pk=call.pk) | Q(phone_key=call.phone_key) if call.phone_key else Q(pk=call.pk)).order_by('pk'))
        call = next(c for c in locked if c.pk == call.pk)
        if q_missed.callback_dues([call]):
            return Response({'detail': 'يوجد موعد معاودة مجدول لهذا الرقم بالفعل'}, status=status.HTTP_409_CONFLICT)
        log = CallLog.objects.create(
            phone_number=call.customer_number, customer=call.customer, direction='inbound',
            status='callback', callback_due=due, handled_by=acc.profile, notes=note, source='manual')
    from apps.audit.models import AuditLog
    AuditLog.log('pic_analytics_callback_scheduled', user=acc.profile, obj=log, request=request,
                 note='missed call back', extra={'call_id': call.pk, 'calllog_id': log.pk,
                                                 'callback_due': due.isoformat(), 'note': note})
    return Response({'id': log.pk, 'callback_due': log.callback_due.isoformat(),
                     'number': mask(call.customer_number)})


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
        calls_f = Filters.from_request(request, acc, live=True) if acc.sees_calls_tabs else None
        data, counts = build_workbook(f, acc, exported_by=acc.profile.full_name if acc.profile else '',
                                      calls_f=calls_f)
    except ValueError as exc:                  # FilterError is a ValueError
        return _bad(str(exc))
    name = f'pic-analytics_{f.start.isoformat()}_{f.end.isoformat()}.xlsx'
    from apps.audit.models import AuditLog
    AuditLog.log('pic_analytics_exported', user=acc.profile, request=request, note=name,
                 extra={'filters': filters_dict(f), 'rows': counts})
    resp = HttpResponse(data, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = f'attachment; filename="{name}"'
    return resp
