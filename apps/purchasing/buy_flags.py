"""
apps/purchasing/buy_flags.py — two ADVISORY purchase-side flags on شيت النواقص (doc 22 §10,
"future patterns"; sized 2026-10-26 on 180 days / 38.8M EGP of purchases):

  💲 يوجد أرخص — an accredited supplier sold the item recently at a better real discount
     than what we paid. Not a new engine: the verdict is apps/supply/price_history.build()
     («مقارنة أسعار الشراء») — same yardstick, same 1-point margin, same stale rule.

  🎁 بونص زائد — a bonus (FOC) deal bought more than FOC_COVER_MONTHS of the network's
     sales: the free units tied up cash for longer than they are worth. Established items
     only — a launch with no sales history yet is not an over-buy.

Both are read-only annotations: they never change المطلوب, never order, never touch SOFTECH.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

WINDOW_DAYS = 180          # purchases looked at
FOC_COVER_MONTHS = 6       # paid + free units above this many months of sales = over-buy
FOC_MIN_BONUS = 0.05       # free units ≥ 5 % of the paid ones = a real bonus deal
ESTABLISHED_DAYS = 180     # the item sold for at least this long before the deal


def cheaper_supplier_flags(*, today=None, board=None) -> dict:
    """{item_id: row} for the items whose state is «يوجد أرخص» in «مقارنة أسعار الشراء»."""
    from apps.supply import price_history
    board = board or price_history.build(days=WINDOW_DAYS, today=today)
    return {r['item_id']: r for r in board['items'] if r['state'] == 'cheaper'}


def foc_overbuy_flags(*, today=None, rates=None) -> dict:
    """{item_id: deal} — the biggest bonus over-buy per item in the window.

    A deal = one item's paid + free units bought on one day (all branches, accredited
    suppliers — virtual / contract accounts are never a bonus to judge). Cover = units ÷
    the network monthly rate of the latest demand run; excess = the units beyond
    FOC_COVER_MONTHS of it, valued at the deal's real unit cost.
    """
    from django.utils import timezone
    from apps.procurement.models import PurchaseLine
    from apps.supply.comparison import _profiles
    from apps.supply.price_history import _company, _company_tier, _rates

    today = today or timezone.localdate()
    since = today - timedelta(days=WINDOW_DAYS)
    lines = list(PurchaseLine.objects.filter(doc_date__gte=since, is_return=False, net_qty__gt=0,
                                             bonus_qty__gt=0, item__isnull=False)
                 .values('item_id', 'item_code', 'supplier_code', 'doc_date', 'net_qty', 'bonus_qty',
                         'net_value', 'vat_value'))
    if not lines:
        return {}
    prof = _profiles({l['supplier_code'] for l in lines})
    deals = defaultdict(lambda: {'qty': 0.0, 'bonus': 0.0, 'paid': 0.0, 'suppliers': set()})
    codes = {}
    for l in lines:
        _key, name, accounts = _company(l['supplier_code'], prof)
        if _company_tier(accounts, prof) is None:
            continue
        d = deals[(l['item_id'], l['doc_date'])]
        d['qty'] += float(l['net_qty'])
        d['bonus'] += float(l['bonus_qty'])
        d['paid'] += float(l['net_value'] or 0) + float(l['vat_value'] or 0)
        d['suppliers'].add(name)
        codes[l['item_id']] = l['item_code']
    if not deals:
        return {}
    first_sale = _first_sales(set(codes.values()))
    rates = rates if rates is not None else _rates({iid for iid, _d in deals})

    out = {}
    for (iid, day), d in deals.items():
        if d['qty'] <= 0 or d['bonus'] / d['qty'] < FOC_MIN_BONUS:
            continue
        started = first_sale.get(codes[iid])
        if started is None or started > day - timedelta(days=ESTABLISHED_DAYS):
            continue                                      # a launch, not an over-buy
        units = d['qty'] + d['bonus']
        rate = float(rates.get(iid, 0) or 0)
        cover = units / rate if rate > 0 else None        # None = no sales now
        if cover is not None and cover <= FOC_COVER_MONTHS:
            continue
        unit_cost = d['paid'] / units
        excess = round((units - FOC_COVER_MONTHS * rate) * unit_cost, 2)
        deal = {'date': day.isoformat(), 'qty': round(d['qty'], 2), 'bonus_qty': round(d['bonus'], 2),
                'supplier': ' / '.join(sorted(d['suppliers'])), 'monthly_rate': round(rate, 2),
                'cover_months': round(cover, 1) if cover is not None else None,
                'excess_value': excess}
        if iid not in out or excess > out[iid]['excess_value']:
            out[iid] = deal
    return out


def _first_sales(item_codes) -> dict:
    """{item_code: earliest sale date} — the earlier of the demand engine's 365-day sales
    lines and, where the seasonality mirror exists, its 48 months of monthly sales."""
    from django.db.models import Min
    from apps.purchasing import models as pm
    out = dict(pm.SalesTransactionLine.objects.filter(softech_itemcode__in=item_codes, doccode='115')
               .values('softech_itemcode').annotate(m=Min('doc_date')).values_list('softech_itemcode', 'm'))
    monthly = getattr(pm, 'ItemMonthlySales', None)
    if monthly is not None:
        for code, m in (monthly.objects.filter(item_code__in=item_codes, qty__gt=0)
                        .values('item_code').annotate(m=Min('month')).values_list('item_code', 'm')):
            if code not in out or m < out[code]:
                out[code] = m
    return out


def cheaper_label(r) -> str:
    """One cell for the sheet: who is cheaper, by how much, and what a month of it saves."""
    best = r['best'] or {}
    return (f"يوجد أرخص: {best.get('name', '')} {best.get('discount_pct', 0):g}% "
            f"بدل {r['paid_pct'] if r['paid_pct'] is not None else r['last']['discount_pct']:g}% "
            f"— توفير {r['saving_month']:,.0f} ج.م/شهر")


def foc_label(d) -> str:
    cover = 'بدون مبيعات حالياً' if d['cover_months'] is None else f"تغطية {d['cover_months']:g} شهر"
    return (f"بونص زائد: {d['qty']:g}+{d['bonus_qty']:g} من {d['supplier']} {d['date']} — "
            f"{cover} (≈{d['excess_value']:,.0f} ج.م فوق {FOC_COVER_MONTHS} شهور)")
