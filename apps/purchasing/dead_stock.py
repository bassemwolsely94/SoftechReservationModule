"""
apps/purchasing/dead_stock.py

P-27 part A «🧊 مخزون راكد» (docs/product-review/06_SPEC_P-27_dead_stock_recovery.md, doc 22). Read-only: PostgreSQL
only — no SOFTECH read or write, no transfer or return document. One function decides dead / lane / targets; the tab,
the Excel and (later) part B all read its output.

Dead (per item × branch, latest successful engine run):
  • stock > 0, the branch is live (kind hq/retail — closed, pending and CC never), the item is stockable and not a strategic hold;
  • no local sale for N months (SystemSetting dead_stock_months, default 6) — `last_sale_date` null or older;
  • and the oldest unit on hand arrived N+ months ago — FIFO over the stock-ledger arrivals of the last year
    (expiry_audit._fifo_oldest_date); no arrival in the year → «أقدم من سنة».
  • HQ (hq_code()) is a warehouse, not a selling point: there a line is dead only when no branch sells the item.
Network rate = Σ monthly_avg at the other active branches (HQ excluded). Value = stock × Item.cost_price.
Lanes: move «يُباع بفرع آخر» (network rate > 0) · return «مرتجع للمورد» (rate 0, latest supplier's class in
dead_stock_return_classes) · stop «إيقاف» (otherwise).
Move targets: other active branches that sell it (never HQ), not one that sent the item out in the last N months,
room = max(0, engine gap), largest room first (fastest seller first when the source has a lot expiring within 180
days), whole packs, at most 4. Under dead_stock_min_move_value EGP (100) → flagged, not proposed. Fridge items:
listed, never proposed. An open rebalance transfer for item + source → «متعارض».
"""
import calendar
import datetime as dt
from collections import defaultdict
from decimal import ROUND_DOWN, Decimal


def _hq():
    """HQ's SOFTECH branch code (the one Branch of kind hq), looked up at call time — never at
    import (module import must not hit the DB)."""
    from apps.branches.models import hq_code
    return hq_code()


DEFAULT_MONTHS = 6
DEFAULT_MIN_MOVE_VALUE = Decimal('100')
DEFAULT_RETURN_CLASSES = ('20', '60', '70', '50')
SHORT_DATED_DAYS = 180
MAX_TARGETS = 4
ZERO = Decimal('0')


def months_ago(today, months):
    y, m = divmod(today.year * 12 + today.month - 1 - months, 12)
    m += 1
    return dt.date(y, m, min(today.day, calendar.monthrange(y, m)[1]))


def cfg():
    from apps.config.models import SystemSetting
    try:
        months = int(SystemSetting.get('dead_stock_months', DEFAULT_MONTHS) or DEFAULT_MONTHS)
    except (TypeError, ValueError):
        months = DEFAULT_MONTHS
    try:
        min_value = Decimal(str(SystemSetting.get('dead_stock_min_move_value', DEFAULT_MIN_MOVE_VALUE)))
    except Exception:
        min_value = DEFAULT_MIN_MOVE_VALUE
    raw = SystemSetting.get('dead_stock_return_classes', ','.join(DEFAULT_RETURN_CLASSES))
    classes = raw if isinstance(raw, (list, tuple)) else [c.strip() for c in str(raw or '').split(',') if c.strip()]
    return {'months': months, 'min_move_value': min_value, 'return_classes': tuple(classes)}


# ── the classifier (pure) ────────────────────────────────────────────────────

def classify(rows, *, today, active, arrivals, suppliers, soonest_expiry=None, sent_out=None, open_transfers=None,
             windows=None, months=DEFAULT_MONTHS, min_move_value=DEFAULT_MIN_MOVE_VALUE,
             return_classes=DEFAULT_RETURN_CLASSES):
    """rows: [{item, item_id, name, branch, stock, rate, gap, last_sale, qty_365d, cost, hold, stockable, fridge,
    no_more_use}] — one per item × branch. arrivals: {(branch, item): [(date, qty)] newest first}.
    active = the live branch codes (build() passes Branch.objects.live()); rows elsewhere are ignored.
    suppliers: {item: (supplier_code, class)}. soonest_expiry: {(branch, item): date}. sent_out: {(branch, item):
    last date it left that branch}. open_transfers: {(item, source): number}. Returns lines, ranked."""
    from apps.batches.expiry_audit import _fifo_oldest_date
    soonest_expiry, sent_out = soonest_expiry or {}, sent_out or {}
    open_transfers, windows = open_transfers or {}, windows or {}
    cutoff = months_ago(today, months)
    by_item = defaultdict(list)
    for r in rows:
        if r['branch'] in active:
            by_item[r['item']].append(r)

    out = []
    for item, item_rows in by_item.items():
        sellers = {r['branch']: r for r in item_rows if r['branch'] != _hq() and r['rate'] > 0}
        dead = []
        for r in item_rows:
            if r['stock'] <= 0 or r['hold'] or not r['stockable']:
                continue
            others = sum((s['rate'] for b, s in sellers.items() if b != r['branch']), ZERO)
            if r['branch'] == _hq():
                if others > 0:
                    continue                              # warehouse stock a branch still sells
            elif r['last_sale'] is not None and r['last_sale'] >= cutoff:
                continue
            arr = arrivals.get((r['branch'], item)) or []
            oldest = _fifo_oldest_date(arr, r['stock']) if arr else None
            if oldest is not None and oldest > cutoff:
                continue                                  # fresh stock: a trial seed or a recent move in
            dead.append((r, others, oldest))
        if not dead:
            continue
        at_hq = any(r['branch'] == _hq() for r, _, _ in dead)
        at_branches = any(r['branch'] != _hq() for r, _, _ in dead)
        location = 'both' if at_hq and at_branches else 'hq_only' if at_hq else 'branches_only'
        sup_code, sup_class = suppliers.get(item, ('', ''))
        for r, others, oldest in dead:
            value = (r['stock'] * r['cost']).quantize(Decimal('0.01'))
            if location == 'both' or r['no_more_use']:
                cause = 'obsolete'
            elif location == 'hq_only':
                cause = 'supplier_push'
            elif r['qty_365d'] > 0:
                cause = 'demand_died'
            else:
                cause = ''
            if others > 0:
                lane = 'move'
            elif sup_class in return_classes:
                lane = 'return'
            else:
                lane = 'stop'
            expiry = soonest_expiry.get((r['branch'], item))
            short = bool(expiry and expiry <= today + dt.timedelta(days=SHORT_DATED_DAYS))
            flags = {'fridge': bool(r['fridge']), 'below_threshold': False,
                     'conflict': open_transfers.get((item, r['branch']), '')}
            targets, move_value = [], ZERO
            if lane == 'move' and not r['fridge']:
                cands = [s for b, s in sellers.items() if b != r['branch'] and b != _hq()
                         and not (sent_out.get((b, item)) and sent_out[(b, item)] >= cutoff)]
                key = (lambda s: (-s['rate'], s['branch'])) if short else \
                      (lambda s: (-max(s['gap'], ZERO), s['branch']))
                cands = sorted(cands, key=key)[:MAX_TARGETS]
                left = int(r['stock'].to_integral_value(rounding=ROUND_DOWN))
                for s in cands:
                    q = int(min(max(s['gap'], ZERO), left))
                    if q < 1:
                        continue
                    targets.append({'branch': s['branch'], 'qty': q, 'room': float(max(s['gap'], ZERO)),
                                    'rate': float(s['rate'])})
                    left -= q
                    if left < 1:
                        break
                move_value = sum((Decimal(t['qty']) * r['cost'] for t in targets), ZERO).quantize(Decimal('0.01'))
                flags['below_threshold'] = move_value < min_move_value
            out.append({
                'item': item, 'item_id': r['item_id'], 'name': r['name'], 'branch': r['branch'], 'lane': lane,
                'location': location, 'cause': cause, 'qty': r['stock'], 'value': value,
                'last_sale': r['last_sale'], 'oldest_arrival': oldest,
                'age_note': 'older_than_year' if oldest is None else '', 'network_rate': others,
                'targets': targets, 'move_value': move_value, 'soonest_expiry': expiry, 'short_dated': short,
                'supplier_code': sup_code, 'supplier_class': sup_class,
                'window_state': windows.get((r['branch'], item), '') if lane == 'return' else '', 'flags': flags,
            })
    out.sort(key=lambda l: (not l['short_dated'], -l['value'], l['item'], l['branch']))
    return out


# ── loader (PostgreSQL only) ─────────────────────────────────────────────────

def _rows(run):
    from apps.purchasing.models import ItemDemandMetrics
    return [{'item': m['item__softech_id'], 'item_id': m['item_id'], 'name': m['item__name'],
             'branch': str(m['branch__softech_branch_id']), 'stock': m['current_stock'] or ZERO,
             'rate': m['monthly_avg'] or ZERO, 'gap': m['gap'] or ZERO, 'last_sale': m['last_sale_date'],
             'qty_365d': m['qty_365d'] or ZERO, 'cost': m['item__cost_price'] or ZERO,
             'hold': m['item__strategic_hold'], 'stockable': m['item__is_stockable'],
             'fridge': m['item__requires_fridge'], 'no_more_use': m['item__no_more_use']}
            for m in ItemDemandMetrics.objects.filter(run=run).values(
                'item_id', 'item__softech_id', 'item__name', 'branch__softech_branch_id', 'current_stock',
                'monthly_avg', 'gap', 'last_sale_date', 'qty_365d', 'item__cost_price', 'item__strategic_hold',
                'item__is_stockable', 'item__requires_fridge', 'item__no_more_use')]


def _arrivals(pairs, today):
    """{(branch, item): [(date, qty)] newest first} from the stock-ledger mirror (arrival doccodes, last year)."""
    from apps.batches.expiry_audit import ARRIVAL_DOCCODES
    from apps.stock_audit.models import StockLedgerLine
    out = defaultdict(list)
    if not pairs:
        return out
    branches, items = {b for b, _ in pairs}, {i for _, i in pairs}
    for b, i, d, q in (StockLedgerLine.objects.filter(doccode__in=ARRIVAL_DOCCODES, branchcode__in=branches,
                                                      itemcode__in=items, docdate__gte=today - dt.timedelta(days=365),
                                                      transqty__gt=0)
                       .order_by('-docdate', '-trans_time').values_list('branchcode', 'itemcode', 'docdate',
                                                                        'transqty')):
        if (b, i) in pairs:
            out[(b, i)].append((d, q))
    return out


def _suppliers(items):
    """{item: (supplier_code, class)} — supplier of the item's most recent doc 10 purchase line."""
    from apps.procurement.models import PurchaseLine, SupplierProfile
    latest = {}
    for i, s in (PurchaseLine.objects.filter(doccode='10', item_code__in=items)
                 .order_by('item_code', '-doc_date').values_list('item_code', 'supplier_code')):
        latest.setdefault(i, str(s).strip())
    classes = dict(SupplierProfile.objects.filter(supplier_code__in=set(latest.values()))
                   .values_list('supplier_code', 'classif_code'))
    return {i: (s, str(classes.get(s, '') or '').strip()) for i, s in latest.items()}


def _expiry_and_windows(pairs, items, today, suppliers):
    """Soonest live-store expiry per (branch, item), and the P-29 window state of that lot."""
    from apps.batches.models import StockExpiryBalance
    from apps.batches.return_window import window_for
    soonest = {}
    for b, i, e in (StockExpiryBalance.objects.filter(item_code__in=items, store_role='live', qty__gt=0,
                                                      expiry_date__isnull=False)
                    .values_list('branch_code', 'item_code', 'expiry_date')):
        if (b, i) in pairs and (soonest.get((b, i)) is None or e < soonest[(b, i)]):
            soonest[(b, i)] = e
    windows = {k: window_for(e, today)['state'] for k, e in soonest.items()}
    return soonest, windows


def _sent_out(items, since):
    """{(branch, item): last date that branch issued the item to another branch/HQ} (ledger doc 125)."""
    from apps.stock_audit.models import StockLedgerLine
    out = {}
    for b, i, d in (StockLedgerLine.objects.filter(doccode='125', itemcode__in=items, docdate__gte=since)
                    .values_list('branchcode', 'itemcode', 'docdate')):
        if out.get((b, i)) is None or d > out[(b, i)]:
            out[(b, i)] = d
    return out


def _open_transfers(items):
    from apps.batches.rebalance import OPEN_TRANSFER
    from apps.transfers.models import TransferRequestItem
    return {(str(i), str(s)): n for i, s, n in (
        TransferRequestItem.objects.filter(item__softech_id__in=items, request__status__in=OPEN_TRANSFER)
        .values_list('item__softech_id', 'request__supplying_branch__softech_branch_id', 'request__request_number'))}


def build(run, today):
    from apps.branches.models import Branch
    c = cfg()
    active = set(Branch.objects.live().values_list('softech_branch_id', flat=True))   # closed/pending/CC never
    rows = [r for r in _rows(run) if r['branch'] in active]
    pairs = {(r['branch'], r['item']) for r in rows if r['stock'] > 0}
    items = {i for _, i in pairs}
    suppliers = _suppliers(items)
    soonest, windows = _expiry_and_windows(pairs, items, today, suppliers)
    lines = classify(rows, today=today, active=active, arrivals=_arrivals(pairs, today), suppliers=suppliers,
                     soonest_expiry=soonest, sent_out=_sent_out(items, months_ago(today, c['months'])),
                     open_transfers=_open_transfers(items), windows=windows, months=c['months'],
                     min_move_value=c['min_move_value'], return_classes=c['return_classes'])
    return lines, c


def compute_snapshot(run, today=None):
    """Build and store the list for `run` (replacing that run's lines in one transaction)."""
    from django.db import transaction
    from django.utils import timezone
    from apps.purchasing.models import DeadStockLine, DeadStockSnapshot
    today = today or timezone.localdate()
    lines, c = build(run, today)
    totals = defaultdict(lambda: {'count': 0, 'qty': 0.0, 'value': 0.0})
    for l in lines:
        for key in (l['lane'], f"{l['lane']}:{l['location']}", f"{l['lane']}:{l['branch']}"):
            t = totals[key]
            t['count'] += 1
            t['qty'] += float(l['qty'])
            t['value'] += float(l['value'])
    settings_used = {'months': c['months'], 'min_move_value': str(c['min_move_value']),
                     'return_classes': list(c['return_classes']), 'today': today.isoformat()}
    with transaction.atomic():
        snap, _ = DeadStockSnapshot.objects.update_or_create(
            run=run, defaults={'as_of': today, 'settings_used': settings_used, 'totals': dict(totals)})
        snap.lines.all().delete()
        DeadStockLine.objects.bulk_create([DeadStockLine(
            snapshot=snap, item_id=l['item_id'], branch_code=l['branch'], lane=l['lane'], location=l['location'],
            cause=l['cause'], qty=l['qty'], value=l['value'], last_sale_date=l['last_sale'],
            oldest_arrival_date=l['oldest_arrival'], age_note=l['age_note'], network_rate=l['network_rate'],
            targets=l['targets'], move_value=l['move_value'], soonest_expiry=l['soonest_expiry'],
            supplier_code=l['supplier_code'], supplier_class=l['supplier_class'], window_state=l['window_state'],
            flags=l['flags'], rank=n) for n, l in enumerate(lines)], batch_size=1000)
    return snap


def latest_snapshot():
    from apps.purchasing.models import DeadStockSnapshot
    return DeadStockSnapshot.objects.select_related('run').order_by('-run__finished_at', '-run_id').first()


def ensure_latest():
    """Scheduler: build the list for the latest successful engine run if it has none yet. Returns the snapshot or
    None."""
    from apps.purchasing.models import DeadStockSnapshot
    from apps.purchasing.rate_writer import _latest_run
    run = _latest_run()
    if run is None or DeadStockSnapshot.objects.filter(run=run).exists():
        return None
    return compute_snapshot(run)
