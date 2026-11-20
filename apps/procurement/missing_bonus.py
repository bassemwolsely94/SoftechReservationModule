"""
apps/procurement/missing_bonus.py — C18 missing-bonus check at invoice receipt (READ-ONLY review list).

docs/full-project-audit/08_BUSINESS_OPTIMIZATION_OPPORTUNITIES.md §C18. The agreed bonus is not stored anywhere, so
the supplier's own recent history is the proxy (owner question in the PR): a paid doc-10 receipt is flagged when it
came with fewer free units than the same supplier's last REFS deliveries of the same item would give.

Free goods are the procurement engine's bonus_qty (SOFTECH books them as a separate stktrans line for the same item
with pharmacydiscp = 100; memory «Procurement Intelligence Overhaul»); raw_qty is the paid quantity.

Rule, per paid doc-10 line in the window (accredited suppliers only — same company grouping and tier filter as
«مقارنة الموردين» / buy_flags; virtual / contract accounts never count):
  • references = the REFS previous paid deliveries of the item from the same supplier company (any branch), in the
    HISTORY_DAYS before it. All REFS must exist and carry a real bonus (free ≥ FOC_MIN_BONUS of paid — buy_flags);
  • the deal must be stable: the highest reference ratio ≤ STABLE_SPREAD × the lowest. Otherwise the deal is
    changing and nothing is judged;
  • expected free = floor(paid × the LOWEST reference ratio) — conservative; only when the line's paid qty reaches the
    smallest paid qty that earned a bonus in the references (a «10+1» deal gives nothing on 5);
  • flagged when received free < expected free (at least one whole unit missing): «بونص ناقص» when some free units
    came, «بدون بونص» when none came;
  • deal changed: when the NEXT delivery of the same supplier + item also comes below the old ratio, the lower ratio is
    taken as a new deal and the row is marked deal_changed (hidden by default).
Missing value = missing free units × the line's paid unit cost (raw_value ÷ raw_qty, before VAT).

Nothing is written; no SOFTECH call. Deterministic Decimal arithmetic.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

LOOKBACK_DAYS = 30
MAX_LOOKBACK_DAYS = 120
HISTORY_DAYS = 365
REFS = 3
STABLE_SPREAD = Decimal('2')
ZERO = Decimal('0')
CENT = Decimal('0.01')


def _d(v) -> Decimal:
    return Decimal(str(v)) if v is not None else ZERO


def min_bonus() -> Decimal:
    from apps.purchasing.buy_flags import FOC_MIN_BONUS
    return Decimal(str(FOC_MIN_BONUS))


def _ratio(paid: Decimal, free: Decimal):
    return (free / paid) if paid > 0 else None


def judge(paid, free, refs, later=None) -> dict | None:
    """The rule for one line. refs = [(paid, free)] newest first (REFS of them); later = (paid, free) of the next
    delivery or None. Returns {'kind', 'expected', 'missing', 'deal_ratio', 'deal_changed'} or None (not flagged)."""
    paid, free = _d(paid), _d(free)
    if paid <= 0 or len(refs) < REFS:
        return None
    floor_ratio = min_bonus()
    ratios = []
    for rp, rf in refs[:REFS]:
        r = _ratio(_d(rp), _d(rf))
        if r is None or r < floor_ratio:
            return None                                   # a reference without a real bonus: no deal to expect
        ratios.append(r)
    lo, hi = min(ratios), max(ratios)
    if hi > lo * STABLE_SPREAD:
        return None                                       # the deal is changing — not judged
    if paid < min(_d(rp) for rp, _rf in refs[:REFS]):
        return None                                       # below the smallest order that earned a bonus
    expected = (paid * lo).to_integral_value(ROUND_FLOOR)
    if expected < 1 or free >= expected:
        return None
    changed = False
    if later is not None:
        lp, lf = _d(later[0]), _d(later[1])
        nr = _ratio(lp, lf)
        changed = nr is not None and nr < lo and (lp * lo).to_integral_value(ROUND_FLOOR) > lf
    return {'kind': 'short' if free > 0 else 'none', 'expected': expected, 'missing': expected - free,
            'deal_ratio': lo, 'deal_changed': changed}


def _delivery_order(line):
    return (line['doc_date'], line['branch_code'], line['doc_number'], line['id'])


def _accredited(codes):
    """{supplier_code: (company_key, company_name)} for the suppliers that count (buy_flags' filter)."""
    from apps.supply.comparison import _profiles
    from apps.supply.price_history import _company, _company_tier
    prof = _profiles(codes)
    out = {}
    for c in codes:
        key, name, accounts = _company(c, prof)
        if _company_tier(accounts, prof) is not None:
            out[c] = (key, name)
    return out


def build(days=LOOKBACK_DAYS, today=None, branch_codes=None, include_changed=False) -> dict:
    """{'rows', 'branches', 'days', 'refs', 'min_bonus_pct'}. branch_codes = receiving branches in view (None = all)."""
    from django.utils import timezone
    from apps.branches.models import Branch
    from apps.catalog.models import Item
    from .models import PurchaseLine

    today = today or timezone.localdate()
    days = max(1, min(int(days or LOOKBACK_DAYS), MAX_LOOKBACK_DAYS))
    since = today - dt.timedelta(days=days)
    live = [b for b in Branch.objects.live() if branch_codes is None or b.softech_branch_id in branch_codes]
    live.sort(key=lambda b: (b.display_order, b.softech_branch_id))
    out = {'rows': [], 'branches': [], 'days': days, 'refs': REFS,
           'min_bonus_pct': float(min_bonus() * 100)}

    paid = PurchaseLine.objects.filter(doccode='10', is_return=False, raw_qty__gt=0)
    fields = ('id', 'branch_code', 'supplier_code', 'doc_number', 'doc_date', 'item_code', 'raw_qty', 'raw_value',
              'bonus_qty')
    current = list(paid.filter(doc_date__gte=since, doc_date__lte=today,
                               branch_code__in=[b.softech_branch_id for b in live]).values(*fields))
    sup = _accredited({l['supplier_code'] for l in current})
    current = [l for l in current if l['supplier_code'] in sup]
    if current:
        history = list(paid.filter(doc_date__gte=since - dt.timedelta(days=HISTORY_DAYS),
                                   item_code__in={l['item_code'] for l in current})
                       .values(*fields))
        hsup = _accredited({l['supplier_code'] for l in history} - set(sup))
        hsup.update(sup)
        series = defaultdict(list)            # (company, item) → deliveries, oldest first (all branches)
        for l in history:
            if l['supplier_code'] in hsup:
                series[(hsup[l['supplier_code']][0], l['item_code'])].append(l)
        for s in series.values():
            s.sort(key=_delivery_order)
        items = dict(Item.objects.filter(softech_id__in={l['item_code'] for l in current})
                     .values_list('softech_id', 'name'))
        for l in current:
            s = series[(sup[l['supplier_code']][0], l['item_code'])]
            i = next(k for k, x in enumerate(s) if x['id'] == l['id'])
            refs = [(x['raw_qty'], x['bonus_qty']) for x in reversed(s[max(0, i - REFS):i])]
            later = (s[i + 1]['raw_qty'], s[i + 1]['bonus_qty']) if i + 1 < len(s) else None
            v = judge(l['raw_qty'], l['bonus_qty'], refs, later)
            if v is None or (v['deal_changed'] and not include_changed):
                continue
            unit = (_d(l['raw_value']) / _d(l['raw_qty'])) if _d(l['raw_qty']) > 0 else ZERO
            out['rows'].append({
                'id': l['id'], 'branch_code': l['branch_code'], 'supplier_code': l['supplier_code'],
                'supplier_name': sup[l['supplier_code']][1], 'doc_number': l['doc_number'],
                'doc_date': l['doc_date'].isoformat(), 'item_code': l['item_code'],
                'item_name': items.get(l['item_code'], ''),
                'paid_qty': float(_d(l['raw_qty'])), 'free_qty': float(_d(l['bonus_qty'])),
                'expected_free': float(v['expected']), 'missing_free': float(v['missing']),
                'deal_pct': float((v['deal_ratio'] * 100).quantize(CENT, ROUND_HALF_UP)),
                'unit_cost': float(unit.quantize(CENT, ROUND_HALF_UP)),
                'missing_value': float((v['missing'] * unit).quantize(CENT, ROUND_HALF_UP)),
                'kind': v['kind'], 'deal_changed': v['deal_changed'],
                'refs': [{'doc_date': x['doc_date'].isoformat(), 'doc_number': x['doc_number'],
                          'branch_code': x['branch_code'], 'paid': float(_d(x['raw_qty'])),
                          'free': float(_d(x['bonus_qty']))}
                         for x in reversed(s[max(0, i - REFS):i])],
            })
    out['rows'].sort(key=lambda r: (-r['missing_value'], r['doc_date'], r['item_code']))
    for b in live:
        mine = [r for r in out['rows'] if r['branch_code'] == b.softech_branch_id]
        out['branches'].append({'branch_code': b.softech_branch_id, 'lines': len(mine),
                                'value': round(sum(r['missing_value'] for r in mine), 2)})
    return out


KIND_AR = {'none': 'بدون بونص', 'short': 'بونص ناقص'}


def workbook(report, label=lambda c: c):
    from openpyxl import Workbook
    from core.export_safety import safe_sheet
    wb = Workbook()
    ws = safe_sheet(wb.active)
    ws.title = 'ملخص الفروع'
    ws.sheet_view.rightToLeft = True
    ws.append(['الفرع المستلم', 'سطور', 'قيمة البونص الناقص'])
    for b in report['branches']:
        ws.append([label(b['branch_code']), b['lines'], b['value']])
    ws2 = safe_sheet(wb.create_sheet('السطور'))
    ws2.sheet_view.rightToLeft = True
    ws2.append(['التاريخ', 'الفرع', 'المستند', 'المورد', 'كود الصنف', 'الصنف', 'المدفوع', 'البونص المستلم',
                'البونص المتوقع', 'الناقص', 'نسبة الصفقة %', 'تكلفة الوحدة', 'قيمة الناقص', 'النوع',
                'آخر 3 توريدات (التاريخ: مدفوع+بونص)'])
    for r in report['rows']:
        refs = ' | '.join(f"{x['doc_date']}: {x['paid']:g}+{x['free']:g}" for x in r['refs'])
        ws2.append([r['doc_date'], label(r['branch_code']), r['doc_number'], r['supplier_name'] or r['supplier_code'],
                    r['item_code'], r['item_name'], r['paid_qty'], r['free_qty'], r['expected_free'],
                    r['missing_free'], r['deal_pct'], r['unit_cost'], r['missing_value'],
                    KIND_AR.get(r['kind'], r['kind']) + (' — صفقة تغيّرت' if r['deal_changed'] else ''), refs])
    return wb
