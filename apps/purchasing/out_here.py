"""
apps/purchasing/out_here.py — C06 «ناقص هنا · موجود هناك» (P-30 list without waiting for newqty). READ-ONLY.

docs/full-project-audit/08_BUSINESS_OPTIMIZATION_OPPORTUNITIES.md §C06: about a third of the engine's estimated lost
revenue is «transfer» — the stock existed at another branch while this one waited for the next ISR. This list shows,
from TODAY's stock (catalog.ItemStock, sellable stores only), every A/B item at zero at a retail branch while another
live branch holds stock above its safety level, and how much each could send.

No new matching rule: the deficit ↔ surplus pairing IS transfer_engine.TransferEngine._match_all, fed live numbers:
  • destination = a retail branch (Branch.objects.live(), so closed / pending / call centre never appear) where the
    item is class A or B in the latest successful engine run, sells (monthly_avg > 0), and has ≤ 0 sellable stock now;
    its need = the engine's target level (gap + engine stock) − live stock — in-transit stays netted, so an item
    already on its way is not listed;
  • source = any live branch (HQ included) with the engine row's safety stock; surplus = live stock − safety stock,
    so a source never drops below its safety stock (the transfer engine's rule);
  • priority = the destination's need (the engine's (1 − cover) × gap at zero cover).
newqty (apps/stock_audit/newqty_check.py) stays the gate only for MEASURED stock-out duration; this list does not need it.

Nothing is written anywhere — no transfer, ISR or SOFTECH call. The hand-off is the person: the transfer itself is
made on the transfers screen. Deterministic; quantities are kept fractional (the approver rounds), like the engine.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from types import SimpleNamespace

ZERO = Decimal('0')
CLASSES = ('A', 'B')


def _d(v) -> Decimal:
    return Decimal(str(v)) if v is not None else ZERO


def latest_run():
    from .cover_tiers import latest_run as _lr
    return _lr()


def build(run=None, dest_codes=None, classes=CLASSES) -> dict:
    """{'run', 'calc_date', 'rows', 'branches'}. dest_codes = the destination branch codes in view (None = all retail).
    rows: one per (destination branch, item) with its sources; branches: every retail branch in view with its counts
    (a branch with nothing to fix still shows, with 0)."""
    from django.db.models import Sum
    from apps.branches.models import Branch
    from apps.catalog.models import ItemStock, exclude_unsellable
    from apps.config.item_types import planning_excluded_codes
    from .models import ItemDemandMetrics
    from .transfer_engine import MIN_TRANSFER_QTY, TransferEngine

    run = run if run is not None else latest_run()
    live = {b.id: b for b in Branch.objects.live()}
    retail = [b for b in live.values() if b.kind == Branch.KIND_RETAIL
              and (dest_codes is None or b.softech_branch_id in dest_codes)]
    retail.sort(key=lambda b: (b.display_order, b.softech_branch_id))
    dest_ids = {b.id for b in retail}
    out = {'run': run.pk if run else None, 'calc_date': run.calc_date.isoformat() if run and run.calc_date else None,
           'rows': [], 'branches': []}
    if run is None or not dest_ids:
        out['branches'] = [_branch_summary(b, []) for b in retail]
        return out

    fields = ('item_id', 'branch_id', 'gap', 'current_stock', 'in_transit_qty', 'safety_stock', 'monthly_avg',
              'pack_price', 'abc_class')
    excluded = planning_excluded_codes()
    cand = list(ItemDemandMetrics.objects.filter(run=run, branch_id__in=dest_ids, abc_class__in=list(classes),
                                                 monthly_avg__gt=0, item__is_stockable=True)
                .exclude(item__medicine_type__in=excluded).values(*fields))
    item_ids = {c['item_id'] for c in cand}
    if not item_ids:
        out['branches'] = [_branch_summary(b, []) for b in retail]
        return out

    stock = defaultdict(lambda: ZERO)          # (item_id, branch_id) → sellable on hand now
    for r in (exclude_unsellable(ItemStock.objects.filter(item_id__in=item_ids, branch_id__in=list(live)))
              .order_by().values('item_id', 'branch_id').annotate(q=Sum('quantity_on_hand'))):
        stock[(r['item_id'], r['branch_id'])] = _d(r['q'])

    # destinations at zero now, with their live need
    dests = {}
    for c in cand:
        live_qty = stock[(c['item_id'], c['branch_id'])]
        if live_qty > 0:
            continue
        target = _d(c['gap']) + _d(c['current_stock']) + _d(c['in_transit_qty'])
        need = target - max(live_qty, ZERO) - _d(c['in_transit_qty'])
        if need < Decimal(str(MIN_TRANSFER_QTY)):
            continue
        dests[(c['item_id'], c['branch_id'])] = (c, need, live_qty)
    if not dests:
        out['branches'] = [_branch_summary(b, []) for b in retail]
        return out

    dest_items = {k[0] for k in dests}
    by_item = defaultdict(list)
    for m in (ItemDemandMetrics.objects.filter(run=run, item_id__in=dest_items, branch_id__in=list(live))
              .values(*fields)):
        key = (m['item_id'], m['branch_id'])
        live_qty = stock[key]
        if key in dests:
            _, need, _ = dests[key]
            gap, prio = need, need
        else:
            gap, prio = ZERO, ZERO          # only today's zero-stock A/B destinations are deficits here
        by_item[m['item_id']].append(SimpleNamespace(
            item_id=m['item_id'], branch_id=m['branch_id'], gap=gap, priority=prio,
            current_stock=live_qty, safety_stock=_d(m['safety_stock']), monthly_avg=_d(m['monthly_avg']),
            pack_price=_d(m['pack_price']), abc_class=m['abc_class']))

    recs = TransferEngine(None)._match_all(by_item)          # the engine's own greedy pairing

    from apps.catalog.models import Item
    items = {i['id']: i for i in Item.objects.filter(id__in=dest_items).values('id', 'softech_id', 'name')}
    sources = defaultdict(list)
    for r in recs:
        sources[(r.item_id, r.to_branch_id)].append(r)
    rows = []
    for (item_id, bid), (c, need, live_qty) in dests.items():
        srcs = sources.get((item_id, bid), [])
        if not srcs:
            continue                         # zero here, but nobody holds a surplus → a buy, not this list
        qty = sum((_d(s.quantity) for s in srcs), ZERO)
        it = items.get(item_id, {})
        rows.append({
            'item_id': item_id, 'item_code': it.get('softech_id', ''), 'item_name': it.get('name', ''),
            'branch_code': live[bid].softech_branch_id, 'abc_class': c['abc_class'],
            'monthly_avg': float(_d(c['monthly_avg'])), 'stock_now': float(live_qty),
            'need': float(need.quantize(Decimal('0.01'))), 'transfer_qty': float(qty.quantize(Decimal('0.01'))),
            'short_after': float(max(need - qty, ZERO).quantize(Decimal('0.01'))),
            'value': float(sum((_d(s.estimated_value) for s in srcs), ZERO).quantize(Decimal('0.01'))),
            'sources': [{'branch_code': live[s.from_branch_id].softech_branch_id,
                         'qty': float(_d(s.quantity).quantize(Decimal('0.01'))),
                         'stock_now': float(_d(s.from_stock)), 'safety': float(_d(s.from_safety))}
                        for s in srcs],
        })
    rows.sort(key=lambda r: (r['branch_code'], r['abc_class'], -r['value'], r['item_code']))
    out['rows'] = rows
    out['branches'] = [_branch_summary(b, [r for r in rows if r['branch_code'] == b.softech_branch_id])
                       for b in retail]
    return out


def _branch_summary(b, rows) -> dict:
    return {'branch_code': b.softech_branch_id, 'items': len(rows),
            'a_items': sum(1 for r in rows if r['abc_class'] == 'A'),
            'value': round(sum(r['value'] for r in rows), 2)}


def workbook(report, label=lambda c: c):
    """The list as a streaming (write-only) workbook: summary + lines. The caller saves it through
    core.export_safety.neutralise_formulas."""
    from openpyxl import Workbook
    from core.export_safety import safe_sheet
    wb = Workbook(write_only=True)
    ws = safe_sheet(wb.create_sheet('ملخص الفروع'))
    ws.sheet_view.rightToLeft = True
    ws.append(['الفرع', 'أصناف ناقصة وموجودة بفرع آخر', 'منها فئة A', 'القيمة (سعر الجمهور)'])
    for b in report['branches']:
        ws.append([label(b['branch_code']), b['items'], b['a_items'], b['value']])
    ws2 = safe_sheet(wb.create_sheet('الأصناف'))
    ws2.sheet_view.rightToLeft = True
    ws2.append(['الفرع (ناقص)', 'كود الصنف', 'الصنف', 'الفئة', 'المعدل الشهري', 'الرصيد الآن', 'الاحتياج',
                'المقترح تحويله', 'يتبقى ناقص', 'القيمة', 'من (الفرع: الكمية — الرصيد / الأمان)'])
    for r in report['rows']:
        src = ' | '.join(f"{label(s['branch_code'])}: {s['qty']:g} — {s['stock_now']:g} / {s['safety']:g}"
                         for s in r['sources'])
        ws2.append([label(r['branch_code']), r['item_code'], r['item_name'], r['abc_class'], r['monthly_avg'],
                    r['stock_now'], r['need'], r['transfer_qty'], r['short_after'], r['value'], src])
    return wb
