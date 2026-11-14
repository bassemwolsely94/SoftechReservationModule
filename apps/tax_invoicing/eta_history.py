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

from django.db import DatabaseError, connection
from django.db.models import Count, Max, Min
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .eta_client import EtaError, EtaRefused
from .eta_reader import EtaReader
from .models import EtaHistoryState, EtaHistoryWindow, EtaMirrorDocument, EtaMirrorReceipt, TaxIssuerProfile

KINDS = ('documents', 'receipts')
WINDOW_DAYS = {'documents': 30, 'receipts': 4}
# ETA lets the issuer cancel and the receiver reject for about 7 days; documents also wait for a whole window.
TOPUP_DAYS = {'documents': 30, 'receipts': 7}
PACKAGE_LIST_PAGES = 5
MAX_ATTEMPTS = 5
W = EtaHistoryWindow


# ── planning ───────────────────────────────────────────────────────────────────────────────────

def plan_windows(system, kind, start, end):
    """Create the whole windows from `start` up to `end` (inclusive) after the newest existing one. A window that
    is not complete yet is left for the daily top-up, so planned days never overlap. Returns how many were created."""
    span = dt.timedelta(days=WINDOW_DAYS[kind])
    newest = W.objects.filter(system=system, kind=kind).order_by('-date_to').values_list('date_to', flat=True).first()
    day = max(start, newest + dt.timedelta(days=1)) if newest else start
    created = 0
    while day + span - dt.timedelta(days=1) <= end:
        last = day + span - dt.timedelta(days=1)
        _, new = W.objects.get_or_create(system=system, kind=kind, date_from=day, date_to=last)
        created += int(new)
        day = last + dt.timedelta(days=1)
    return created


def retry_failed(system, kind=None):
    """Puts failed windows back to planned (after the cause is fixed). Returns how many."""
    qs = W.objects.filter(system=system, state=W.FAILED)
    if kind:
        qs = qs.filter(kind=kind)
    return qs.update(state=W.PLANNED, attempts=0, error='', package_id='')


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
    w.state, w.error = W.SPLIT, f'قُسمت: {reason}'[:2000]
    w.save()
    W.objects.get_or_create(system=w.system, kind=w.kind, date_from=w.date_from, date_to=mid)
    W.objects.get_or_create(system=w.system, kind=w.kind, date_from=mid + dt.timedelta(days=1), date_to=w.date_to)


# ── one step: poll, download, request ──────────────────────────────────────────────────────────

def _try_lock(system):
    with connection.cursor() as cur:
        cur.execute('SELECT pg_try_advisory_lock(%s)', [_lock_key(system)])
        return bool(cur.fetchone()[0])


def _unlock(system):
    with connection.cursor() as cur:
        cur.execute('SELECT pg_advisory_unlock(%s)', [_lock_key(system)])


def _lock_key(system):
    return 0x45544148 + (1 if system == 'production' else 0)      # "ETAH" + system


def _record(system, kind, error):
    now = timezone.now()
    state, _ = EtaHistoryState.objects.get_or_create(system=system, kind=kind)
    state.last_run_at, state.last_error = now, (error or '')[:2000]
    if not error:
        state.last_ok_at = now
    state.save()


def _package_statuses(reader, kind):
    statuses = {}
    for page in range(1, PACKAGE_LIST_PAGES + 1):
        rows = reader.package_requests(kind, page=page)
        for p in rows:
            statuses[str(p.get('packageId'))] = p
        if len(rows) < 50:
            break
    return statuses


def _back_to_planned(w, reason, *, count=True):
    if count:
        w.attempts += 1
    w.state = W.FAILED if w.attempts >= MAX_ATTEMPTS else W.PLANNED
    w.package_id, w.error = '', reason[:2000]
    w.save()


def _collect(reader, system, kind, w, statuses, out):
    info = statuses.get(w.package_id, {})
    status = info.get('status')
    if status == 4 or info.get('isExpired'):
        _back_to_planned(w, 'انتهت صلاحية الحزمة لدى المصلحة؛ تُطلب من جديد', count=False)
        return
    if status == 3:
        _back_to_planned(w, 'المصلحة لم تستطع تجهيز الحزمة')
        return
    if status not in (2, None):
        return
    try:
        data = reader.download_package(kind, w.package_id)
    except EtaError as exc:
        if getattr(exc, 'http_status', None) in (404, 410):
            _back_to_planned(w, 'الحزمة غير موجودة لدى المصلحة؛ تُطلب من جديد', count=False)
            return
        raise
    if data is None:
        return
    try:
        rows = _rows_from_zip(data)
        upsert = upsert_documents if kind == 'documents' else upsert_receipts
        count = upsert(system, rows, 'package', older_than=w.requested_at)
    except (zipfile.BadZipFile, ValueError, DatabaseError) as exc:
        _back_to_planned(w, f'تعذرت قراءة الحزمة: {type(exc).__name__}')
        return
    w.state, w.loaded_count, w.loaded_at, w.error = W.LOADED, count, timezone.now(), ''
    w.save()
    out['loaded'] += 1


def step(system, kind, max_requests=5):
    """Moves this system's backfill for one kind forward by one round. Returns counts and any stop reason.
    One round per system at a time (the button and the scheduler never overlap)."""
    reader = EtaReader(system)
    out = {'requested': 0, 'loaded': 0, 'split': 0, 'error': '', 'busy': False}
    reason = reader.why_not()
    if reason:
        out['error'] = reason
        return out
    if not _try_lock(system):
        out['busy'] = True
        return out
    try:
        waiting = list(W.objects.filter(system=system, kind=kind, state=W.REQUESTED).order_by('date_from'))
        if waiting:
            statuses = _package_statuses(reader, kind)
            for w in waiting:
                _collect(reader, system, kind, w, statuses, out)
        for w in W.objects.filter(system=system, kind=kind, state=W.PLANNED).order_by('date_from')[:max_requests]:
            try:
                pid = reader.request_package(kind, _body(kind, w))
            except EtaRefused as exc:
                if getattr(exc, 'http_status', None) in (401, 403):
                    raise                       # a login / permission problem stops the round; windows keep their state
                if _too_big(exc):
                    _split(w, str(exc)[:300])
                    out['split'] += 1
                else:
                    _back_to_planned(w, str(exc))
                continue
            if not pid:
                _back_to_planned(w, 'لم ترجع المصلحة رقم الحزمة')
                continue
            w.state, w.package_id, w.requested_at, w.error = W.REQUESTED, pid, timezone.now(), ''
            w.attempts += 1
            w.save()
            out['requested'] += 1
    except EtaError as exc:
        out['error'] = str(exc)[:500]       # could not ask ETA: every window keeps its state
    finally:
        _unlock(system)
    _record(system, kind, out['error'])
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


def _newer_than(model, system, uuids, older_than):
    """uuids already refreshed after `older_than` (a package prepared before then is an older snapshot)."""
    if not older_than:
        return set()
    return set(model.objects.filter(system=system, uuid__in=uuids, fetched_at__gt=older_than).values_list('uuid', flat=True))


def _dedupe(objs):
    last = {}
    for o in objs:
        last[o.uuid] = o
    return list(last.values())


def upsert_documents(system, rows, source, older_than=None):
    """Insert or refresh documents by (system, uuid). A package never overwrites a row refreshed after the
    package was asked for. Returns how many distinct documents were taken."""
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
    objs = _dedupe(objs)
    skip = _newer_than(EtaMirrorDocument, system, [o.uuid for o in objs], older_than)
    taken = len(objs)
    objs = [o for o in objs if o.uuid not in skip]
    EtaMirrorDocument.objects.bulk_create(objs, batch_size=500, update_conflicts=True,
                                          unique_fields=['system', 'uuid'], update_fields=DOC_FIELDS)
    return taken


RECEIPT_FIELDS = ['submission_uuid', 'previous_uuid', 'receipt_number', 'pos_serial', 'branch_number', 'issued_at',
                  'receipt_type', 'status', 'net_amount', 'tax_amount', 'total_amount', 'buyer_type', 'raw', 'source']


def upsert_receipts(system, rows, source, older_than=None):
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
    objs = _dedupe(objs)
    skip = _newer_than(EtaMirrorReceipt, system, [o.uuid for o in objs], older_than)
    taken = len(objs)
    objs = [o for o in objs if o.uuid not in skip]
    EtaMirrorReceipt.objects.bulk_create(objs, batch_size=500, update_conflicts=True,
                                         unique_fields=['system', 'uuid'], update_fields=RECEIPT_FIELDS)
    return taken


# ── daily top-up ───────────────────────────────────────────────────────────────────────────────

SEARCH_PAGE = 100
MAX_PAGES = 200


def top_up(system, days=None):
    """Refreshes the last `days` days from ETA's search (documents sent and received, receipts), so recent
    status changes (a cancellation, a rejection) reach the mirror without waiting for a package."""
    reader = EtaReader(system)
    out = {'documents': 0, 'receipts': 0, 'error': ''}
    reason = reader.why_not()
    if reason:
        out['error'] = reason
        return out
    if not _try_lock(system):
        out['error'] = 'تحميل آخر يعمل الآن لهذه المنظومة'
        return out
    now = timezone.now()
    since = now - dt.timedelta(days=days or TOPUP_DAYS['documents'])
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
        since = now - dt.timedelta(days=days or TOPUP_DAYS['receipts'])
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
    finally:
        _unlock(system)
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
        state = EtaHistoryState.objects.filter(system=system, kind=kind).first()
        last_error = state.last_error if state else ''
        model = EtaMirrorDocument if kind == 'documents' else EtaMirrorReceipt
        out[kind] = {'states': {s: states.get(s, 0) for s, _ in W.STATES}, 'windows': qs.count(),
                     'rows': model.objects.filter(system=system).count(), 'loaded_from': loaded['first'],
                     'loaded_to': loaded['last'], 'last_loaded_at': loaded['at'], 'last_error': last_error}
    return out
