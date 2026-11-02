"""
apps/purchasing/dead_stock_views.py

P-27 part A «🧊 مخزون راكد» API (docs/product-review/06_SPEC_P-27_dead_stock_recovery.md). Read-only toward SOFTECH.
Read = the analytics grant (as the spike tab); a branch-bound user sees only own-branch lines (core/branch_scope).
Decisions and strategic hold = purchasing edit/approve, audited (AuditLog).

  GET  /api/purchasing/dead-stock/summary/
  GET  /api/purchasing/dead-stock/lines/?lane=&location=&branch=&cause=&flag=&q=&show_decided=1&page=&page_size=
                                                      (200 a page, rank order; format=xlsx = every line)
  GET  /api/purchasing/dead-stock/recompute/          {running}
  POST /api/purchasing/dead-stock/recompute/          rebuild the list for the latest engine run (background)
  POST /api/purchasing/dead-stock/decisions/          {item_id, branch_code, decision, reason, until?} · {id, close: true}
  POST /api/purchasing/dead-stock/strategic-hold/     {item_id, hold}
"""
import datetime as dt
import logging
import threading

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.permissions import matrix_permission
from core.export_safety import neutralise_formulas

from . import dead_stock as DS

logger = logging.getLogger('elrezeiky.purchasing')

DEAD_READ = matrix_permission('analytics')
DEAD_REVIEW = matrix_permission('purchasing', post=('edit', 'approve'))
# recompute: GET (status) = read; POST passes this class on read rights and is then checked against DEAD_REVIEW
DEAD_RECOMPUTE = matrix_permission('analytics', post=('view',))

LANE_AR = dict([('move', 'يُباع بفرع آخر'), ('return', 'مرتجع للمورد'), ('stop', 'إيقاف (موقوف)')])
LOCATION_AR = {'hq_only': 'الرئيسي فقط', 'branches_only': 'فروع فقط', 'both': 'الرئيسي والفروع'}
CAUSE_AR = {'': '', 'supplier_push': 'دفع مورد / شراء مركزي', 'demand_died': 'توقف الطلب', 'obsolete': 'متقادم'}
WINDOW_AR = {'open': 'نافذة المرتجع مفتوحة', 'closes_this_month': 'تُغلق هذا الشهر', 'opens_next_month': 'تُفتح الشهر القادم',
             'later': 'لاحقًا', 'missed': 'فاتت'}
REASONS = ('مريض معروف', 'عرض قادم', 'خطأ رصيد', 'أخرى')
PAGE_SIZE = 200
MAX_PAGE_SIZE = 1000


def _allowed_codes(request):
    """None = every branch; else the softech codes this user may see."""
    from apps.branches.models import Branch
    from core.branch_scope import branch_ids
    ids = branch_ids(request.user)
    if ids is None:
        return None
    return set(Branch.objects.filter(id__in=ids).values_list('softech_branch_id', flat=True))


def _staff(request):
    return getattr(request.user, 'staff_profile', None)


def _open_decisions(today):
    from apps.purchasing.models import DeadStockDecision
    return list(DeadStockDecision.objects.filter(closed_at__isnull=True, until__gte=today)
                .values('id', 'item_id', 'branch_code', 'decision', 'reason', 'until'))


def _decided(decisions):
    out = {}
    for d in decisions:
        out[(d['item_id'], d['branch_code'])] = d
    return out


def _lines(request, snap):
    from apps.branches.models import Branch
    qp = request.query_params
    qs = snap.lines.select_related('item')
    codes = _allowed_codes(request)
    if codes is not None:
        qs = qs.filter(branch_code__in=codes)
    for f in ('lane', 'location', 'cause'):
        if qp.get(f):
            qs = qs.filter(**{f: qp[f]})
    if qp.get('branch'):
        qs = qs.filter(branch_code=qp['branch'])
    if qp.get('q'):
        from apps.catalog.wildcard import wq
        qs = qs.filter(wq(qp['q'], 'item__name', 'item__softech_id'))
    flag = qp.get('flag')
    decided = _decided(_open_decisions(timezone.localdate()))
    show_decided = qp.get('show_decided') in ('1', 'true')
    names = dict(Branch.objects.values_list('softech_branch_id', 'name'))
    out = []
    for l in qs:
        d = decided.get((l.item_id, l.branch_code)) or decided.get((l.item_id, ''))
        if d and not show_decided:
            continue
        if flag == 'fridge' and not l.flags.get('fridge') or flag == 'below_threshold' and not l.flags.get(
                'below_threshold') or flag == 'conflict' and not l.flags.get('conflict'):
            continue
        out.append({
            'id': l.pk, 'item_id': l.item_id, 'itemcode': l.item.softech_id, 'name': l.item.name,
            'branch_code': l.branch_code, 'branch_name': names.get(l.branch_code, l.branch_code),
            'lane': l.lane, 'lane_label': LANE_AR[l.lane], 'location': l.location,
            'location_label': LOCATION_AR[l.location], 'cause': l.cause, 'cause_label': CAUSE_AR.get(l.cause, ''),
            'qty': float(l.qty), 'value': float(l.value), 'last_sale_date': l.last_sale_date,
            'oldest_arrival_date': l.oldest_arrival_date, 'age_note': l.age_note,
            'network_rate': float(l.network_rate),
            'targets': [{**t, 'branch_name': names.get(t['branch'], t['branch'])} for t in l.targets],
            'move_value': float(l.move_value), 'soonest_expiry': l.soonest_expiry,
            'supplier_code': l.supplier_code, 'supplier_class': l.supplier_class,
            'window_state': l.window_state, 'window_label': WINDOW_AR.get(l.window_state, ''),
            'flags': l.flags, 'strategic_hold': l.item.strategic_hold,
            'decision': d and {'id': d['id'], 'decision': d['decision'], 'reason': d['reason'], 'until': d['until']},
        })
    return out


@api_view(['GET'])
@permission_classes([IsAuthenticated, DEAD_READ])
def dead_stock_summary(request):
    snap = DS.latest_snapshot()
    if snap is None:
        return Response({'snapshot': None, 'lanes': {}, 'detail': 'لم تُحسب قائمة الراكد بعد — اضغط «إعادة الحساب».'})
    lines = _lines(request, snap)
    lanes = {k: {'label': v, 'count': 0, 'value': 0.0, 'qty': 0.0} for k, v in LANE_AR.items()}
    locations = {k: {'label': v, 'count': 0, 'value': 0.0} for k, v in LOCATION_AR.items()}
    for l in lines:
        for agg in (lanes[l['lane']], locations[l['location']]):
            agg['count'] += 1
            agg['value'] += l['value']
        lanes[l['lane']]['qty'] += l['qty']
    return Response({'snapshot': {'run_id': snap.run_id, 'run_finished_at': snap.run.finished_at,
                                  'computed_at': snap.computed_at, 'as_of': snap.as_of,
                                  'settings': snap.settings_used},
                     'branches': [{'code': c, 'name': n} for c, n in
                                  sorted({(l['branch_code'], l['branch_name']) for l in lines})],
                     'lanes': lanes, 'locations': locations, 'total': {
                         'count': len(lines), 'value': sum(l['value'] for l in lines)},
                     'reasons': REASONS})


@api_view(['GET'])
@permission_classes([IsAuthenticated, DEAD_READ])
def dead_stock_lines(request):
    snap = DS.latest_snapshot()
    lines = _lines(request, snap) if snap else []
    if request.query_params.get('format') == 'xlsx':
        return _excel(lines, snap)                                    # the export is never paged
    try:
        size = max(1, min(int(request.query_params.get('page_size', PAGE_SIZE)), MAX_PAGE_SIZE))
        page = max(1, int(request.query_params.get('page', 1)))
    except ValueError:
        size, page = PAGE_SIZE, 1
    pages = max(1, -(-len(lines) // size))
    page = min(page, pages)
    return Response({'lines': lines[(page - 1) * size: page * size], 'count': len(lines), 'page': page,
                     'pages': pages, 'page_size': size, 'run_id': snap.run_id if snap else None})


def _excel(lines, snap):
    from io import BytesIO
    import openpyxl
    from django.http import HttpResponse
    from openpyxl.styles import Font, PatternFill
    wb = openpyxl.Workbook()
    fill = PatternFill('solid', fgColor='022871')
    cols = [('الصنف', 10), ('الاسم', 34), ('الفرع', 16), ('الكمية', 9), ('القيمة', 12), ('آخر بيع', 12),
            ('أقدم وارد', 12), ('معدل الشبكة/شهر', 12), ('الموقع', 14), ('السبب', 18), ('إلى (فرع: كمية)', 34),
            ('قيمة النقل', 12), ('المورد', 10), ('تصنيف المورد', 10), ('نافذة المرتجع', 18), ('ملاحظات', 26)]

    def sheet(title, rows, first=False):
        ws = wb.active if first else wb.create_sheet()
        ws.title = title
        ws.sheet_view.rightToLeft = True
        ws.append([c for c, _ in cols])
        for i, (_, w) in enumerate(cols, start=1):
            cell = ws.cell(row=1, column=i)
            cell.font, cell.fill = Font(bold=True, color='FFFFFF'), fill
            ws.column_dimensions[cell.column_letter].width = w
        for l in rows:
            notes = []
            if l['flags'].get('fridge'):
                notes.append('ثلاجة — لا يُنقل')
            if l['flags'].get('below_threshold'):
                notes.append('أقل من حد القيمة')
            if l['flags'].get('conflict'):
                notes.append(f"متعارض مع تحويل {l['flags']['conflict']}")
            if l['age_note']:
                notes.append('أقدم من سنة')
            ws.append([l['itemcode'], l['name'], l['branch_name'], l['qty'], l['value'], l['last_sale_date'],
                       l['oldest_arrival_date'], l['network_rate'], l['location_label'], l['cause_label'],
                       '، '.join(f"{t['branch_name']}: {t['qty']}" for t in l['targets']), l['move_value'],
                       l['supplier_code'], l['supplier_class'], l['window_label'], ' · '.join(notes)])
        ws.freeze_panes = 'A2'
    by_lane = {k: [l for l in lines if l['lane'] == k] for k in LANE_AR}
    ws = wb.active
    ws.title = 'ملخص'
    ws.sheet_view.rightToLeft = True
    ws.append([f'المخزون الراكد — تشغيل المحرك {snap.run_id if snap else "—"}'])
    ws['A1'].font = Font(bold=True, size=13)
    ws.append(['المسار', 'عدد', 'القيمة'])
    for k, v in LANE_AR.items():
        ws.append([v, len(by_lane[k]), sum(l['value'] for l in by_lane[k])])
    for k, v in LANE_AR.items():
        sheet(v[:31], by_lane[k])
    buf = BytesIO()
    neutralise_formulas(wb).save(buf)
    resp = HttpResponse(buf.getvalue(),
                        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = f'attachment; filename="dead_stock_{timezone.localdate().isoformat()}.xlsx"'
    return resp


_lock = threading.Lock()


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, DEAD_RECOMPUTE])
def dead_stock_recompute(request):
    if request.method == 'GET':
        return Response({'running': _lock.locked()})
    if not DEAD_REVIEW().has_permission(request, None):
        return Response({'detail': 'إعادة الحساب تحتاج صلاحية تعديل المشتريات.'}, status=status.HTTP_403_FORBIDDEN)
    if _lock.locked():
        return Response({'detail': 'إعادة الحساب جارية بالفعل.', 'running': True}, status=status.HTTP_409_CONFLICT)
    from apps.purchasing.rate_writer import _latest_run
    run = _latest_run()
    if run is None:
        return Response({'detail': 'لا يوجد تشغيل ناجح لمحرك الطلب.'}, status=status.HTTP_400_BAD_REQUEST)

    def _work():
        from django.db import connections
        with _lock:
            try:
                DS.compute_snapshot(run)
            except Exception:
                logger.exception('dead stock recompute failed')
            finally:
                connections.close_all()
    threading.Thread(target=_work, name='dead-stock-recompute', daemon=True).start()
    return Response({'detail': f'بدأت إعادة حساب الراكد لتشغيل المحرك {run.pk}.', 'running': True},
                    status=status.HTTP_202_ACCEPTED)


@api_view(['POST'])
@permission_classes([IsAuthenticated, DEAD_REVIEW])
def dead_stock_decisions(request):
    from apps.audit.models import AuditLog
    from apps.catalog.models import Item
    from apps.purchasing.models import DeadStockDecision
    d = request.data
    staff = _staff(request)
    if d.get('close'):
        obj = DeadStockDecision.objects.filter(pk=d.get('id'), closed_at__isnull=True).first()
        if obj is None:
            return Response({'detail': 'القرار غير موجود.'}, status=status.HTTP_404_NOT_FOUND)
        obj.closed_at = timezone.now()
        obj.save(update_fields=['closed_at'])
        AuditLog.log('dead_stock_decision', user=staff, obj=obj, note='closed',
                     changes={'closed_at': [None, obj.closed_at.isoformat()]})
        return Response({'id': obj.pk, 'closed': True})
    item = Item.objects.filter(pk=d.get('item_id')).first()
    if item is None:
        return Response({'detail': 'الصنف غير موجود.'}, status=status.HTTP_404_NOT_FOUND)
    decision = d.get('decision') or 'exclude'
    if decision not in dict(DeadStockDecision.DECISION_CHOICES):
        return Response({'detail': 'القرار: استبعاد أو يبقى بالفرع.'}, status=status.HTTP_400_BAD_REQUEST)
    reason = str(d.get('reason') or '').strip()[:300]
    if not reason:
        return Response({'detail': 'اختر السبب.'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        until = dt.date.fromisoformat(str(d['until'])) if d.get('until') else \
            DS.months_ago(timezone.localdate(), -DS.cfg()['months'])
    except ValueError:
        return Response({'detail': 'تاريخ غير صحيح.'}, status=status.HTTP_400_BAD_REQUEST)
    obj = DeadStockDecision.objects.create(item=item, branch_code=str(d.get('branch_code') or '').strip(),
                                           decision=decision, reason=reason, until=until, decided_by=staff)
    AuditLog.log('dead_stock_decision', user=staff, obj=obj,
                 new_data={'item': item.softech_id, 'branch_code': obj.branch_code, 'decision': decision,
                           'reason': reason, 'until': until.isoformat()})
    return Response({'id': obj.pk, 'until': until}, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated, DEAD_REVIEW])
def dead_stock_strategic_hold(request):
    from apps.audit.models import AuditLog
    from apps.catalog.models import Item
    item = Item.objects.filter(pk=request.data.get('item_id')).first()
    if item is None:
        return Response({'detail': 'الصنف غير موجود.'}, status=status.HTTP_404_NOT_FOUND)
    hold = request.data.get('hold')
    hold = hold if isinstance(hold, bool) else str(hold).lower() in ('1', 'true')
    before = item.strategic_hold
    item.strategic_hold = hold
    item.save(update_fields=['strategic_hold'])
    AuditLog.log('dead_stock_strategic_hold', user=_staff(request), obj=item,
                 changes={'strategic_hold': [before, hold]}, note=str(request.data.get('reason') or '')[:255])
    return Response({'item_id': item.pk, 'strategic_hold': hold})
