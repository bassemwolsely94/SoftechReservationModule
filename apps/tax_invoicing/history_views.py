"""
apps/tax_invoicing/history_views.py — browsing the ETA history mirror (spec 2026-11-14, phase 2).

Read only. Lists come from the local mirror (one ETA system at a time, never mixed); a document's lines, ETA's
validation steps and the official PDF are asked from ETA when someone opens it, and the lines are kept on the row.
Company-level data, seen with tax_invoicing → view (the same as the tax documents themselves). A person's national
ID is masked everywhere; a company's tax number is not secret.
"""
import datetime as dt
import io
import math
from decimal import Decimal

import openpyxl
from django.db.models import Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.export_safety import neutralise_formulas
from core.permissions import matrix_permission
from core.sort_ordering import explicit_order_by

from . import services
from .eta_client import EtaError
from .eta_reader import SYSTEMS, EtaReader
from .models import EtaMirrorDocument, EtaMirrorReceipt

VIEWER = matrix_permission('tax_invoicing')
PAGE_SIZE, MAX_PAGE_SIZE, MAX_EXPORT = 50, 200, 50000
DOC_SORT = {'issued_at': 'issued_at', 'total_amount': 'total_amount', 'status': 'status', 'internal_id': 'internal_id',
            'receiver_name': 'receiver_name', 'issuer_name': 'issuer_name', 'doc_type': 'doc_type'}
RECEIPT_SORT = {'issued_at': 'issued_at', 'total_amount': 'total_amount', 'status': 'status',
                'receipt_number': 'receipt_number', 'pos_serial': 'pos_serial'}


class _Bad(Exception):
    pass


def _mask(id_type, value):
    """A person's (P) or foreign (F) ID shows its last 4 digits only; a business tax number (B) is public."""
    value = value or ''
    if not value or (id_type or '').upper() == 'B':
        return value
    return '•' * max(len(value) - 4, 0) + value[-4:]


def _money(value):
    return None if value is None else str(Decimal(value).quantize(Decimal('0.00001')))


def _system(request):
    system = request.query_params.get('system') or ''
    if system not in SYSTEMS:
        raise _Bad('اختر المنظومة: التجريبية أو الفعلية')
    return system


def _dates(qs, request):
    start, end = parse_date(request.query_params.get('date_from') or ''), parse_date(request.query_params.get('date_to') or '')
    if start:
        qs = qs.filter(issued_at__date__gte=start)
    if end:
        qs = qs.filter(issued_at__date__lte=end)
    return qs


def _documents(request):
    p = request.query_params
    qs = _dates(EtaMirrorDocument.objects.filter(system=_system(request)), request)
    for key in ('direction', 'status', 'doc_type'):
        if p.get(key):
            qs = qs.filter(**{key: p[key].lower()})
    q = (p.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(uuid__icontains=q) | Q(internal_id__icontains=q) | Q(receiver_name__icontains=q)
                       | Q(issuer_name__icontains=q) | Q(receiver_id=q) | Q(issuer_rin=q))
    return qs


def _receipts(request):
    p = request.query_params
    qs = _dates(EtaMirrorReceipt.objects.filter(system=_system(request)), request)
    if p.get('status'):
        qs = qs.filter(status=p['status'].lower())
    if p.get('device'):
        qs = qs.filter(pos_serial=p['device'])
    q = (p.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(receipt_number__icontains=q) | Q(uuid__icontains=q))
    return qs


def _doc_row(d):
    return {'id': d.id, 'system': d.system, 'uuid': d.uuid, 'internal_id': d.internal_id, 'doc_type': d.doc_type,
            'direction': d.direction, 'status': d.status, 'issued_at': d.issued_at, 'received_at': d.received_at,
            'issuer_rin': d.issuer_rin, 'issuer_name': d.issuer_name, 'receiver_type': d.receiver_type,
            'receiver_id': _mask(d.receiver_type, d.receiver_id), 'receiver_name': d.receiver_name,
            'net_amount': _money(d.net_amount), 'total_amount': _money(d.total_amount)}


def _receipt_row(r):
    return {'id': r.id, 'system': r.system, 'uuid': r.uuid, 'receipt_number': r.receipt_number, 'pos_serial': r.pos_serial,
            'issued_at': r.issued_at, 'receipt_type': r.receipt_type, 'status': r.status,
            'total_amount': _money(r.total_amount), 'submitter': (r.raw or {}).get('submitterName') or ''}


def _page(request, qs, sort, default, to_row, extra=None):
    try:
        ordering = explicit_order_by(request.query_params.get('ordering'), sort, default)
    except Exception:       # noqa: BLE001 — explicit_order_by raises a ValidationError for an unknown key
        raise _Bad('ترتيب غير مدعوم')
    try:
        size = min(max(int(request.query_params.get('page_size') or PAGE_SIZE), 1), MAX_PAGE_SIZE)
        page = max(int(request.query_params.get('page') or 1), 1)
    except ValueError:
        raise _Bad('رقم الصفحة غير صحيح')
    count = qs.count()
    total = qs.aggregate(t=Sum('total_amount'))['t']
    rows = [to_row(x) for x in qs.order_by(*ordering)[(page - 1) * size:page * size]]
    return {'count': count, 'page': page, 'pages': max(math.ceil(count / size), 1), 'total_amount': _money(total),
            'rows': rows, **(extra or {})}


def _guard(fn):
    def run(request, *a, **kw):
        try:
            return fn(request, *a, **kw)
        except _Bad as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    run.__name__ = fn.__name__
    run.__doc__ = fn.__doc__
    return run


@api_view(['GET'])
@permission_classes([IsAuthenticated, VIEWER])
@_guard
def history_documents(request):
    return Response(_page(request, _documents(request), DOC_SORT, ('-issued_at', '-id'), _doc_row))


@api_view(['GET'])
@permission_classes([IsAuthenticated, VIEWER])
@_guard
def history_receipts(request):
    system = _system(request)
    devices = sorted(d for d in EtaMirrorReceipt.objects.filter(system=system).order_by().values_list('pos_serial', flat=True)
                     .distinct() if d)
    return Response(_page(request, _receipts(request), RECEIPT_SORT, ('-issued_at', '-id'), _receipt_row,
                          {'devices': devices}))


# ── detail (ETA asked once, kept on the row) ────────────────────────────────────────────────────

def _sum_tax(items):
    return sum((Decimal(str(t.get('amount') or 0)) for t in items or [] if isinstance(t, dict)), Decimal('0'))


def _num(value):
    if isinstance(value, dict):
        value = value.get('amountEGP', value.get('amount'))
    if value in (None, ''):
        return None
    return format(Decimal(str(value)).normalize(), 'f')


def _doc_lines(detail):
    return [{'internal_code': x.get('internalCode') or '', 'description': x.get('description') or '',
             'item_code': x.get('itemCode') or '', 'quantity': _num(x.get('quantity')), 'unit_value': _num(x.get('unitValue')),
             'sales_total': _num(x.get('salesTotal')), 'discount': _num(x.get('discount')), 'net_total': _num(x.get('netTotal')),
             'tax': _num(_sum_tax(x.get('lineTaxableItems') or x.get('taxableItems'))), 'total': _num(x.get('total'))}
            for x in (detail.get('invoiceLines') or []) if isinstance(x, dict)]


def _receipt_lines(detail):
    items = ((detail.get('receipt') or {}).get('itemData') or [])
    return [{'internal_code': x.get('internalCode') or '', 'description': x.get('description') or '',
             'item_code': x.get('itemCode') or '', 'quantity': _num(x.get('quantity')), 'unit_value': _num(x.get('unitPrice')),
             'sales_total': _num(x.get('totalSale')), 'net_total': _num(x.get('netSale')),
             'tax': _num(_sum_tax(x.get('taxableItems'))), 'total': _num(x.get('total'))}
            for x in items if isinstance(x, dict)]


def _ensure_detail(obj, path):
    """The row's ETA detail, asked from ETA once. Returns (detail or None, reason when not available)."""
    if obj.detail:
        return obj.detail, ''
    reader = EtaReader(obj.system)
    reason = reader.why_not()
    if reason:
        return None, reason
    try:
        resp = reader.get(path)
    except EtaError as exc:
        return None, str(exc)[:300]
    if resp.status_code != 200:
        return None, f'المصلحة ردت HTTP {resp.status_code}'
    detail = resp.json() if isinstance(resp.json(), dict) else {}
    obj.detail, obj.detail_at = detail, timezone.now()
    obj.save(update_fields=['detail', 'detail_at'])
    return detail, ''


@api_view(['GET'])
@permission_classes([IsAuthenticated, VIEWER])
def history_document_detail(request, pk):
    doc = get_object_or_404(EtaMirrorDocument, pk=pk)
    detail, reason = _ensure_detail(doc, f'/api/v1.0/documents/{doc.uuid}/details')
    steps = ((detail or {}).get('validationResults') or {}).get('validationSteps') or []
    return Response({**_doc_row(doc), 'lines': _doc_lines(detail) if detail else None, 'detail_unavailable': reason,
                     'validation': [{'name': s.get('stepName'), 'status': s.get('status'), 'error': s.get('error')}
                                    for s in steps if isinstance(s, dict)],
                     'cancel_until': (detail or {}).get('canbeCancelledUntil'),
                     'reject_until': (detail or {}).get('canbeRejectedUntil'),
                     'references': doc.references or []})


@api_view(['GET'])
@permission_classes([IsAuthenticated, VIEWER])
def history_receipt_detail(request, pk):
    rec = get_object_or_404(EtaMirrorReceipt, pk=pk)
    detail, reason = _ensure_detail(rec, f'/api/v1/receipts/{rec.uuid}/details')
    seller = ((detail or {}).get('receipt') or {}).get('seller') or {}
    return Response({**_receipt_row(rec), 'lines': _receipt_lines(detail) if detail else None, 'detail_unavailable': reason,
                     'branch': seller.get('branchCode') or '', 'previous_uuid': rec.previous_uuid})


@api_view(['GET'])
@permission_classes([IsAuthenticated, VIEWER])
def history_document_pdf(request, pk):
    """ETA's own printout of the document (its official layout), straight from ETA."""
    doc = get_object_or_404(EtaMirrorDocument, pk=pk)
    reader = EtaReader(doc.system)
    reason = reader.why_not()
    if reason:
        return Response({'detail': reason}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    try:
        resp = reader.get(f'/api/v1.0/documents/{doc.uuid}/pdf')
    except EtaError as exc:
        return Response({'detail': str(exc)[:300]}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    if resp.status_code != 200 or 'pdf' not in str(resp.headers.get('Content-Type', '')):
        return Response({'detail': f'المصلحة لم ترسل الملف (HTTP {resp.status_code})'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    services.audit('eta_history_pdf', actor=request.user, entity='eta_history_document', entity_id=doc.pk,
                   after={'system': doc.system, 'uuid': doc.uuid})
    out = HttpResponse(resp.content, content_type='application/pdf')
    out['Content-Disposition'] = f'inline; filename="{doc.internal_id or doc.uuid}.pdf"'
    return out


# ── export ─────────────────────────────────────────────────────────────────────────────────────

DOC_COLUMNS = [('uuid', 'UUID'), ('internal_id', 'الرقم الداخلي'), ('doc_type', 'النوع'), ('direction', 'الاتجاه'),
               ('status', 'الحالة'), ('issued_at', 'تاريخ الإصدار'), ('issuer_rin', 'رقم المُصدر'), ('issuer_name', 'المُصدر'),
               ('receiver_id', 'رقم المستلم'), ('receiver_name', 'المستلم'), ('net_amount', 'الصافي'), ('total_amount', 'الإجمالي')]
RECEIPT_COLUMNS = [('uuid', 'UUID'), ('receipt_number', 'رقم الإيصال'), ('pos_serial', 'الجهاز'), ('issued_at', 'تاريخ الإصدار'),
                   ('receipt_type', 'النوع'), ('status', 'الحالة'), ('total_amount', 'الإجمالي'), ('submitter', 'البرنامج المرسل')]


def _cell(value):
    if isinstance(value, dt.datetime):
        return timezone.localtime(value).replace(tzinfo=None) if timezone.is_aware(value) else value
    return value


@api_view(['GET'])
@permission_classes([IsAuthenticated, VIEWER])
@_guard
def history_export(request, kind):
    if kind == 'documents':
        qs, columns, to_row, sort = _documents(request), DOC_COLUMNS, _doc_row, ('-issued_at', '-id')
    else:
        qs, columns, to_row, sort = _receipts(request), RECEIPT_COLUMNS, _receipt_row, ('-issued_at', '-id')
    count = qs.count()
    if count > MAX_EXPORT:
        raise _Bad(f'النتيجة {count} صفاً؛ ضيّق الفترة (الحد {MAX_EXPORT})')
    wb = openpyxl.Workbook(write_only=False)
    ws = wb.active
    ws.title = 'ETA'
    ws.sheet_view.rightToLeft = True
    ws.append([label for _, label in columns])
    for obj in qs.order_by(*sort).iterator(chunk_size=2000):
        row = to_row(obj)
        ws.append([_cell(row.get(key)) for key, _ in columns])
    buf = io.BytesIO()
    neutralise_formulas(wb).save(buf)       # typed text never reaches Excel as a live formula
    services.audit('eta_history_export', actor=request.user, entity='eta_history', entity_id=kind,
                   after={'system': request.query_params.get('system'), 'rows': count})
    out = HttpResponse(buf.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    out['Content-Disposition'] = f'attachment; filename="eta-{kind}-{request.query_params.get("system")}.xlsx"'
    return out
