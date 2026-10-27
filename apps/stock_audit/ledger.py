"""
apps/stock_audit/ledger.py

Doc 32 Phase 1 — mirror SOFTECH `stktrans` (every doccode) from HQ into StockLedgerLine.

  • HQ only: Phase 0 showed HQ holds every branch's lines (branch 160: 158,430 = 158,430).
  • Indexed predicate: a docdate range (`stktrans_60` = docdate, doccode); trans_time is unindexed.
  • stktrans has no line id → each chunk REPLACES the docdate days it covers, in one transaction.
    Idempotent; picks up SOFTECH edits/deletes inside the window; a failed chunk keeps the old rows.
  • READ-ONLY against SOFTECH (SELECT only). ~3k lines/day.
"""
import datetime as _dt
import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger('elrezeiky.stock_audit')

# Order matters: _row_to_obj reads by position.
COLUMNS = [
    'branchcode', 'doccode', 'docnumber', 'docdate', 'trans_time', 'storecode', 'storecode2',
    'usercode', 'personcode', 'suppliercode', 'itemcode', 'itemexpirydate',
    'transqty', 'newqty', 'bonusqty', 'retqty', 'transprice', 'transprice_total', 'newcostprice',
    'itemsaleprice', 'itemsalestax', 'itemsaleprice_tax', 'pharmacydiscp', 'additionaldiscp',
    'custdiscp', 'specialdiscp',
    'r_doccode', 'r_docnumber', 'r_docdate', 's_doccode', 's_docnumber', 's_docdate',
]

_SQL = (
    'SELECT ' + ', '.join(f'st.{c}' for c in COLUMNS) + ' '
    'FROM SOFTECHDB9.dbo.stktrans st '
    "WHERE st.docdate >= '{d1}' AND st.docdate < '{d2}'"
)

_DECIMALS = {'transqty': 5, 'newqty': 5, 'bonusqty': 5, 'retqty': 5, 'transprice': 4,
             'transprice_total': 4, 'newcostprice': 4, 'itemsaleprice': 3, 'itemsalestax': 4,
             'itemsaleprice_tax': 4, 'pharmacydiscp': 4, 'additionaldiscp': 2, 'custdiscp': 2,
             'specialdiscp': 2}
_STRINGS = {'branchcode': 5, 'doccode': 3, 'storecode': 3, 'storecode2': 3, 'usercode': 5,
            'personcode': 8, 'suppliercode': 8, 'itemcode': 6, 'r_doccode': 3, 's_doccode': 3}
_DATES = {'docdate', 'itemexpirydate', 'r_docdate', 's_docdate'}
_NUMBERS = {'docnumber', 'r_docnumber', 's_docnumber'}


def window_days():
    return int(getattr(settings, 'STOCK_AUDIT_WINDOW_DAYS', 365))


# ── value cleaning ────────────────────────────────────────────────────────────

def _s(v, n):
    return '' if v is None else str(v).replace('\x00', '').strip()[:n]


def _dec(v, places):
    if v is None:
        return Decimal('0')
    try:
        return Decimal(str(v)).quantize(Decimal(1).scaleb(-places))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal('0')


def _num(v):
    """decimal(10,0) docnumbers arrive as floats ('418293.0'); 0 / blank → None."""
    if v is None or str(v).strip() in ('', '0', '0.0'):
        return None
    try:
        return int(Decimal(str(v)))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _date(v):
    if v is None:
        return None
    if isinstance(v, _dt.datetime):
        d = v.date()
    elif isinstance(v, _dt.date):
        d = v
    else:
        try:
            d = _dt.datetime.strptime(str(v)[:10], '%Y-%m-%d').date()
        except ValueError:
            return None
    return None if d.year <= 1900 else d   # SOFTECH writes 1900-01-01 for "no date"


def _aware(v):
    if not isinstance(v, _dt.datetime):
        return None
    return v if timezone.is_aware(v) else timezone.make_aware(v, timezone.get_default_timezone())


def row_to_line(row, item_ids):
    """One stktrans row (COLUMNS order) → unsaved StockLedgerLine, or None when unusable."""
    from .models import StockLedgerLine
    rec = dict(zip(COLUMNS, row))
    data = {}
    for c, v in rec.items():
        if c in _DECIMALS:
            data[c] = _dec(v, _DECIMALS[c])
        elif c in _STRINGS:
            data[c] = _s(v, _STRINGS[c])
        elif c in _DATES:
            data[c] = _date(v)
        elif c in _NUMBERS:
            data[c] = _num(v)
        elif c == 'trans_time':
            data[c] = _aware(v)
    if not data['branchcode'] or not data['doccode'] or not data['itemcode'] \
            or data['docnumber'] is None or data['docdate'] is None:
        return None
    data['item_id'] = item_ids.get(data['itemcode'])
    return StockLedgerLine(**data)


# ── fetch (HQ) ────────────────────────────────────────────────────────────────

class _HqFetcher:
    """Reuses one HQ connection across chunks; reopened once if it drops."""

    def __init__(self, timeout):
        self.timeout = timeout
        self.conn = None

    def __call__(self, d1, d2):
        sql = _SQL.format(d1=d1.strftime('%Y%m%d'), d2=d2.strftime('%Y%m%d'))
        for attempt in (1, 2):
            try:
                if self.conn is None:
                    from config.sybase import get_sybase_connection
                    self.conn = get_sybase_connection()
                cur = self.conn.cursor()
                cur.execute(sql, timeout=self.timeout)
                return cur.fetchall()
            except Exception:
                self.close()
                if attempt == 2:
                    raise

    def close(self):
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None


def _chunks(date_from, date_to, days):
    d = date_from
    while d < date_to:
        nxt = min(d + _dt.timedelta(days=days), date_to)
        yield d, nxt
        d = nxt


# ── public API ────────────────────────────────────────────────────────────────

def sync_ledger(date_from, date_to, run=None, fetch=None, chunk_days=7, timeout=600, prune=True):
    """
    Replace StockLedgerLine for docdate in [date_from, date_to) with what SOFTECH HQ holds.
    `fetch(d1, d2)` → rows in COLUMNS order (injected in tests). Returns a summary dict;
    fills and finishes `run` (StockLedgerSyncRun) when given.
    """
    from apps.catalog.models import Item
    from .models import StockLedgerLine

    item_ids = dict(Item.objects.values_list('softech_id', 'id'))
    own_fetch = fetch is None
    fetch = fetch or _HqFetcher(timeout)
    detail, rows_total, ok, failed = {}, 0, 0, 0
    try:
        for d1, d2 in _chunks(date_from, date_to, chunk_days):
            key = d1.isoformat()
            try:
                raw = fetch(d1, d2)
            except Exception as e:
                failed += 1
                detail[key] = {'ok': False, 'to': d2.isoformat(), 'error': str(e)[:200]}
                logger.warning('[StockLedger] chunk %s→%s failed: %s', d1, d2, e)
                continue
            objs = [o for o in (row_to_line(r, item_ids) for r in raw) if o is not None]
            with transaction.atomic():
                StockLedgerLine.objects.filter(docdate__gte=d1, docdate__lt=d2).delete()
                StockLedgerLine.objects.bulk_create(objs, batch_size=2000)
            ok += 1
            rows_total += len(objs)
            detail[key] = {'ok': True, 'to': d2.isoformat(), 'rows': len(objs),
                           'skipped': len(raw) - len(objs)}
    finally:
        if own_fetch:
            fetch.close()

    pruned = prune_ledger() if prune and ok else 0
    status = 'success' if failed == 0 else ('partial' if ok else 'failed')
    if run is not None:
        run.date_from, run.date_to = date_from, date_to
        run.chunks_ok, run.chunks_failed = ok, failed
        run.rows_synced, run.rows_pruned = rows_total, pruned
        run.detail = detail
        run.finish(status)
    logger.info('[StockLedger] %s→%s %s: %d rows, %d chunks ok, %d failed, %d pruned',
                date_from, date_to, status, rows_total, ok, failed, pruned)
    return {'status': status, 'rows': rows_total, 'chunks_ok': ok, 'chunks_failed': failed,
            'pruned': pruned, 'detail': detail}


def prune_ledger(today=None):
    """Drop lines older than the rolling window."""
    from .models import StockLedgerLine
    today = today or timezone.localdate()
    cutoff = today - _dt.timedelta(days=window_days())
    deleted, _ = StockLedgerLine.objects.filter(docdate__lt=cutoff).delete()
    return deleted


def recent_range(days, today=None):
    """[today − days + 1, tomorrow) — `days` docdate days ending today."""
    today = today or timezone.localdate()
    return today - _dt.timedelta(days=max(int(days), 1) - 1), today + _dt.timedelta(days=1)
