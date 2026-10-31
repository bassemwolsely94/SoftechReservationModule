"""
apps/finance/receivables_views.py

P-41 «مستحقات التعاقدات» API (docs/product-review/06_SPEC_P-41_contract_receivables.md). Company-level finance: the
finance matrix grant AND an all-branch user (owner decision B-1 — recon_views._company_only). Read-only toward
SOFTECH; the refresh starts the contract-filtered SELECT-only sync in the background.

  GET   /api/finance/receivables/summary/
  GET   /api/finance/receivables/<personcode>/invoices/?overdue=1&bucket=61-90
  GET   /api/finance/receivables/terms/
  PATCH /api/finance/receivables/terms/          {personcode, agreed_days?, group_name?, is_tracked?, source_note?}
  GET   /api/finance/receivables/export/         xlsx
  POST  /api/finance/receivables/refresh/        background contract sync (one at a time)
"""
import datetime as dt
import logging
import threading
from decimal import Decimal

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import receivables as R
from .recon_views import FINANCE, FINANCE_EDIT, FINANCE_EXPORT

logger = logging.getLogger('elrezeiky.finance')

METHOD_LABELS = {'linked': 'من ربط SOFTECH', 'fifo': 'تقدير — أقدم فاتورة أولاً', 'none': '—'}
BASIS_LABELS = {'agreed': 'متفق عليه', 'measured': 'مقاس — غير متفق عليه', 'none': '—'}
_TERM_FIELDS = ('agreed_days', 'group_name', 'is_tracked', 'source_note')


def _j(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _j(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_j(x) for x in v]
    return v


def _as_of(request):
    try:
        return dt.date.fromisoformat(request.query_params.get('as_of', ''))
    except ValueError:
        return timezone.localdate()


def _contract(c):
    out = _j(c)
    out['measured_method_label'] = METHOD_LABELS.get(c['measured_method'], '')
    return out


@api_view(['GET'])
@permission_classes([IsAuthenticated, FINANCE])
def receivables_summary(request):
    s = R.summary(_as_of(request))
    return Response({'as_of': s['as_of'].isoformat(), 'totals': _j(s['totals']),
                     'groups': [{**_j({k: v for k, v in g.items() if k != 'contracts'}),
                                 'contracts': [_contract(c) for c in g['contracts']]} for g in s['groups']],
                     'reliable_coverage_pct': float(R.RELIABLE_COVERAGE_PCT)})


@api_view(['GET'])
@permission_classes([IsAuthenticated, FINANCE])
def receivables_invoices(request, personcode):
    from apps.finance.models import Payment
    as_of = _as_of(request)
    rows = R.open_invoices(personcode, as_of)
    if request.query_params.get('overdue') in ('1', 'true'):
        rows = [r for r in rows if r['overdue']]
    if request.query_params.get('bucket'):
        rows = [r for r in rows if r['bucket'] == request.query_params['bucket']]
    receipts = (Payment.objects.filter(party__softech_personcode=personcode, party_type='customer', direction='in')
                .order_by('-voucher_date')[:12])
    return Response({
        'invoices': [{**_j(r), 'expected_basis_label': BASIS_LABELS[r['expected_basis']]} for r in rows],
        'receipts': [{'date': p.voucher_date.isoformat(), 'amount': float(p.amount), 'cheqtype': p.cheqtype,
                      'note': p.note} for p in receipts],
    })


def _terms_dict(t):
    return {'personcode': t.personcode, 'name': t.name, 'group_name': t.group_name, 'agreed_days': t.agreed_days,
            'is_tracked': t.is_tracked, 'source_note': t.source_note,
            'entered_by': t.entered_by.full_name if t.entered_by_id else None, 'updated_at': t.updated_at}


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated, FINANCE])            # GET finance view · PATCH finance edit
def receivables_terms(request):
    from apps.finance.models import ContractReceivableTerms, ReconAuditEvent
    if request.method == 'GET':
        return Response({'terms': [_j(_terms_dict(t)) for t in
                                   ContractReceivableTerms.objects.select_related('entered_by')]})
    d = request.data
    t = ContractReceivableTerms.objects.filter(personcode=str(d.get('personcode') or '').strip()).first()
    if t is None:
        return Response({'detail': 'الحساب غير موجود.'}, status=status.HTTP_404_NOT_FOUND)
    vals = {f: d[f] for f in _TERM_FIELDS if f in d}
    if 'agreed_days' in vals and vals['agreed_days'] not in (None, ''):
        try:
            vals['agreed_days'] = int(vals['agreed_days'])
        except (TypeError, ValueError):
            vals['agreed_days'] = -1
        if not 0 <= vals['agreed_days'] <= 365:
            return Response({'detail': 'أيام السداد بين 0 و 365.'}, status=status.HTTP_400_BAD_REQUEST)
    elif 'agreed_days' in vals:
        vals['agreed_days'] = None
    if 'is_tracked' in vals:
        vals['is_tracked'] = vals['is_tracked'] if isinstance(vals['is_tracked'], bool) \
            else str(vals['is_tracked']).lower() in ('true', '1')
    for f in ('group_name', 'source_note'):
        if f in vals:
            vals[f] = str(vals[f] or '').strip()[:300]
    before = {f: getattr(t, f) for f in _TERM_FIELDS}
    for f, v in vals.items():
        setattr(t, f, v)
    staff = getattr(request.user, 'staff_profile', None)
    t.entered_by = staff
    t.save()
    ReconAuditEvent.objects.create(action='contract_terms_changed', party=t.party, before_state=before,
                                   after_state={f: getattr(t, f) for f in _TERM_FIELDS},
                                   detail=f'contract {t.personcode}', performed_by=staff)
    return Response(_j(_terms_dict(t)))


@api_view(['GET'])
@permission_classes([IsAuthenticated, FINANCE_EXPORT])
def receivables_export(request):
    from io import BytesIO
    import openpyxl
    from django.http import HttpResponse
    from openpyxl.styles import Alignment, Font, PatternFill
    as_of = _as_of(request)
    s = R.summary(as_of)
    cols = [('الجهة', 22), ('الحساب', 10), ('الاسم', 34), ('المفتوح', 14), ('0-30', 12), ('31-60', 12),
            ('61-90', 12), ('91-180', 12), ('>180', 12), ('المتأخر', 14), ('على الحساب', 14), ('مرتجعات مفتوحة', 14),
            ('صافي المستحق', 14), ('رصيد SOFTECH', 14), ('الفرق', 12), ('أيام متفق عليها', 10),
            ('أيام مقاسة', 10), ('طريقة القياس', 22), ('تغطية الربط %', 10)]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'مستحقات التعاقدات'
    ws.sheet_view.rightToLeft = True
    ws.append([f'مستحقات التعاقدات — حتى {as_of.isoformat()}'])
    ws['A1'].font = Font(bold=True, size=13)
    ws.append([])
    ws.append([c[0] for c in cols])
    fill = PatternFill('solid', fgColor='022871')
    for i, c in enumerate(cols, start=1):
        cell = ws.cell(row=3, column=i)
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = fill
        cell.alignment = Alignment(horizontal='center')
        ws.column_dimensions[cell.column_letter].width = c[1]
    f = lambda v: float(v) if v is not None else None      # noqa: E731
    for g in s['groups']:
        for c in g['contracts']:
            b = c['buckets']
            ws.append([g['group_name'], c['personcode'], c['name'], f(c['open']), f(b['0-30']), f(b['31-60']),
                       f(b['61-90']), f(b['91-180']), f(b['>180']), f(c['overdue']), f(c['on_account']),
                       f(c['open_returns']), f(c['net_receivable']), f(c['softech_receivable']), f(c['difference']),
                       c['agreed_days'], f(c['measured_days']), METHOD_LABELS.get(c['measured_method'], ''),
                       f(c['link_coverage_pct'])])
    ws.freeze_panes = 'A4'
    buf = BytesIO()
    wb.save(buf)
    resp = HttpResponse(buf.getvalue(),
                        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = f'attachment; filename="contract_receivables_{as_of.isoformat()}.xlsx"'
    return resp


_refresh_lock = threading.Lock()


@api_view(['POST'])
@permission_classes([IsAuthenticated, FINANCE_EDIT])
def receivables_refresh(request):
    """Re-read the tracked contract accounts from SOFTECH (SELECT-only, 120 days) in the background."""
    from apps.finance.models import ReconciliationRun
    recent = timezone.now() - dt.timedelta(hours=2)
    if _refresh_lock.locked() or ReconciliationRun.objects.filter(party_type='customer', status='running',
                                                                    started_at__gte=recent).exists():
        return Response({'detail': 'تحديث جارٍ بالفعل.', 'running': True}, status=status.HTTP_409_CONFLICT)

    def _work():
        from django.core.management import call_command
        from django.db import connections
        with _refresh_lock:
            try:
                today = timezone.localdate()
                call_command('sync_ap_reconciliation', party_type='customer', contracts=True,
                             date_from=(today - dt.timedelta(days=120)).isoformat(), date_to=today.isoformat(),
                             verbosity=0)
            except Exception:
                logger.exception('contract receivables refresh failed')
            finally:
                connections.close_all()
    threading.Thread(target=_work, name='contract-receivables-refresh', daemon=True).start()
    return Response({'detail': 'بدأ تحديث مستحقات التعاقدات من SOFTECH.', 'running': True},
                    status=status.HTTP_202_ACCEPTED)
