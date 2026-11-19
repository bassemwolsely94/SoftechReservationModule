"""
apps/insights/today.py

Top-10 C02: the «اليوم» part of the branch morning brief — what to do today, with the money at stake,
built only from engines that already exist (nothing is computed or decided here):

  • return window closes this month  — apps/batches/return_calendar (C03): shelf lots to send to HQ by a date
  • move slow stock                  — apps/purchasing/dead_stock (P-27): the latest snapshot's «move» lines
                                       out of this branch, with their target branches
  • rescue near-expiry stock         — the stock-expiry mirror (StockExpiryBalance, PostgreSQL only): the
                                       most valuable shelf lots expiring within RESCUE_DAYS, not already
                                       listed under the return window

At most MAX_LINES per part, plus «+N أخرى». The same lines feed the WhatsApp brief (compose) and the
in-app /me widget «📋 مهام فرعي اليوم», so the list works while WhatsApp sending stays off.
Read-only: no SOFTECH read or write.
"""
import datetime as dt
from decimal import Decimal

MAX_LINES = 3
RESCUE_DAYS = 60
H_TODAY = 'اليوم'


def _money(v):
    return f'{Decimal(str(v or 0)):,.0f}'


def _qty(v):
    v = Decimal(str(v or 0))
    return f'{v:,.0f}' if v == v.to_integral_value() else f'{v:,.2f}'


def _branch_names():
    from apps.branches.models import Branch
    return {str(c): (a or n or str(c)) for c, a, n in Branch.objects.values_list('softech_branch_id', 'name_ar', 'name')}


def returns_due(branch_code, today):
    """Shelf lots whose supplier return window closes this month and are not done yet."""
    from apps.batches.return_calendar import calendar
    c = calendar(today=today, branch_codes=[branch_code], location='shelf', state='closes_this_month')
    rows = [l for l in c['lines'] if l['supplier_code'] and not (l['record'] and l['record']['status'] == 'done')]
    rows.sort(key=lambda l: (l['send_by'] or '', -l['value']))
    return [{'item_code': l['item_code'], 'item': l['item_name'] or l['item_code'], 'qty': l['qty'],
             'value': l['value'], 'send_by': l['send_by'], 'supplier': l['supplier_name'] or l['supplier_code'],
             'expiry': l['expiry_date'], 'late': bool(l['send_by'] and l['send_by'] < today.isoformat())}
            for l in rows]


def moves_out(branch_code):
    """The latest dead-stock snapshot's «move» lines out of this branch that have a target and are worth moving."""
    from apps.purchasing.dead_stock import latest_snapshot
    snap = latest_snapshot()
    if snap is None:
        return []
    names = _branch_names()
    out = []
    for l in (snap.lines.filter(branch_code=branch_code, lane='move').select_related('item')
              .order_by('-move_value', 'rank')):
        flags = l.flags or {}
        if not l.targets or flags.get('below_threshold') or flags.get('conflict'):
            continue
        out.append({'item_code': l.item.softech_id, 'item': l.item.name, 'value': float(l.move_value),
                    'targets': [{'branch': names.get(str(t['branch']), str(t['branch'])), 'qty': t['qty']}
                                for t in l.targets]})
    return out


def rescue(branch_code, today, skip_items=()):
    """Shelf lots expiring within RESCUE_DAYS (not yet expired), most valuable first."""
    from apps.batches.expiry_audit import _item_attr_map
    from apps.batches.models import StockExpiryBalance
    from apps.batches.store_roles import LIVE
    qs = list(StockExpiryBalance.objects.filter(
        branch_code=branch_code, store_role=LIVE, qty__gt=0,
        expiry_date__gte=today, expiry_date__lte=today + dt.timedelta(days=RESCUE_DAYS),
    ).exclude(item_code__in=list(skip_items)).values('item_code', 'item_name', 'expiry_date', 'qty'))
    costs = _item_attr_map(list({r['item_code'] for r in qs}))
    out = []
    for r in qs:
        info = costs.get(r['item_code'], {})
        value = round(float(r['qty']) * float(info.get('unit_cost') or 0), 2)
        out.append({'item_code': r['item_code'], 'item': r['item_name'] or info.get('name') or r['item_code'],
                    'qty': float(r['qty']), 'expiry': r['expiry_date'].isoformat(), 'value': value})
    out.sort(key=lambda x: (-x['value'], x['expiry'], x['item_code']))
    return out


def actions(branch, today):
    """{'returns': [...], 'moves': [...], 'rescue': [...]} for one live branch (empty lists otherwise)."""
    from apps.branches.models import Branch
    if not Branch.objects.live().filter(pk=branch.pk).exists():
        return {'returns': [], 'moves': [], 'rescue': []}            # closed / pending / call centre: nothing to do
    code = str(branch.softech_branch_id)
    ret = returns_due(code, today)
    return {'returns': ret, 'moves': moves_out(code),
            'rescue': rescue(code, today, skip_items={r['item_code'] for r in ret})}


def _part(title, rows, line_of):
    if not rows:
        return []
    total = sum(r['value'] for r in rows)
    lines = [f'{title} — {len(rows)} ({_money(total)} ج.م)'] + [f'• {line_of(r)}' for r in rows[:MAX_LINES]]
    if len(rows) > MAX_LINES:
        lines.append(f'  +{len(rows) - MAX_LINES} أخرى')
    return lines


def lines(acts):
    """The «اليوم» section as text lines (empty when there is nothing to do)."""
    body = []
    body += _part('📆 مرتجع للمورد — أرسل للرئيسي', acts['returns'],
                  lambda r: f"{r['item']} — كمية {_qty(r['qty'])} — "
                  + (f"متأخر (كان قبل {r['send_by']}) أرسل الآن" if r.get('late') else f"قبل {r['send_by']}")
                  + f" ({r['supplier']})")
    body += _part('🔁 راكد يُباع بفرع آخر — انقل', acts['moves'],
                  lambda r: f"{r['item']} → " + '، '.join(f"{t['branch']} {t['qty']}" for t in r['targets'])
                  + f" ({_money(r['value'])} ج.م)")
    body += _part(f'⏳ ينتهي خلال {RESCUE_DAYS} يوم — بِع أو انقل', acts['rescue'],
                  lambda r: f"{r['item']} — كمية {_qty(r['qty'])} — ينتهي {r['expiry']} ({_money(r['value'])} ج.م)")
    return [f'*{H_TODAY}*'] + body if body else []
