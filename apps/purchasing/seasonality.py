"""
apps/purchasing/seasonality.py — the seasonal index of each item for the month we are in
(owner 2026-10-25, «لوحة المشتريات الأمثل»).

Why a new one: forecasting.SeasonalityIndex is labelled "2 years" but our sales copy only
holds 12 months, it keeps one-off bulk sales in, and it divides each month by the year's
average (a growing item then looks "seasonal" late in the year). It also feeds the advanced
rate method (pushed to SOFTECH) — so it is left untouched; switching rates to this index is
an owner decision.

1. HISTORY — SOFTECH (server 100, SELECT only) network sales per item for the last
   MONTHS_BACK complete months, read invoice by invoice (doccode 115); real stock only (no
   service / adjustment / gift codes):
     an invoice is BULK when its quantity ≥ max(BULK_MIN_PACKS, BULK_FACTOR × the item's usual
     invoice quantity) — the usual quantity = the median invoice of the last 12 months in our
     own copy. Bulk quantity is kept apart (ItemMonthlySales.bulk_qty) and listed in the notes.
2. INDEX — ratio to a centred 12-month moving average (the trend is removed, so growth is not
   mistaken for season): ratio(year, month) = regular sales ÷ moving average; the index of a
   calendar month = the median of its ratios over the years (mean when only two; at least
   MIN_YEARS), normalised so
   the twelve months average 1.00, clamped to [INDEX_MIN, INDEX_MAX].
     • not enough history → no index («بيانات غير كافية»);
     • years that disagree (spread > UNSTABLE_SPREAD) → «غير مستقر».
Deterministic; read-only towards SOFTECH; writes our own tables only.
"""
import logging
import statistics
import threading
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db import connections, transaction
from django.utils import timezone

logger = logging.getLogger('elrezeiky.purchasing')

MONTHS_BACK = 48                 # four complete years → three measurements per calendar month
MIN_YEARS = 2                    # owner: at least two years to call a month seasonal
MIN_SELLING_MONTHS = 16          # months with sales, out of MONTHS_BACK
MIN_AVG_MONTHLY = 4.0            # packs / month across the network — below that a «season» is noise
BULK_MIN_PACKS = 10
BULK_FACTOR = 5
INDEX_MIN, INDEX_MAX = 0.3, 3.0
UNSTABLE_SPREAD = 0.5            # (max − min) ÷ mean of a month's ratios across the years
STRONG = 0.15                    # |index − 1| ≥ this → worth saying in the note
REFRESH_OVERLAP = 2              # re-pull the last N stored months (late entries)
STALE_RUNNING_HOURS = 3
MIN_WINDOW_SHARE = 0.4          # the 13 months around a measurement ≥ this × an average 13 months
AR_MONTHS = ['', 'يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو', 'يوليو', 'أغسطس', 'سبتمبر',
             'أكتوبر', 'نوفمبر', 'ديسمبر']

QUERY_MONTH = """
    SELECT st.itemcode, st.branchcode, st.docnumber, SUM(st.transqty)
    FROM SOFTECHDB9.dbo.stktrans st
    WHERE st.doccode = '115' AND st.docdate >= '{start}' AND st.docdate < '{end}'
      AND st.itemcode IS NOT NULL AND st.itemcode != '' AND st.transqty > 0
    GROUP BY st.itemcode, st.branchcode, st.docnumber
"""

_lock = threading.Lock()


def _first(d):
    return d.replace(day=1)


def _add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def history_months(today=None):
    """The MONTHS_BACK complete months, oldest first (the running month is never used)."""
    last = _add_months(_first(today or timezone.localdate()), -1)
    return [_add_months(last, -k) for k in range(MONTHS_BACK - 1, -1, -1)]


# ── 1. bulk threshold + SOFTECH pull ─────────────────────────────────────────────
def bulk_thresholds() -> dict:
    """{itemcode: packs} — an invoice at or above this is bulk. From our own last-12-month
    invoice copy (SalesTransactionLine is one row per invoice × item)."""
    from django.db import connection
    with connection.cursor() as cur:
        cur.execute("""
            SELECT softech_itemcode, percentile_cont(0.5) WITHIN GROUP (ORDER BY net_qty)
            FROM purchasing_salestransactionline
            WHERE doccode = '115' AND net_qty > 0
            GROUP BY softech_itemcode
        """)
        return {str(c).strip(): max(BULK_MIN_PACKS, BULK_FACTOR * float(m or 0)) for c, m in cur.fetchall()}


def split_invoices(invoice_qtys, threshold) -> dict:
    """[invoice qty, …] → {'qty', 'regular', 'bulk', 'invoices', 'bulk_invoices'}."""
    bulk = [q for q in invoice_qtys if q >= threshold]
    total = sum(invoice_qtys)
    return {'qty': total, 'regular': total - sum(bulk), 'bulk': sum(bulk),
            'invoices': len(invoice_qtys), 'bulk_invoices': len(bulk)}


def pull_month(cur, month, thresholds) -> dict:
    """{itemcode: split} for one calendar month, read from SOFTECH."""
    end = _add_months(month, 1)
    cur.execute(QUERY_MONTH.format(start=month.isoformat(), end=end.isoformat()))
    per = defaultdict(list)
    for code, _branch, _doc, qty in cur.fetchall():
        per[str(code).strip()].append(float(qty or 0))
    return {c: split_invoices(q, thresholds.get(c, BULK_MIN_PACKS)) for c, q in per.items()}


def _store_month(month, data, item_ids):
    from apps.purchasing.models import ItemMonthlySales
    D = lambda v: Decimal(str(round(v, 3)))
    with transaction.atomic():
        ItemMonthlySales.objects.filter(month=month).delete()
        ItemMonthlySales.objects.bulk_create([
            ItemMonthlySales(item_code=c, item_id=item_ids.get(c), month=month, qty=D(s['qty']),
                             regular_qty=D(s['regular']), bulk_qty=D(s['bulk']), invoices=s['invoices'],
                             bulk_invoices=s['bulk_invoices']) for c, s in data.items()], batch_size=2000)


# ── 2. the index ─────────────────────────────────────────────────────────────────
def compute_item(series, months, *, bulk_by_month=None):
    """series = regular qty per month (aligned with `months`, oldest first). Returns
    {calendar month: {'index', 'years', 'ratios', 'stable', 'bulk'}} or None (not enough data)."""
    n = len(series)
    selling = sum(1 for x in series if x > 0)
    if n < 37 or selling < MIN_SELLING_MONTHS or sum(series) / n < MIN_AVG_MONTHLY:
        return None
    ratios = defaultdict(list)
    avg13 = sum(series) / n * 13
    for t in range(6, n - 6):
        # a year when the item was not launched yet / long out of stock fakes a «season» — that
        # year's measurement is skipped unless the 13 months around it hold a normal volume
        # (a summer-only product keeps its index: every 13-month window still holds a summer)
        if sum(series[t - 6:t + 7]) < MIN_WINDOW_SHARE * avg13:
            continue
        ma = (0.5 * series[t - 6] + sum(series[t - 5:t + 6]) + 0.5 * series[t + 6]) / 12.0
        if ma > 0:
            ratios[months[t].month].append({'year': months[t].year, 'ratio': series[t] / ma})
    # median when three or more years (one odd year can't swing it), else the mean of two
    raw = {m: (statistics.median if len(rs) >= 3 else statistics.mean)(r['ratio'] for r in rs)
           for m, rs in ratios.items() if len(rs) >= MIN_YEARS}
    if len(raw) < 12:
        return None
    scale = 12.0 / sum(raw.values()) if sum(raw.values()) > 0 else 1.0
    out = {}
    for m in range(1, 13):
        rs = ratios[m]
        vals = [r['ratio'] for r in rs]
        mean = statistics.mean(vals)
        spread = (max(vals) - min(vals)) / mean if mean > 0 else 0.0
        out[m] = {'index': round(min(INDEX_MAX, max(INDEX_MIN, raw[m] * scale)), 3), 'years': len(rs),
                  'ratios': [{'year': r['year'], 'ratio': round(r['ratio'] * scale, 3)} for r in rs],
                  'stable': spread <= UNSTABLE_SPREAD,
                  'bulk': [(mo.year, b) for mo, b in (bulk_by_month or {}).get(m, []) if b > 0]}
    return out


def note_for(m, row, nxt=None):
    """The remarks column for calendar month m (Arabic)."""
    if row is None:
        return (f'لا يمكن تقدير الموسمية: يلزم سنتان على الأقل ومبيعات منتظمة لا تقل عن '
                f'{MIN_AVG_MONTHLY:g} عبوات شهرياً على الشبكة — يُعامل كمعتدل ×1.00.')
    idx, parts = row['index'], []
    pct = round((idx - 1) * 100)
    if idx >= INDEX_MAX or idx <= INDEX_MIN:              # capped — say so, not a fake percentage
        parts.append(f'{AR_MONTHS[m]} {"أعلى" if idx > 1 else "أقل"} من المتوسط بكثير (محدود عند ×{idx:g})')
    elif abs(idx - 1) >= STRONG:
        parts.append(f'{AR_MONTHS[m]} {"أعلى" if pct > 0 else "أقل"} من المتوسط {abs(pct)}%')
    else:
        parts.append(f'{AR_MONTHS[m]} قريب من المتوسط')
    years = ' / '.join(f"{r['year']}: ×{r['ratio']:.2f}" for r in row['ratios'])
    parts.append(f"{row['years']} سنوات ({years})" if row['years'] > 2 else f"سنتان ({years})")
    if not row['stable']:
        parts.append('⚠ غير مستقر — السنوات مختلفة، استخدمه بحذر')
    if row['bulk']:
        parts.append('استُبعدت مبيعات كبيرة: ' + '، '.join(f'{b:g} عبوة ({AR_MONTHS[m]} {y})' for y, b in row['bulk']))
    if nxt is not None:
        parts.append(f'الشهر التالي ×{nxt["index"]:.2f}')
    return ' · '.join(parts)


def compute_all(today=None):
    """Recompute ItemSeasonality for every item from the stored history."""
    from apps.purchasing.models import ItemMonthlySales, ItemSeasonality
    months = history_months(today)
    pos = {m: i for i, m in enumerate(months)}
    series = defaultdict(lambda: [0.0] * len(months))
    bulk = defaultdict(lambda: defaultdict(list))
    item_of = {}
    # real stock only — service / adjustment / gift / coupon codes («فرق سعر») never get a season
    for r in (ItemMonthlySales.objects.filter(month__in=months, item_id__isnull=False, item__is_stockable=True,
                                              item__pack_price__gt=0).exclude(item__medicine_type='60')
              .values('item_id', 'month', 'regular_qty', 'bulk_qty')):
        series[r['item_id']][pos[r['month']]] = float(r['regular_qty'] or 0)
        if r['bulk_qty']:
            bulk[r['item_id']][r['month'].month].append((r['month'], float(r['bulk_qty'])))
        item_of[r['item_id']] = True
    rows = []
    for iid in item_of:
        prof = compute_item(series[iid], months, bulk_by_month=bulk[iid])
        for m in range(1, 13):
            p = prof[m] if prof else None
            nxt = prof[m % 12 + 1] if prof else None
            rows.append(ItemSeasonality(
                item_id=iid, month=m, index=Decimal(str(p['index'])) if p else None,
                years=p['years'] if p else 0, ratios=p['ratios'] if p else [], stable=bool(p and p['stable']),
                bulk_qty=Decimal(str(round(sum(b for _y, b in p['bulk']), 3))) if p else Decimal('0'),
                note=note_for(m, p, nxt)))
    with transaction.atomic():
        ItemSeasonality.objects.all().delete()
        ItemSeasonality.objects.bulk_create(rows, batch_size=5000)
    return len(item_of)


# ── 3. running it (button + monthly catch-up) ─────────────────────────────────────
def running_run():
    from apps.purchasing.models import SeasonalityRun
    since = timezone.now() - timedelta(hours=STALE_RUNNING_HOURS)
    return SeasonalityRun.objects.filter(status='running', started_at__gte=since).first()


def last_success():
    from apps.purchasing.models import SeasonalityRun
    return SeasonalityRun.objects.filter(status='success').order_by('-finished_at').first()


def months_to_pull(today=None):
    """Months not stored yet + the last REFRESH_OVERLAP stored ones (late entries)."""
    from apps.purchasing.models import ItemMonthlySales
    months = history_months(today)
    have = set(ItemMonthlySales.objects.filter(month__in=months).values_list('month', flat=True).distinct())
    todo = [m for m in months if m not in have]
    return sorted(set(todo) | set(months[-REFRESH_OVERLAP:]))


def run_now(triggered_by, *, today=None):
    from apps.catalog.models import Item
    from apps.purchasing.models import SeasonalityRun
    from config.sybase import get_sybase_connection
    if not _lock.acquire(blocking=False):
        return None
    try:
        if running_run() is not None:
            return None
        todo = months_to_pull(today)
        run = SeasonalityRun.objects.create(triggered_by=triggered_by[:60], first_month=todo[0] if todo else None,
                                            last_month=todo[-1] if todo else None)
        try:
            thresholds = bulk_thresholds()
            item_ids = dict(Item.objects.values_list('softech_id', 'id'))
            conn = get_sybase_connection()
            cur = conn.cursor()
            try:
                for k, month in enumerate(todo, start=1):
                    run.progress = {'step': k - 1, 'steps': len(todo) + 1,
                                    'message': f'سحب مبيعات {AR_MONTHS[month.month]} {month.year} من SOFTECH'}
                    run.save(update_fields=['progress'])
                    _store_month(month, pull_month(cur, month, thresholds), item_ids)
                    run.months_pulled = k
            finally:
                cur.close()
                conn.close()
            run.progress = {'step': len(todo), 'steps': len(todo) + 1, 'message': 'حساب مؤشر الموسمية'}
            run.save(update_fields=['progress', 'months_pulled'])
            run.items = compute_all(today)
            run.status, run.finished_at = 'success', timezone.now()
        except Exception as exc:
            logger.exception('[seasonality] run failed')
            run.status, run.finished_at, run.error = 'failed', timezone.now(), str(exc)[:2000]
        run.save()
        return run
    finally:
        _lock.release()


def start_background(triggered_by) -> bool:
    if running_run() is not None or _lock.locked():
        return False

    def _worker():
        try:
            run_now(triggered_by)
        finally:
            connections.close_all()

    threading.Thread(target=_worker, name='seasonality', daemon=True).start()
    return True


def is_due(today=None) -> bool:
    """Due when the last success was before the current month started (a new month closed)."""
    last = last_success()
    start = _first(today or timezone.localdate())
    return last is None or timezone.localdate(last.finished_at) < start


def scheduled_tick():
    return run_now('scheduler') if is_due() else None


def freshness() -> dict:
    last = last_success()
    run = running_run()
    return {'at': last.finished_at if last else None, 'items': last.items if last else 0,
            'through': last.last_month if last else None, 'running': run is not None,
            'progress': (run.progress or {}) if run else None, 'started_at': run.started_at if run else None}
