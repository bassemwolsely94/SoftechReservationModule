"""
apps/tax_invoicing/eta_history.py — copying what ETA holds into the history mirror, per ETA system.

Backfill reads ETA's search lists (spec §Phase 1b): ETA's packages only cover what the requesting ERP itself
submitted, and Invoicer submitted everything. Documents: 30-day windows by submission date from
TAX_ETA_HISTORY_START, following continuation tokens. Receipts: one-day windows by issue date from
TAX_ETA_HISTORY_RECEIPTS_START (ETA holds receipts from 2025), 100 per page; ETA returns at most 3000 per query, so a
longer window over that is split in halves and a single day over it is marked too_big — never cut. A window is
fetched whole in one round and keeps ETA's own count beside ours. "No results" is a loaded window with 0. When ETA
can't be reached the window keeps its state and the reason goes to the round record, so "not fetched yet" is never
read as "nothing there". Read only: nothing here sends anything to ETA.
"""
import datetime as dt
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import connection
from django.db.models import Count, Max, Min
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .eta_client import EtaError, EtaRefused, EtaUncertain, _json
from .eta_reader import EtaReader
from .models import EtaHistoryState, EtaHistoryWindow, EtaMirrorDocument, EtaMirrorReceipt, TaxIssuerProfile

KINDS = ('documents', 'receipts')
WINDOW_DAYS = {'documents': 30, 'receipts': 1}
# ETA lets the issuer cancel and the receiver reject for about 7 days; documents also wait for a whole window;
# Invoicer uploads a day's receipts late and in bursts, so receipts are re-read by issue date for 14 days.
TOPUP_DAYS = {'documents': 30, 'receipts': 14}
RECEIPT_CAP = 3000            # ETA's maximum per receipts search
PAGE = 100
MAX_PAGES = 400               # safety stop for one documents window (40,000 rows)
MAX_ATTEMPTS = 5
DOCS_PATH = '/api/v1.0/documents/search'
RECEIPTS_PATH = '/api/v1/receipts/search'
STAMP = '%Y-%m-%dT%H:%M:%SZ'
W = EtaHistoryWindow


class _TooBig(Exception):
    def __init__(self, total):
        super().__init__(total)
        self.total = total


# ── planning ───────────────────────────────────────────────────────────────────────────────────

def start_date(kind='documents'):
    name, default = (('TAX_ETA_HISTORY_RECEIPTS_START', '2025-01-01') if kind == 'receipts'
                     else ('TAX_ETA_HISTORY_START', '2022-06-01'))
    try:
        return dt.date.fromisoformat(str(getattr(settings, name, default) or default))
    except ValueError:
        return dt.date.fromisoformat(default)


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


def _split(w, total):
    days = (w.date_to - w.date_from).days + 1
    if days <= 1:
        w.state, w.eta_count = W.TOO_BIG, total
        w.error = f'المصلحة تعرض {total} إيصالاً في هذا اليوم، والحد {RECEIPT_CAP} للاستعلام الواحد'
        w.save()
        return
    mid = w.date_from + dt.timedelta(days=days // 2 - 1)
    w.state, w.eta_count, w.error = W.SPLIT, total, f'قُسمت: {total} أكبر من {RECEIPT_CAP}'
    w.save()
    W.objects.get_or_create(system=w.system, kind=w.kind, date_from=w.date_from, date_to=mid)
    W.objects.get_or_create(system=w.system, kind=w.kind, date_from=mid + dt.timedelta(days=1), date_to=w.date_to)


# ── reading ETA's search lists ─────────────────────────────────────────────────────────────────

def _no_result(resp):
    if resp.status_code != 404:
        return False
    body = _json(resp)
    if isinstance(body, dict) and body.get('target') == 'NoResult':
        return True
    raise EtaUncertain(f'رد غير متوقع من المصلحة (HTTP 404)', 404)


def _ok(resp, what):
    if resp.status_code == 200:
        body = _json(resp)
        return body if isinstance(body, dict) else {}
    if resp.status_code in (401, 403):
        raise EtaRefused(f'المصلحة رفضت {what} (HTTP {resp.status_code})', resp.status_code)
    if resp.status_code >= 400 and resp.status_code < 500:
        raise EtaRefused(f'المصلحة رفضت {what} (HTTP {resp.status_code})', resp.status_code)
    raise EtaUncertain(f'تعذر {what} (HTTP {resp.status_code})', resp.status_code)


def _fetch_documents(reader, system, since, until):
    """All documents submitted in [since, until), sent and received. Returns (loaded, eta_count)."""
    token, loaded = '', 0
    for _ in range(MAX_PAGES):
        resp = reader.get(DOCS_PATH, {'submissionDateFrom': since.strftime(STAMP), 'submissionDateTo': until.strftime(STAMP),
                                      'pageSize': PAGE, 'continuationToken': token})
        if _no_result(resp):
            break
        body = _ok(resp, 'بحث المستندات')
        loaded += upsert_documents(system, [r for r in body.get('result') or [] if isinstance(r, dict)], 'search')
        token = str((body.get('metadata') or {}).get('continuationToken') or '')
        if not token or token.lower() == 'endofresultset':
            break
    else:
        raise EtaUncertain('صفحات المستندات تجاوزت حد الأمان')
    return loaded, loaded


def _fetch_receipts(reader, system, since, until):
    """All receipts issued in [since, until), as ETA holds them now. Issue dates spread evenly (about 600 a day);
    received dates come in Invoicer's upload bursts. Returns (loaded, eta_count). Raises _TooBig over the cap."""
    loaded, total, page = 0, 0, 1
    while True:
        resp = reader.get(RECEIPTS_PATH, {'DateTimeIssuedFrom': since.strftime(STAMP), 'DateTimeIssuedTo': until.strftime(STAMP),
                                          'PageNo': page, 'PageSize': PAGE})
        if _no_result(resp):
            break
        body = _ok(resp, 'بحث الإيصالات')
        meta = body.get('metadata') or {}
        if page == 1:
            total = int(meta.get('totalCount') or 0)
            if total > RECEIPT_CAP:
                raise _TooBig(total)
        loaded += upsert_receipts(system, [r for r in body.get('receipts') or [] if isinstance(r, dict)], 'search')
        if page >= int(meta.get('totalPages') or 1):
            break
        page += 1
    return loaded, total


def _bounds(w):
    since = dt.datetime.combine(w.date_from, dt.time.min, tzinfo=dt.timezone.utc)
    until = dt.datetime.combine(w.date_to + dt.timedelta(days=1), dt.time.min, tzinfo=dt.timezone.utc)
    return since, until


# ── one round ──────────────────────────────────────────────────────────────────────────────────

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


def _back_to_planned(w, reason):
    w.attempts += 1
    w.state = W.FAILED if w.attempts >= MAX_ATTEMPTS else W.PLANNED
    w.error = reason[:2000]
    w.save()


def step(system, kind, max_windows=5):
    """Fetches up to `max_windows` windows of this system and kind, oldest first. Returns counts and any stop
    reason. One round per system at a time (the button and the scheduler never overlap)."""
    reader = EtaReader(system)
    out = {'loaded': 0, 'split': 0, 'too_big': 0, 'error': '', 'busy': False}
    reason = reader.why_not()
    if reason:
        out['error'] = reason
        return out
    if not _try_lock(system):
        out['busy'] = True
        return out
    fetch = _fetch_documents if kind == 'documents' else _fetch_receipts
    try:
        for w in W.objects.filter(system=system, kind=kind, state__in=[W.PLANNED, W.REQUESTED]).order_by('date_from')[:max_windows]:
            try:
                loaded, eta_count = fetch(reader, system, *_bounds(w))
            except _TooBig as big:
                _split(w, big.total)
                out['too_big' if w.state == W.TOO_BIG else 'split'] += 1
                continue
            except EtaRefused as exc:
                if getattr(exc, 'http_status', None) in (401, 403):
                    raise                       # a login / permission problem stops the round; windows keep their state
                _back_to_planned(w, str(exc))
                continue
            w.state, w.loaded_count, w.eta_count, w.loaded_at, w.error = W.LOADED, loaded, eta_count, timezone.now(), ''
            w.save()
            out['loaded'] += 1
    except EtaError as exc:
        out['error'] = str(exc)[:500]           # could not ask ETA: every window keeps its state
    finally:
        _unlock(system)
    _record(system, kind, out['error'])
    return out


# ── daily top-up ───────────────────────────────────────────────────────────────────────────────

def top_up(system, days=None):
    """Re-reads recent days from ETA's search (documents: 30 days in one query; receipts: day by day for 14 days,
    today included), so late status changes (a cancellation, a rejection) reach the mirror."""
    reader = EtaReader(system)
    out = {'documents': 0, 'receipts': 0, 'error': ''}
    reason = reader.why_not()
    if reason:
        out['error'] = reason
        return out
    if not _try_lock(system):
        out['error'] = 'تحميل آخر يعمل الآن لهذه المنظومة'
        return out
    today = timezone.now().date()
    tomorrow = dt.datetime.combine(today + dt.timedelta(days=1), dt.time.min, tzinfo=dt.timezone.utc)
    try:
        since = dt.datetime.combine(today - dt.timedelta(days=days or TOPUP_DAYS['documents']), dt.time.min, tzinfo=dt.timezone.utc)
        out['documents'] = _fetch_documents(reader, system, since, tomorrow)[0]
        for back in range((days or TOPUP_DAYS['receipts']), -1, -1):
            day = dt.datetime.combine(today - dt.timedelta(days=back), dt.time.min, tzinfo=dt.timezone.utc)
            try:
                out['receipts'] += _fetch_receipts(reader, system, day, day + dt.timedelta(days=1))[0]
            except _TooBig as big:
                out['error'] = f'يوم {day.date()} فيه {big.total} إيصالاً، أكثر من حد المصلحة'
    except EtaError as exc:
        out['error'] = str(exc)[:500]
    finally:
        _unlock(system)
    return out


def enabled_systems():
    from .eta_reader import SYSTEMS
    return [s for s in SYSTEMS if EtaReader(s).enabled()]


def last_loaded_at(system):
    """Newest moment anything from this system reached the mirror (freshness bar)."""
    times = [EtaMirrorDocument.objects.filter(system=system).aggregate(t=Max('fetched_at'))['t'],
             EtaMirrorReceipt.objects.filter(system=system).aggregate(t=Max('fetched_at'))['t'],
             W.objects.filter(system=system).aggregate(t=Max('loaded_at'))['t']]
    times = [t for t in times if t]
    return max(times) if times else None


# ── mapping ETA's rows ─────────────────────────────────────────────────────────────────────────

def _get(row, *keys):
    """First non-empty value among the keys, case-insensitively."""
    lowered = {str(k).lower(): v for k, v in row.items()}
    for key in keys:
        value = lowered.get(key.lower())
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


def _dedupe(objs):
    last = {}
    for o in objs:
        last[o.uuid] = o
    return list(last.values())


DOC_FIELDS = ['submission_uuid', 'internal_id', 'doc_type', 'type_version', 'direction', 'issuer_rin', 'issuer_name',
              'issuer_branch', 'receiver_type', 'receiver_id', 'receiver_name', 'issued_at', 'received_at', 'status',
              'net_amount', 'tax_amount', 'total_amount', 'currency', 'references', 'raw', 'source']


def upsert_documents(system, rows, source):
    """Insert or refresh documents by (system, uuid); the newest read wins. Returns how many distinct documents."""
    rin = _our_rin()
    objs = []
    for row in rows:
        uuid = _text(_get(row, 'uuid'), 64)
        if not uuid:
            continue
        issuer = _text(_get(row, 'issuerId'), 30)
        objs.append(EtaMirrorDocument(
            system=system, uuid=uuid, submission_uuid=_text(_get(row, 'submissionUUID'), 64),
            internal_id=_text(_get(row, 'internalId'), 100), doc_type=_text(_get(row, 'typeName'), 5).lower(),
            type_version=_text(_get(row, 'typeVersionName'), 10),
            direction='sent' if rin and issuer == rin else 'received', issuer_rin=issuer,
            issuer_name=_text(_get(row, 'issuerName'), 300), issuer_branch=_text(_get(row, 'issuerBranchId'), 50),
            receiver_type=_text(_get(row, 'receiverType'), 5), receiver_id=_text(_get(row, 'receiverId'), 50),
            receiver_name=_text(_get(row, 'receiverName'), 300),
            issued_at=_when(_get(row, 'dateTimeIssued')), received_at=_when(_get(row, 'dateTimeReceived')),
            status=_text(_get(row, 'status'), 20).lower(), net_amount=_money(_get(row, 'netAmount')),
            tax_amount=_money(_get(row, 'totalTaxAmount', 'taxAmount')), total_amount=_money(_get(row, 'total', 'totalAmount')),
            currency=_text(_get(row, 'currency'), 5) or 'EGP', references=_get(row, 'references') or [], raw=row,
            source=source))
    objs = _dedupe(objs)
    EtaMirrorDocument.objects.bulk_create(objs, batch_size=500, update_conflicts=True,
                                          unique_fields=['system', 'uuid'], update_fields=DOC_FIELDS)
    return len(objs)


RECEIPT_FIELDS = ['submission_uuid', 'previous_uuid', 'receipt_number', 'pos_serial', 'branch_number', 'issued_at',
                  'receipt_type', 'status', 'net_amount', 'tax_amount', 'total_amount', 'buyer_type', 'raw', 'source']


def upsert_receipts(system, rows, source):
    objs = []
    for row in rows:
        uuid = _text(_get(row, 'uuid'), 64)
        if not uuid:
            continue
        objs.append(EtaMirrorReceipt(
            system=system, uuid=uuid, submission_uuid=_text(_get(row, 'submissionUuid'), 64),
            previous_uuid=_text(_get(row, 'previousUUID'), 64), receipt_number=_text(_get(row, 'receiptNumber'), 100),
            pos_serial=_text(_get(row, 'posSerialNumber'), 100), branch_number=_text(_get(row, 'branchCode'), 50),
            issued_at=_when(_get(row, 'dateTimeIssued')), receipt_type=_text(_get(row, 'typeName'), 5).lower(),
            status=_text(_get(row, 'status'), 20).lower(), net_amount=_money(_get(row, 'netAmount')),
            tax_amount=_money(_get(row, 'totalTaxAmount')), total_amount=_money(_get(row, 'totalAmount')),
            buyer_type=_text(_get(row, 'receiverType'), 5), raw=row, source=source))
    objs = _dedupe(objs)
    EtaMirrorReceipt.objects.bulk_create(objs, batch_size=500, update_conflicts=True,
                                         unique_fields=['system', 'uuid'], update_fields=RECEIPT_FIELDS)
    return len(objs)


# ── progress ───────────────────────────────────────────────────────────────────────────────────

def progress(system):
    out = {'system': system, 'why_not': EtaReader(system).why_not()}
    for kind in KINDS:
        qs = W.objects.filter(system=system, kind=kind)
        states = dict(qs.values_list('state').annotate(n=Count('id')))
        loaded = qs.filter(state=W.LOADED).aggregate(first=Min('date_from'), last=Max('date_to'), at=Max('loaded_at'))
        state = EtaHistoryState.objects.filter(system=system, kind=kind).first()
        model = EtaMirrorDocument if kind == 'documents' else EtaMirrorReceipt
        out[kind] = {'states': {s: states.get(s, 0) for s, _ in W.STATES}, 'windows': qs.count(),
                     'rows': model.objects.filter(system=system).count(), 'loaded_from': loaded['first'],
                     'loaded_to': loaded['last'], 'last_loaded_at': loaded['at'],
                     'last_error': state.last_error if state else '', 'start': start_date(kind)}
    return out
