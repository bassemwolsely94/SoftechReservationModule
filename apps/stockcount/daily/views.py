"""
apps/stockcount/daily/views.py — /api/stockcount/daily/…  (404 everywhere while DAILY_COUNT_ENABLED is off)

Counter (any logged-in staff, own list only — BLIND: never sees expected, difference or why an item
was picked):
  GET  my/                 today's picks + recounts handed to me
  POST my/count/           {pick_id, counted_qty, physical_expiry?, client_token?}
Reviewers = stock-audit access (apps/stock_audit/access.py): named branch managers for their own
branches; management (stock_audit view/approve) = the central auditor, all branches:
  GET  board/              ?date=&branch=  per-person progress + open differences
  POST picks/<id>/recount/ {assignee_id?, note?}
  POST picks/<id>/accept/  {reason, note?, needs_softech_adjustment?}
  POST picks/<id>/escalate/ {note?}
  GET  report/             ?days=7|30 [&export=xlsx]  completion + differences per branch / person
  POST generate/           {branch_code, date?}  management only
  GET|PATCH settings/      management (PATCH needs stock_audit edit)
"""
import datetime as dt
from collections import defaultdict
from decimal import Decimal

from django.db.models import Q
from django.http import Http404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.stock_audit.access import Access
from apps.stockcount.models import DailyCountPick, DailyCountSettings, StockCountSession
from . import service
from .service import DailyCountError, cairo_today

REMINDER = 'اجرد كل الكمية بالفرع: الرف + المخزن + المحجوز'
STATUS_LABELS = dict(DailyCountPick.STATUS_CHOICES)


def _on():
    if not service.enabled():
        raise Http404


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


def _date(value, default):
    try:
        return dt.date.fromisoformat(value) if value else default
    except ValueError:
        return default


def _f(v):
    return None if v is None else float(v)


def _branch_names():
    from apps.branches.models import Branch
    return {b.softech_branch_id: (b.name_ar or b.name) for b in Branch.objects.all()}


# ── Counter ───────────────────────────────────────────────────────────────────

def _item_info(codes):
    """{item_code: {'barcodes': [...], 'pack_qty': n}} — for matching a camera scan to a line and
    for counting strips/units on the phone."""
    from apps.catalog.models import Item, ItemBarcode
    info = {}
    for code, bc, pq in Item.objects.filter(softech_id__in=codes).values_list('softech_id', 'barcode', 'pack_qty'):
        info[code] = {'barcodes': [bc] if bc else [], 'pack_qty': int(pq or 1)}
    for code, bc in ItemBarcode.objects.filter(item__softech_id__in=codes).values_list('item__softech_id', 'barcode'):
        if code in info and bc and bc not in info[code]['barcodes']:
            info[code]['barcodes'].append(bc)
    return info


def _blind(pick, profile, info=None):
    extra = (info or {}).get(pick.item_code) or {'barcodes': [], 'pack_qty': 1}
    return {
        'pick_id': pick.pk, 'item_code': pick.item_code, 'item_name': pick.item_name,
        'barcodes': extra['barcodes'], 'pack_qty': extra['pack_qty'],
        # no status / label: counted, accepted and escalated must look the same to the counter
        'ask_expiry': pick.ask_expiry,
        'done': pick.status not in service.OPEN_FOR_COUNT,
        'is_recount': pick.status == 'recount',
        'can_count': service.can_count(pick, profile),
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_list(request):
    _on()
    p = _profile(request)
    today = cairo_today()
    if p is None or not p.is_active:
        return Response({'date': today.isoformat(), 'picks': [], 'progress': {'done': 0, 'total': 0},
                         'reminder': REMINDER})
    sessions = service.counter_sessions(p)
    if sessions:
        today = max(x.count_date for x in sessions)
    picks = (DailyCountPick.objects.select_related('session')
             .filter(Q(session__in=sessions) | Q(recount_by=p, status='recount'))
             .order_by('item_name').distinct())
    picks = list(picks)
    info = _item_info([x.item_code for x in picks])
    rows = [_blind(x, p, info) for x in picks]
    # recounts first, then the not-yet-counted, then the done ones
    rows.sort(key=lambda r: (not r['is_recount'], r['done'], r['item_name']))
    done = sum(1 for r in rows if r['done'])
    return Response({'date': today.isoformat(), 'picks': rows, 'reminder': REMINDER,
                     'progress': {'done': done, 'total': len(rows)}})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def my_count(request):
    _on()
    p = _profile(request)
    if p is None or not p.is_active:
        return Response({'detail': 'هذا الصنف ليس ضمن جردك'}, status=404)
    try:
        pick = DailyCountPick.objects.select_related('session').get(
            Q(session__assigned_to=p) | Q(recount_by=p), pk=int(request.data.get('pick_id')))
    except (DailyCountPick.DoesNotExist, TypeError, ValueError):
        return Response({'detail': 'هذا الصنف ليس ضمن جردك'}, status=404)
    token = str(request.data.get('client_token') or '').strip()[:64] or None
    try:
        service.record_count(pick, p, request.data.get('counted_qty'),
                             physical_expiry=request.data.get('physical_expiry') or None, client_token=token)
    except DailyCountError as e:
        return Response({'detail': str(e)}, status=400)
    pick.refresh_from_db()
    return Response({'pick_id': pick.pk, 'done': True, 'status': 'counted' if pick.status != 'recount' else 'recount'})


# ── Reviewers ─────────────────────────────────────────────────────────────────

def _reviewer(request):
    acc = Access(request)
    if not acc.can_review:
        return None
    return acc


def _scoped_picks(acc):
    return acc.scope(DailyCountPick.objects.filter(session__mode='daily'), field='session__branch_code')


def _diff_row(pick, acc, names, tol):
    a = pick.latest_attempt
    s = pick.session
    return {
        'pick_id': pick.pk, 'item_code': pick.item_code, 'item_name': pick.item_name,
        'branch_code': s.branch_code, 'branch_name': names.get(s.branch_code, s.branch_code),
        'date': s.count_date.isoformat() if s.count_date else None,
        'assigned_to': s.assigned_to.full_name if s.assigned_to else '',
        'counted_by': a.counted_by.full_name if a and a.counted_by else '',
        'expected_qty': _f(a.expected_qty), 'counted_qty': _f(a.counted_qty),
        'difference': _f(a.difference), 'value_egp': _f(a.value_egp),
        'expected_source': a.expected_source, 'counted_at': a.created_at.isoformat(),
        'physical_expiry': a.physical_expiry.isoformat() if a.physical_expiry else None,
        'reasons': pick.reasons, 'status': pick.status, 'status_label': STATUS_LABELS.get(pick.status, ''),
        'escalated': pick.escalated, 'escalation_reason': pick.escalation_reason,
        'attempts': pick.attempts.count(),
        'can_act': pick.status in ('counted', 'escalated') and (acc.management or not pick.escalated),
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def board(request):
    _on()
    acc = _reviewer(request)
    if acc is None:
        return Response({'detail': 'غير مسموح'}, status=403)
    day = _date(request.query_params.get('date'), cairo_today())
    branch = (request.query_params.get('branch') or '').strip()
    s = DailyCountSettings.get()
    names = _branch_names()
    sessions = acc.scope(StockCountSession.objects.filter(mode='daily', count_date=day), field='branch_code')
    if branch:
        sessions = sessions.filter(branch_code=branch)
    people = []
    for sess in sessions.select_related('assigned_to').order_by('branch_code', 'assigned_to__user__first_name'):
        st = defaultdict(int)
        for status in sess.daily_picks.values_list('status', flat=True):
            st[status] += 1
        total = sum(st.values())
        left = st['pending'] + st['recount']
        people.append({
            'session_id': sess.pk, 'branch_code': sess.branch_code,
            'branch_name': names.get(sess.branch_code, sess.branch_code),
            'staff_id': sess.assigned_to_id, 'staff_name': sess.assigned_to.full_name if sess.assigned_to else '',
            'total': total, 'done': total - left - st['missed'], 'missed': st['missed'],
            'state': 'missed' if st['missed'] else ('done' if left == 0 else ('partial' if left < total else 'not_started')),
        })
    picks = (_scoped_picks(acc)
             .filter(status__in=('counted', 'escalated', 'recount'), latest_attempt__isnull=False)
             .exclude(latest_attempt__difference__gte=-s.match_tolerance,
                      latest_attempt__difference__lte=s.match_tolerance)
             .filter(Q(session__count_date=day) | Q(status='escalated') | Q(status='recount'))
             .select_related('session', 'session__assigned_to', 'latest_attempt', 'latest_attempt__counted_by'))
    if branch:
        picks = picks.filter(session__branch_code=branch)
    diffs = [_diff_row(x, acc, names, s.match_tolerance) for x in picks.order_by('-latest_attempt__value_egp', 'pk')]
    out = {'date': day.isoformat(), 'people': people, 'differences': diffs,
           'reasons': service.REVIEW_REASONS, 'management': acc.management}
    if acc.management:
        # «توزيع الآن»: the pilot branches management may hand today's lists out for by hand
        from apps.branches.models import Branch
        out['pilot_branches'] = [
            {'code': b.softech_branch_id, 'name': b.name_ar or b.name}
            for b in Branch.objects.filter(is_active=True, settings__daily_count_enabled=True).order_by('softech_branch_id')]
    return Response(out)


def _pick_for_review(request, pk):
    acc = _reviewer(request)
    if acc is None:
        return None, None, Response({'detail': 'غير مسموح'}, status=403)
    pick = _scoped_picks(acc).select_related('session', 'session__assigned_to').filter(pk=pk).first()
    if pick is None:
        return None, None, Response({'detail': 'غير موجود'}, status=404)
    return acc, pick, None


def _review_action(request, pk, fn):
    _on()
    acc, pick, err = _pick_for_review(request, pk)
    if err:
        return err
    try:
        fn(acc, pick)
    except PermissionError as e:
        return Response({'detail': str(e)}, status=403)
    except DailyCountError as e:
        return Response({'detail': str(e)}, status=400)
    pick.refresh_from_db()
    return Response({'pick_id': pick.pk, 'status': pick.status, 'status_label': STATUS_LABELS.get(pick.status, '')})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def pick_recount(request, pk):
    def go(acc, pick):
        from apps.users.models import StaffProfile
        assignee = None
        if request.data.get('assignee_id'):
            assignee = StaffProfile.objects.filter(pk=request.data.get('assignee_id')).first()
            if assignee is None:
                raise DailyCountError('الموظف غير موجود')
        service.request_recount(pick, acc, assignee, str(request.data.get('note') or ''))
    return _review_action(request, pk, go)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def pick_accept(request, pk):
    return _review_action(request, pk, lambda acc, pick: service.accept(
        pick, acc, str(request.data.get('reason') or ''), str(request.data.get('note') or ''),
        bool(request.data.get('needs_softech_adjustment'))))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def pick_escalate(request, pk):
    return _review_action(request, pk, lambda acc, pick: service.escalate(pick, acc, str(request.data.get('note') or '')))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def branch_staff(request):
    """Salespeople of a branch the reviewer may see — for «إعادة الجرد بواسطة»."""
    _on()
    acc = _reviewer(request)
    if acc is None:
        return Response({'detail': 'غير مسموح'}, status=403)
    code = (request.query_params.get('branch') or '').strip()
    if not code or not acc.allows_branch(code):
        return Response([])
    from apps.users.models import StaffProfile
    rows = StaffProfile.objects.filter(branch__softech_branch_id=code, is_active=True, user__is_active=True) \
        .exclude(role__in=('admin', 'call_center', 'delivery', 'viewer'))
    return Response([{'id': x.pk, 'name': x.full_name, 'role': x.role} for x in rows.order_by('user__first_name')])


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def report(request):
    _on()
    acc = _reviewer(request)
    if acc is None:
        return Response({'detail': 'غير مسموح'}, status=403)
    try:
        days = max(1, min(int(request.query_params.get('days') or 7), 90))
    except ValueError:
        days = 7
    since = cairo_today() - dt.timedelta(days=days - 1)
    s = DailyCountSettings.get()
    names = _branch_names()
    picks = _scoped_picks(acc).filter(session__count_date__gte=since).select_related(
        'session', 'session__assigned_to', 'latest_attempt')
    by_person = {}
    reasons = defaultdict(int)
    for x in picks:
        sess = x.session
        key = (sess.branch_code, sess.assigned_to_id)
        r = by_person.setdefault(key, {
            'branch_code': sess.branch_code, 'branch_name': names.get(sess.branch_code, sess.branch_code),
            'staff_name': sess.assigned_to.full_name if sess.assigned_to else '',
            'assigned': 0, 'counted': 0, 'missed': 0, 'differences': 0, 'value_egp': Decimal('0')})
        r['assigned'] += 1
        if x.status == 'missed':
            r['missed'] += 1
        if x.latest_attempt_id:
            r['counted'] += 1
            d = x.latest_attempt.difference
            if abs(d) > s.match_tolerance:
                r['differences'] += 1
                r['value_egp'] += x.latest_attempt.value_egp
        if x.review_reason:
            reasons[x.review_reason] += 1
    rows = []
    for r in by_person.values():
        r['completion_pct'] = round(100 * r['counted'] / r['assigned']) if r['assigned'] else 0
        r['value_egp'] = float(r['value_egp'])
        rows.append(r)
    rows.sort(key=lambda r: (r['branch_name'], -r['completion_pct'], r['staff_name']))
    if request.query_params.get('export') == 'xlsx':
        return _report_xlsx(rows, days)
    return Response({'days': days, 'since': since.isoformat(), 'rows': rows,
                     'reasons': [{'reason': k, 'label': service.REVIEW_REASONS.get(k, k), 'count': v}
                                 for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])]})


def _report_xlsx(rows, days):
    from io import BytesIO
    from django.http import HttpResponse
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = 'الجرد اليومي'
    ws.sheet_view.rightToLeft = True
    ws.append(['الفرع', 'الموظف', 'المطلوب', 'تم جرده', 'لم يُنجز', 'نسبة الإنجاز %', 'عدد الفروق', 'قيمة الفروق (ج.م)'])
    for r in rows:
        ws.append([r['branch_name'], r['staff_name'], r['assigned'], r['counted'], r['missed'],
                   r['completion_pct'], r['differences'], r['value_egp']])
    buf = BytesIO()
    wb.save(buf)
    resp = HttpResponse(buf.getvalue(),
                        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = f'attachment; filename="daily-counts-{days}d.xlsx"'
    return resp


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_now(request):
    _on()
    acc = Access(request)
    if not acc.management:
        return Response({'detail': 'غير مسموح'}, status=403)
    from apps.branches.models import Branch
    branch = Branch.objects.filter(softech_branch_id=str(request.data.get('branch_code') or '')).first()
    if branch is None:
        return Response({'detail': 'الفرع غير موجود'}, status=404)
    if not service.branch_enabled(branch):
        return Response({'detail': 'الجرد اليومي غير مفعّل لهذا الفرع'}, status=400)
    day = _date(request.data.get('date'), cairo_today())
    n = service.generate(branch, day, by=acc.profile)
    return Response({'created': n, 'date': day.isoformat()})


SETTINGS_FIELDS = ['items_per_person', 'include_pharmacists', 'job_hour', 'rotation_days', 'expiry_days',
                   'adjust_window_days', 'escalate_value_egp', 'escalate_repeat_count', 'escalate_repeat_days',
                   'match_tolerance', 'w_value', 'w_rate', 'w_adjust', 'w_finding', 'w_loss', 'w_expiry', 'w_never']
SETTINGS_LIMITS = {'items_per_person': (1, 100), 'job_hour': (0, 23), 'rotation_days': (0, 365),
                   'expiry_days': (1, 365), 'adjust_window_days': (1, 365), 'escalate_repeat_count': (1, 50),
                   'escalate_repeat_days': (1, 365)}


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def settings_view(request):
    _on()
    acc = Access(request)
    if not acc.management:
        return Response({'detail': 'غير مسموح'}, status=403)
    s = DailyCountSettings.get()
    if request.method == 'PATCH':
        if not acc.can_edit_thresholds:
            return Response({'detail': 'غير مسموح'}, status=403)
        old, changed = {}, {}
        for f in SETTINGS_FIELDS:
            if f not in request.data:
                continue
            raw = request.data[f]
            cur = getattr(s, f)
            try:
                if isinstance(cur, bool):
                    val = raw in (True, 'true', '1', 1)
                elif isinstance(cur, Decimal):
                    val = Decimal(str(raw))
                    if val < 0:
                        raise ValueError
                else:
                    val = int(raw)
                    lo, hi = SETTINGS_LIMITS.get(f, (0, 10 ** 6))
                    if not lo <= val <= hi:
                        raise ValueError
            except (ValueError, ArithmeticError):
                return Response({'detail': f'قيمة غير صالحة: {f}'}, status=400)
            if val != cur:
                old[f], changed[f] = str(cur), str(val)
                setattr(s, f, val)
        if changed:
            s.save()
            from apps.audit.models import AuditLog
            AuditLog.log('daily_count_settings_changed', user=acc.profile, obj=s, old_data=old, new_data=changed)
    return Response({f: (_f(getattr(s, f)) if isinstance(getattr(s, f), Decimal) else getattr(s, f))
                     for f in SETTINGS_FIELDS})
