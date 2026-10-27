"""
apps/supply/price_history.py — «مقارنة أسعار الشراء»: compare the accredited suppliers on
what we REALLY paid them (saved purchase invoices, procurement.PurchaseLine) — not on the
incoming «الوارد» lists (that is «مقارنة الموردين», comparison.py). Owner 2026-10-24.

Same agreed rules as comparison.py (memory supplier_price_comparison):
  • who is compared: distributors (class 60) and manufacturers (70) head-to-head; medicine
    warehouses (50 / 20) are their own tier; virtual / contract / clearing / services / misc
    (80, 40, 96, 10) are never a price to beat;
  • one company = one column: «المصرية» شريف / زيتون / الحرية, أخناتون 124 / 3031 / 3030
    (SUPPLIER_GROUPS);
  • fair across public-price changes: every purchase is a DISCOUNT % off the public price in
    force on its invoice (after the free units — bonus lowers the cost), applied to today's
    public price; a purchase at another public price is marked «سعر قديم»;
  • another supplier is better only when more than BETTER_PCT (1 point) cheaper.

Per company and item we keep the LAST purchase (its current terms) and the best one in
the window. The yardstick is what we REALLY paid: the quantity-weighted discount of every
accredited purchase in the last STALE_DAYS (one emergency pack from a warehouse must not
make the saving look huge). «يوجد أرخص» = the best RECENT supplier beats that by more than
BETTER_PCT; saving / month = the difference × today's public price × the network's monthly
sales. Deterministic and read-only: it proposes, never orders.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from .comparison import (BETTER_PCT, SUPPLIER_GROUPS, TIER_LABELS, _f, _line_discount, _profiles, _tier)

DEFAULT_DAYS = 180
STALE_DAYS = 90                       # a last purchase older than this is an old price
HEAD_TIERS = ('distributor', 'manufacturer', 'other')
STATE_LABELS = {'cheaper': 'يوجد أرخص', 'best': 'نشتري من الأفضل', 'single': 'مورد واحد',
                'warehouse_only': 'مخازن فقط'}


def _company(code, prof):
    """(key, name, accounts) — accounts of one company share one column."""
    group = next((g for g in SUPPLIER_GROUPS if code in g), None)
    if group is None:
        return code, (prof.get(code, {}).get('name') or code), [code]
    accounts = sorted(group)
    names = [prof.get(c, {}).get('name') for c in accounts if prof.get(c, {}).get('name')]
    return 'g:' + '-'.join(accounts), (names[0] if names else accounts[0]), accounts


def _company_tier(accounts, prof):
    tiers = [_tier(prof.get(c, {}).get('classif', ''), False) for c in accounts]
    for t in ('distributor', 'manufacturer', 'warehouse', 'other'):
        if t in tiers:
            return t
    return None


def _rates(item_ids) -> dict:
    """{item_id: network sales rate / month} from the latest demand run."""
    from apps.purchasing.models import ItemDemandMetrics
    from .position import latest_demand_run
    run = latest_demand_run()
    out = defaultdict(float)
    if run is None:
        return out
    for m in ItemDemandMetrics.objects.filter(run=run, item_id__in=list(item_ids)).values('item_id', 'monthly_avg'):
        out[m['item_id']] += max(0.0, float(m['monthly_avg'] or 0))
    return out


def build(*, days=DEFAULT_DAYS, include_single=False, today=None) -> dict:
    from django.utils import timezone
    from apps.catalog.models import Item
    from apps.procurement.models import PurchaseLine
    today = today or timezone.localdate()
    since = today - timedelta(days=days)
    lines = list(PurchaseLine.objects.filter(doc_date__gte=since, is_return=False, net_qty__gt=0,
                                             public_price__gt=0, item__isnull=False)
                 .order_by('doc_date', 'id')
                 .values('id', 'item_id', 'item_code', 'supplier_code', 'doc_date', 'net_qty', 'bonus_qty',
                         'net_value', 'vat_value', 'public_price'))
    prof = _profiles({l['supplier_code'] for l in lines})
    comp_of = {}
    for code in {l['supplier_code'] for l in lines}:
        key, name, accounts = _company(code, prof)
        comp_of[code] = (key, name, accounts, _company_tier(accounts, prof))

    per = defaultdict(dict)                              # item_id → company key → record
    paid = defaultdict(lambda: [0.0, 0.0])               # item_id → [Σ discount × units, Σ units] (recent)
    recent_from = (today - timedelta(days=STALE_DAYS)).isoformat()
    for l in lines:
        key, name, accounts, tier = comp_of[l['supplier_code']]
        if tier is None:
            continue                                     # never a price to beat
        d, cost = _line_discount(l)
        if d is None or not (-0.5 < d < 0.9):            # junk / mis-keyed lines
            continue
        buy = {'date': l['doc_date'].isoformat(), 'discount_pct': round(d * 100, 2),
               'unit_cost': round(cost, 2), 'public_price': _f(l['public_price']),
               'qty': _f(l['net_qty']), 'bonus_qty': _f(l['bonus_qty']) or 0, 'account': l['supplier_code']}
        r = per[l['item_id']].setdefault(key, {'key': key, 'name': name, 'tier': tier, 'accounts': accounts,
                                               'buys': 0, 'qty': 0.0, 'value': 0.0})
        r['last'] = buy                                  # ordered by date → the latest wins
        if buy['date'] >= recent_from:
            units = buy['qty'] + buy['bonus_qty']
            paid[l['item_id']][0] += buy['discount_pct'] * units
            paid[l['item_id']][1] += units
        if 'best' not in r or buy['discount_pct'] > r['best']['discount_pct']:
            r['best'] = buy
        r['buys'] += 1
        r['qty'] += buy['qty']
        r['value'] += _f(l['net_value']) or 0

    items = {i.id: i for i in Item.objects.filter(pk__in=list(per)).only(
        'id', 'softech_id', 'name', 'pack_price', 'producer_name', 'supplier_code')}
    rates = _rates(per)
    stale_before = (today - timedelta(days=STALE_DAYS)).isoformat()
    rows, sup = [], defaultdict(lambda: {'items': 0, 'best_in': 0, 'cheaper_than_last': 0, 'value': 0.0,
                                         'disc_sum': 0.0, 'disc_n': 0})
    for iid, comps in per.items():
        it = items.get(iid)
        if it is None:
            continue
        P = _f(it.pack_price) or 0
        cs = sorted(comps.values(), key=lambda c: (-c['last']['discount_pct'], c['last']['date']))
        for c in cs:
            c['qty'], c['value'] = round(c['qty'], 2), round(c['value'], 2)
            c['tier_label'] = TIER_LABELS.get(c['tier'], c['tier'])
            c['old_price'] = bool(P and abs(c['last']['public_price'] - P) > 0.005)
            c['stale'] = c['last']['date'] < stale_before
            c['cost_now'] = round(P * (1 - c['last']['discount_pct'] / 100), 2) if P else None
        head = [c for c in cs if c['tier'] in HEAD_TIERS]
        wh = [c for c in cs if c['tier'] == 'warehouse']
        if len(head) < 2 and not include_single:
            continue
        last = max(cs, key=lambda c: c['last']['date'])            # whom we bought from last
        # the best = the highest RECENT discount: a price older than STALE_DAYS can't drive
        # «يوجد أرخص» or a saving — it is shown apart as «كان أرخص» (old_best)
        fresh = [c for c in head if not c['stale']]
        best = (fresh or head or [None])[0]
        old_best = head[0] if head and best is not None and head[0]['key'] != best['key'] \
            and head[0]['last']['discount_pct'] > best['last']['discount_pct'] + BETTER_PCT else None
        best_wh = wh[0] if wh else None
        pw = paid.get(iid)
        paid_pct = round(pw[0] / pw[1], 2) if pw and pw[1] > 0 else None
        base = paid_pct if paid_pct is not None else last['last']['discount_pct']
        gap = round(best['last']['discount_pct'] - base, 2) if best else None
        if not head:
            state = 'warehouse_only'
        elif len(head) < 2:
            state = 'single'
        elif gap > BETTER_PCT and not best['stale']:
            state = 'cheaper'
        else:
            state = 'best'
        rate = round(rates.get(iid, 0.0), 2)
        main_key = comp_of.get((it.supplier_code or '').strip(), (None,))[0] if it.supplier_code else None
        row = {
            'item_id': iid, 'code': it.softech_id, 'name': it.name, 'producer': it.producer_name or '',
            'public_price': P, 'monthly_rate': rate, 'n_suppliers': len(head), 'n_warehouses': len(wh),
            'state': state, 'state_label': STATE_LABELS[state],
            'last': {'key': last['key'], 'name': last['name'], **last['last'], 'stale': last['stale'],
                     'old_price': last['old_price']},
            'best': ({'key': best['key'], 'name': best['name'], **best['last'], 'stale': best['stale'],
                      'old_price': best['old_price']} if best else None),
            'best_warehouse': ({'key': best_wh['key'], 'name': best_wh['name'], **best_wh['last']}
                               if best_wh else None),
            'old_best': ({'key': old_best['key'], 'name': old_best['name'], **old_best['last']}
                         if old_best else None),
            'paid_pct': paid_pct,                            # what we really paid (recent, weighted)
            'gap_pct': gap if state == 'cheaper' else 0.0,
            # what buying a month's sales from the best instead of the last supplier saves
            'saving_month': round(gap / 100 * P * rate, 2) if state == 'cheaper' and P and rate else 0.0,
            'main_supplier': main_key,
            # compact per-company cells (the screen's expand row); full lines = item_history
            'suppliers': [{'key': c['key'], 'name': c['name'], 'tier_label': c['tier_label'],
                           'date': c['last']['date'], 'discount_pct': c['last']['discount_pct'],
                           'qty': c['last']['qty'], 'bonus_qty': c['last']['bonus_qty'],
                           'best_pct': c['best']['discount_pct'], 'buys': c['buys'], 'total_qty': c['qty'],
                           'cost_now': c['cost_now'], 'old_price': c['old_price'], 'stale': c['stale']}
                          for c in cs],
        }
        rows.append(row)
        for c in cs:
            s = sup[c['key']]
            s.update(key=c['key'], name=c['name'], tier=c['tier'], tier_label=c['tier_label'])
            s['items'] += 1
            s['value'] += c['value']
            s['disc_sum'] += c['last']['discount_pct']
            s['disc_n'] += 1
        if best and len(head) >= 2:
            sup[best['key']]['best_in'] += 1
            if state == 'cheaper':
                sup[best['key']]['cheaper_than_last'] += 1
    rows.sort(key=lambda r: (-r['saving_month'], -r['gap_pct'], r['name']))
    suppliers = []
    for s in sup.values():
        s['avg_discount_pct'] = round(s.pop('disc_sum') / s['disc_n'], 2) if s['disc_n'] else None
        s.pop('disc_n')
        s['value'] = round(s['value'], 2)
        suppliers.append(s)
    suppliers.sort(key=lambda s: (-s['best_in'], -s['value']))
    totals = {'items': len(rows), 'cheaper': sum(r['state'] == 'cheaper' for r in rows),
              'best': sum(r['state'] == 'best' for r in rows),
              'saving_month': round(sum(r['saving_month'] for r in rows), 2),
              'lines': len(lines)}
    return {'days': days, 'since': since.isoformat(), 'today': today.isoformat(), 'better_pct': BETTER_PCT,
            'stale_days': STALE_DAYS, 'include_single': include_single, 'items': rows,
            'suppliers': suppliers, 'totals': totals, 'state_labels': STATE_LABELS}


def item_history(item_code, *, days=365, today=None) -> dict:
    """Every saved purchase of one item (accredited suppliers), newest first."""
    from django.utils import timezone
    from apps.catalog.models import Item
    from apps.procurement.models import PurchaseLine
    today = today or timezone.localdate()
    it = Item.objects.filter(softech_id=str(item_code)).only('softech_id', 'name', 'pack_price').first()
    if it is None:
        return None
    qs = (PurchaseLine.objects.filter(item_code=it.softech_id, doc_date__gte=today - timedelta(days=days),
                                      is_return=False, net_qty__gt=0, public_price__gt=0)
          .order_by('-doc_date', '-id')
          .values('supplier_code', 'branch_code', 'doc_number', 'doc_date', 'net_qty', 'bonus_qty',
                  'net_value', 'vat_value', 'public_price'))
    lines = list(qs)
    prof = _profiles({l['supplier_code'] for l in lines})
    P = _f(it.pack_price) or 0
    out = []
    for l in lines:
        key, name, accounts = _company(l['supplier_code'], prof)
        tier = _company_tier(accounts, prof)
        d, cost = _line_discount(l)
        if tier is None or d is None:
            continue
        out.append({'date': l['doc_date'].isoformat(), 'company': name, 'account': l['supplier_code'],
                    'tier_label': TIER_LABELS.get(tier, tier), 'branch': l['branch_code'],
                    'doc_number': l['doc_number'], 'qty': _f(l['net_qty']), 'bonus_qty': _f(l['bonus_qty']) or 0,
                    'unit_cost': round(cost, 2), 'discount_pct': round(d * 100, 2),
                    'public_price': _f(l['public_price']),
                    'old_price': bool(P and abs(_f(l['public_price']) - P) > 0.005)})
    return {'code': it.softech_id, 'name': it.name, 'public_price': P, 'days': days, 'lines': out}


def filter_board(board, *, state='', supplier='', producer='', q='') -> dict:
    """The board as the screen shows it after its filters (state chip, supplier, producer,
    search) — so the Excel export holds exactly the rows on screen (owner 2026-10-25)."""
    from apps.catalog.wildcard import text_matches
    items = [r for r in board['items']
             if (not state or r['state'] == state)
             and (not supplier or any(c['key'] == supplier for c in r['suppliers']))
             and (not producer or r['producer'] == producer)
             and (not q or text_matches(f"{r['code']} {r['name']}", q))]
    sups = [x for x in board['suppliers'] if not supplier or x['key'] == supplier]
    labels = {'state': board['state_labels'].get(state, state), 'supplier': next(
        (x['name'] for x in board['suppliers'] if x['key'] == supplier), supplier), 'producer': producer, 'q': q}
    return {**board, 'items': items, 'suppliers': sups,
            'filters': {k: v for k, v in labels.items() if v}}


def to_excel(board) -> bytes:
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter as L
    wb = Workbook()
    head_font, head_fill = Font(name='Arial', bold=True, color='FFFFFF'), PatternFill('solid', fgColor='022871')
    body = Font(name='Arial', size=10)

    def sheet(ws, title, heads, rows, widths):
        ws.title = title
        ws.sheet_view.rightToLeft = True
        ws.append(heads)
        for c in ws[1]:
            c.font, c.fill = head_font, head_fill
            c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        for r in rows:
            ws.append(r)
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.font = body
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[L(i)].width = w
        ws.freeze_panes = 'C2'
        ws.auto_filter.ref = ws.dimensions

    def buy(b):
        return (b or {}).get('name', ''), (b or {}).get('discount_pct'), (b or {}).get('date', '')

    from apps.catalog import item_columns as IC
    items = IC.load_items(codes=[r['code'] for r in board['items']])
    rows = []
    for r in board['items']:
        ln, ld, ldt = buy(r['last'])
        bn, bd, bdt = buy(r['best'])
        wn, wd, _ = buy(r['best_warehouse'])
        rows.append([r['code'], r['name'], *IC.item_cells(items.get(r['code'])), r['monthly_rate'], r['n_suppliers'],
                     r['state_label'], r['paid_pct'], ln, ld, ldt, bn, bd, bdt, r['gap_pct'], r['saving_month'], wn, wd,
                     ' · '.join(f"{c['name']} {c['discount_pct']}% ({c['date']})" for c in r['suppliers'])])
    sheet(wb.active, 'الأصناف',
          ['الكود', 'الصنف', *IC.ITEM_HEADS, 'معدل البيع/شهر', 'عدد الموردين', 'الحالة',
           'متوسط خصمنا الفعلي %', 'آخر شراء من', 'خصمه %', 'تاريخه', 'الأفضل', 'خصمه %', 'تاريخه', 'الفرق (نقطة %)',
           'التوفير/شهر',
           'أفضل مخزن', 'خصمه %', 'كل الموردين (آخر خصم)'],
          rows, [9, 34, *IC.ITEM_WIDTHS, 10, 9, 14, 10, 22, 8, 11, 22, 8, 11, 9, 11, 18, 8, 80])
    IC.style_columns(wb.active, 3)
    sheet(wb.create_sheet(), 'الموردين',
          ['المورد', 'الفئة', 'أصناف اشترينا منه', 'الأفضل في', 'أرخص من آخر شراء في', 'متوسط آخر خصم %',
           'قيمة المشتريات'],
          [[s['name'], s['tier_label'], s['items'], s['best_in'], s['cheaper_than_last'], s['avg_discount_pct'],
            s['value']] for s in board['suppliers']], [30, 12, 12, 10, 14, 12, 14])
    notes = wb.create_sheet('الشرح')
    notes.sheet_view.rightToLeft = True
    notes.column_dimensions['A'].width = 120
    for i, t in enumerate([
        f'مقارنة أسعار الشراء — من فواتير الشراء المحفوظة آخر {board["days"]} يوماً (من {board["since"]} إلى {board["today"]}).',
        ('• الفلاتر المطبَّقة: ' + ' · '.join(f'{ {"state": "الحالة", "supplier": "المورد", "producer": "الشركة المنتجة", "q": "بحث"}[k]}: {v}'
                                             for k, v in board['filters'].items())
         + f' — {len(board["items"])} صنف') if board.get('filters') else f'• بدون فلاتر — {len(board["items"])} صنف.',
        '• الخصم % = 1 − (قيمة الفاتورة + الضريبة) ÷ (الكمية + البونص) ÷ سعر الجمهور وقت الشراء — البونص يقلل التكلفة.',
        '• يُقارَن الموزعون والشركات المنتجة معاً، والمخازن في عمود مستقل؛ الحسابات الافتراضية والتعاقدات والمقاصات والخدمات لا تُقارَن.',
        '• حسابات الشركة الواحدة عمود واحد: المصرية (شريف / زيتون / الحرية)، أخناتون (124 / 3031 / 3030).',
        f'• متوسط خصمنا الفعلي = متوسط خصم كل مشترياتنا من الموردين المعتمدين آخر {board["stale_days"]} يوماً، مرجَّحاً بالكمية.',
        f'• «يوجد أرخص» = آخر خصم لدى أفضل مورد (شراء خلال آخر {board["stale_days"]} يوماً) أعلى من متوسط خصمنا الفعلي بأكثر من {board["better_pct"]:g} نقطة. التوفير/شهر = الفرق × سعر الجمهور الحالي × معدل البيع الشهري للشبكة.',
        f'• آخر شراء أقدم من {board["stale_days"]} يوماً = سعر قديم؛ والشراء بسعر جمهور مختلف عن الحالي معلَّم «سعر قديم».',
        IC.ITEM_NOTE,
        '• للقراءة فقط — لا يكتب شيئاً في SOFTECH.',
    ], start=1):
        notes.cell(i, 1, t).font = Font(name='Arial', size=11 if i > 1 else 13, bold=(i == 1))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
