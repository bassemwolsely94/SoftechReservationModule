"""
apps/tax_invoicing/eta_history.py — copying what ETA holds into the history mirror, per ETA system.

Backfill: the history from TAX_ETA_HISTORY_START to today is cut into date windows (receipts 4 days, ETA's
receipt package holds at most 3000; documents 30 days). Each window: ask ETA for a package, wait until ETA has
prepared it, download the ZIP, upsert its rows. A window ETA calls too big is split in halves; a single day still
too big is marked too_big, never truncated. When ETA can't be reached the window keeps its state and the reason,
so "not fetched yet" is never read as "nothing there". Read only: nothing here sends anything to ETA.
"""
import datetime as dt
import io
import json
import zipfile
from decimal import Decimal, InvalidOperation

from django.db.models import Count, Max, Min
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .eta_client import EtaError, EtaRefused
from .eta_reader import EtaReader
from .models import EtaHistoryWindow, EtaMirrorDocument, EtaMirrorReceipt, TaxIssuerProfile

KINDS = ('documents', 'receipts')
WINDOW_DAYS = {'documents': 30, 'receipts': 4}
MAX_ATTEMPTS = 5
W = EtaHistoryWindow


# ── planning ───────────────────────────────────────────────────────────────────────────────────

def plan_windows(system, kind, start, end):
    """Create the windows covering start..end (inclusive) that don't exist yet. Returns how many were created."""
    span = dt.timedelta(days=WINDOW_DAYS[kind])
    created, day = 0, start
    while day <= end:
        last = min(day + span - dt.timedelta(days=1), end)
        _, new = W.objects.get_or_create(system=system, kind=kind, date_from=day, date_to=last)
        created += int(new)
        day = last + dt.timedelta(days=1)
    return created


def _body(kind, w):
    date_from = f'{w.date_from.isoformat()}T00:00:00Z'
    date_to = f'{w.date_to.isoformat()}T23:59:59Z'
    if kind == 'documents':
        return {'type': 'Full', 'format': 'JSON',
                'queryParameters': {'dateFrom': date_from, 'dateTo': date_to, 'truncateIfExceeded': False}}
    return {'type': 'Full', 'format': 'JSON',
            'queryParameters': {'dateFrom': date_from, 'dateTo': date_to, 'represntedTaxpayerTypeId': 'Both'}}


def _too_big(exc):
    text = json.dumps(exc.body or {}, ensure_ascii=False) + str(exc)
    return 'OperationExceedsLimit' in text


def _split(w, reason):
    days = (w.date_to - w.date_from).days + 1
    if days <= 1:
        w.state, w.error = W.TOO_BIG, f'أكبر من حد المصلحة ليوم واحد: {reason}'[:2000]
        w.save()
        return
    mid = w.date_from + dt.timedelta(days=days // 2 - 1)
    system, kind, first, last = w.system, w.kind, w.date_from, w.date_to
    w.delete()
    W.objects.get_or_create(system=system, kind=kind, date_from=first, date_to=mid)
    W.objects.get_or_create(system=system, kind=kind, date_from=mid + dt.timedelta(days=1), date_to=last)


# ── one step: poll, download, request ──────────────────────────────────────────────────────────

def step(system, kind, max_requests=5):
    """Moves this system's backfill for one kind forward by one round. Returns counts and any stop reason."""
    reader = EtaReader(system)
    out = {'requested': 0, 'loaded': 0, 'split': 0, 'error': ''}
    reason = reader.why_not()
    if reason:
        out['error'] = reason
        return out
    waiting = list(W.objects.filter(system=system, kind=kind, state=W.REQUESTED).order_by('date_from'))
    try:
        if waiting:
            statuses = {str(p.get('packageId')): p for p in reader.package_requests(kind)}
            for w in waiting:
                info = statuses.get(w.package_id, {})
                status = info.get('status')
                if status == 4 or info.get('isExpired'):
                    w.state, w.package_id, w.error = W.PLANNED, '', 'انتهت صلاحية الحزمة لدى المصلحة؛ تُطلب من جديد'
                    w.save()
                    continue
                if status == 3:
                    w.attempts += 1
                    w.state = W.FAILED if w.attempts >= MAX_ATTEMPTS else W.PLANNED
                    w.package_id, w.error = '', 'المصلحة لم تستطع تجهيز الحزمة'
                    w.save()
                    continue
                if status not in (2, None):
                    continue
                data = reader.download_package(kind, w.package_id)
                if data is None:
                    continue
                rows = _rows_from_zip(data)
                count = (upsert_documents if kind == 'documents' else upsert_receipts)(system, rows, 'package')
                w.state, w.loaded_count, w.loaded_at, w.error = W.LOADED, count, timezone.now(), ''
                w.save()
                out['loaded'] += 1
        for w in W.objects.filter(system=system, kind=kind, state=W.PLANNED).order_by('date_from')[:max_requests]:
            try:
                pid = reader.request_package(kind, _body(kind, w))
            except EtaRefused as exc:
                if _too_big(exc):
                    _split(w, str(exc)[:300])
                    out['split'] += 1
                else:
                    w.attempts += 1
                    w.state = W.FAILED if w.attempts >= MAX_ATTEMPTS else W.PLANNED
                    w.error = str(exc)[:2000]
                    w.save()
                continue
            w.state, w.package_id, w.requested_at, w.error = W.REQUESTED, pid, timezone.now(), ''
            w.attempts += 1
            w.save()
            out['requested'] += 1
    except EtaError as exc:
        # Could not ask ETA: windows keep their state, the reason is kept beside the oldest unfinished one.
        out['error'] = str(exc)[:500]
        first = W.objects.filter(system=system, kind=kind).exclude(state=W.LOADED).order_by('date_from').first()
        if first:
            first.error = out['error']
            first.save(update_fields=['error'])
    return out


# ── reading ETA's rows ─────────────────────────────────────────────────────────────────────────

def _rows_from_zip(data):
    rows = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            if not name.lower().endswith('.json'):
                continue
            payload = json.loads(z.read(name).decode('utf-8-sig'))
            rows.extend(_as_rows(payload))
    return rows


def _as_rows(payload):
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ('result', 'documents', 'receipts', 'data', 'items'):
            if isinstance(payload.get(key), list):
                return [r for r in payload[key] if isinstance(r, dict)]
        return [payload]
    return []


def _get(row, *paths):
    """First non-empty value among dotted paths, case-insensitively at each level."""
    for path in paths:
        value = row
        for part in path.split('.'):
            if not isinstance(value, dict):
                value = None
                break
            lowered = {str(k).lower(): v for k, v in value.items()}
            value = lowered.get(part.lower())
        if value not in (None, ''):
            return value
    return None


def _text(value, size):
    return '' if value is None else str(value)[:size]


def _when(value):
    if not value:
        return None
    parsed = parse_datetime(str(value))
    if parsed and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, dt.timezone.utc)
    return parsed


def _money(value):
    if value in (None, ''):
        return None
    try:
        return Decimal(str(value)).quantize(Decimal('0.00001'))
    except InvalidOperation:
        return None


def _our_rin():
    issuer = TaxIssuerProfile.objects.first()
    return ''.join(c for c in (issuer.tax_id if issuer else '') if c.isdigit())


DOC_FIELDS = ['submission_uuid', 'internal_id', 'doc_type', 'type_version', 'direction', 'issuer_rin', 'issuer_name',
              'issuer_branch', 'receiver_type', 'receiver_id', 'receiver_name', 'issued_at', 'received_at', 'status',
              'net_amount', 'tax_amount', 'total_amount', 'currency', 'references', 'raw', 'source']


def upsert_documents(system, rows, source):
    """Insert or refresh documents by (system, uuid); the newest copy wins. Returns how many rows were given."""
    rin = _our_rin()
    objs = []
    for row in rows:
        uuid = _text(_get(row, 'uuid'), 64)
        if not uuid:
            continue
        issuer = _text(_get(row, 'issuerId', 'issuer.id'), 30)
        objs.append(EtaMirrorDocument(
            system=system, uuid=uuid, submission_uuid=_text(_get(row, 'submissionUUID', 'submissionUuid'), 64),
            internal_id=_text(_get(row, 'internalId', 'internalID'), 100),
            doc_type=_text(_get(row, 'typeName', 'documentType'), 5).lower(),
            type_version=_text(_get(row, 'typeVersionName', 'documentTypeVersion'), 10),
            direction='sent' if rin and issuer == rin else 'received',
            issuer_rin=issuer, issuer_name=_text(_get(row, 'issuerName', 'issuer.name'), 300),
            issuer_branch=_text(_get(row, 'issuer.address.branchID', 'issuerBranchId'), 50),
            receiver_type=_text(_get(row, 'receiverType', 'receiver.type'), 5),
            receiver_id=_text(_get(row, 'receiverId', 'receiver.id'), 50),
            receiver_name=_text(_get(row, 'receiverName', 'receiver.name'), 300),
            issued_at=_when(_get(row, 'dateTimeIssued')), received_at=_when(_get(row, 'dateTimeReceived')),
            status=_text(_get(row, 'status'), 20).lower(),
            net_amount=_money(_get(row, 'netAmount', 'net')), tax_amount=_money(_get(row, 'totalTaxAmount', 'taxAmount')),
            total_amount=_money(_get(row, 'totalAmount', 'total')), currency=_text(_get(row, 'currency'), 5) or 'EGP',
            references=_get(row, 'references') or [], raw=row, source=source))
    EtaMirrorDocument.objects.bulk_create(objs, batch_size=500, update_conflicts=True,
                                          unique_fields=['system', 'uuid'], update_fields=DOC_FIELDS)
    return len(objs)


RECEIPT_FIELDS = ['submission_uuid', 'previous_uuid', 'receipt_number', 'pos_serial', 'branch_number', 'issued_at',
                  'receipt_type', 'status', 'net_amount', 'tax_amount', 'total_amount', 'buyer_type', 'raw', 'source']


def upsert_receipts(system, rows, source):
    objs = []
    for row in rows:
        uuid = _text(_get(row, 'header.uuid', 'uuid'), 64)
        if not uuid:
            continue
        objs.append(EtaMirrorReceipt(
            system=system, uuid=uuid, submission_uuid=_text(_get(row, 'submissionUuid', 'submissionUUID'), 64),
            previous_uuid=_text(_get(row, 'header.previousUUID', 'previousUUID'), 64),
            receipt_number=_text(_get(row, 'header.receiptNumber', 'receiptNumber'), 100),
            pos_serial=_text(_get(row, 'seller.deviceSerialNumber', 'posSerialNumber', 'deviceSerialNumber'), 100),
            branch_number=_text(_get(row, 'seller.branchCode', 'branchCode', 'issuerBranchCode'), 50),
            issued_at=_when(_get(row, 'header.dateTimeIssued', 'dateTimeIssued')),
            receipt_type=_text(_get(row, 'documentType.receiptType', 'typeName', 'receiptType'), 5).lower(),
            status=_text(_get(row, 'status'), 20).lower(),
            net_amount=_money(_get(row, 'netAmount')), tax_amount=_money(_get(row, 'totalTaxAmount', 'taxAmount')),
            total_amount=_money(_get(row, 'totalAmount', 'total')), buyer_type=_text(_get(row, 'buyer.type', 'buyerType'), 5),
            raw=row, source=source))
    EtaMirrorReceipt.objects.bulk_create(objs, batch_size=500, update_conflicts=True,
                                         unique_fields=['system', 'uuid'], update_fields=RECEIPT_FIELDS)
    return len(objs)


# ── daily top-up ───────────────────────────────────────────────────────────────────────────────

SEARCH_PAGE = 100
MAX_PAGES = 200


def top_up(system, days=3):
    """Refreshes the last `days` days from ETA's search (documents sent and received, receipts), so recent
    status changes (a cancellation, a rejection) reach the mirror without waiting for a package."""
    reader = EtaReader(system)
    out = {'documents': 0, 'receipts': 0, 'error': ''}
    reason = reader.why_not()
    if reason:
        out['error'] = reason
        return out
    now = timezone.now()
    since = now - dt.timedelta(days=days)
    stamp = '%Y-%m-%dT%H:%M:%SZ'
    try:
        token = ''
        for _ in range(MAX_PAGES):
            params = {'submissionDateFrom': since.strftime(stamp), 'submissionDateTo': now.strftime(stamp),
                      'pageSize': SEARCH_PAGE, 'continuationToken': token}
            r = reader.get('/api/v1.0/documents/search', params)
            if r.status_code == 404:
                break
            if r.status_code != 200:
                raise EtaError(f'بحث المستندات HTTP {r.status_code}')
            payload = r.json() or {}
            out['documents'] += upsert_documents(system, _as_rows(payload.get('result') or []), 'search')
            token = str((payload.get('metadata') or {}).get('continuationToken') or '')
            if not token or token.lower() == 'endofresultset':
                break
        for page in range(1, MAX_PAGES + 1):
            params = {'DateTimeIssuedFrom': since.strftime(stamp), 'DateTimeIssuedTo': now.strftime(stamp),
                      'PageNo': page, 'PageSize': SEARCH_PAGE}
            r = reader.get('/api/v1/receipts/search', params)
            if r.status_code == 404 and (r.json() or {}).get('target') == 'NoResult':
                break
            if r.status_code != 200:
                raise EtaError(f'بحث الإيصالات HTTP {r.status_code}')
            payload = r.json() or {}
            out['receipts'] += upsert_receipts(system, _as_rows(payload.get('receipts') or payload.get('result') or []), 'search')
            if page >= int((payload.get('metadata') or {}).get('totalPages') or 1):
                break
    except EtaError as exc:
        out['error'] = str(exc)[:500]
    return out


def enabled_systems():
    from .eta_reader import SYSTEMS
    return [s for s in SYSTEMS if EtaReader(s).enabled()]


def start_date():
    from django.conf import settings
    try:
        return dt.date.fromisoformat(str(getattr(settings, 'TAX_ETA_HISTORY_START', '2022-06-01')))
    except ValueError:
        return dt.date(2022, 6, 1)


def last_loaded_at(system):
    """Newest moment anything from this system reached the mirror (freshness bar)."""
    times = [EtaMirrorDocument.objects.filter(system=system).aggregate(t=Max('fetched_at'))['t'],
             EtaMirrorReceipt.objects.filter(system=system).aggregate(t=Max('fetched_at'))['t'],
             W.objects.filter(system=system).aggregate(t=Max('loaded_at'))['t']]
    times = [t for t in times if t]
    return max(times) if times else None


# ── progress ───────────────────────────────────────────────────────────────────────────────────

def progress(system):
    out = {'system': system, 'why_not': EtaReader(system).why_not()}
    for kind in KINDS:
        qs = W.objects.filter(system=system, kind=kind)
        states = dict(qs.values_list('state').annotate(n=Count('id')))
        loaded = qs.filter(state=W.LOADED).aggregate(first=Min('date_from'), last=Max('date_to'), at=Max('loaded_at'))
        last_error = qs.exclude(error='').order_by('-requested_at', '-id').values_list('error', flat=True).first() or ''
        model = EtaMirrorDocument if kind == 'documents' else EtaMirrorReceipt
        out[kind] = {'states': {s: states.get(s, 0) for s, _ in W.STATES}, 'windows': qs.count(),
                     'rows': model.objects.filter(system=system).count(), 'loaded_from': loaded['first'],
                     'loaded_to': loaded['last'], 'last_loaded_at': loaded['at'], 'last_error': last_error}
    return out
