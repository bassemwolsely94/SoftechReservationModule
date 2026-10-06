"""
apps/purchasing/isr_fulfillment.py — تلبية طلبات توريد الفروع (ISR fulfilment plan). READ-ONLY.

For one or more SOFTECH ISRs (طلبات توريد) raised by branches, works out — per requested
item — the requesting branch, every other branch and HQ: live stock (SOFTECH stkbal), sales
rate and engine need (latest demand-engine run), the max-stock ceiling (rate × coverage
months, never below 1 pack; 0 when the branch doesn't sell it) and the excess above it;
network totals; and a fulfilment plan:
    1. other branches give from their EXCESS only (whole packs, the donor always keeps its
       ceiling), the donor with the most excess on the ISR first;
    2. then HQ's real-balance stores (100 الرئيسي + 104 اكسسوارات — never 102 Washout /
       105 expired);
    3. the rest is shortage to purchase.

Three steps, so the /supply screen can re-plan at a new coverage without re-reading SOFTECH:
    collect(isrs)              → snapshot (JSON-safe; SOFTECH + engine read once)
    compute(snapshot, months)  → the plan, deterministic, for the screen
    build_workbook(snapshot, months) → openpyxl Workbook; every derived cell is an Excel
                                 formula driven by the coverage cell on «ملخص», so the
                                 sheet re-plans itself when the coverage is edited.
compute() and the workbook formulas implement the same rules; tests keep them in step.
Never writes to SOFTECH.
"""
import datetime
import logging
import math
import re
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from apps.finance.recon_labels import branch_label as BL      # '170' → '170 · م. الجيش-العباسية'

logger = logging.getLogger(__name__)

HQ = '100'
NAVY = '022871'
FONT = 'Arial'
MAX_ISRS = 20
COV_REF = "'ملخص'!$C$4"          # donor coverage cell (what each branch keeps) — ceiling formulas
FILL_REF = "'ملخص'!$C$5"         # fill coverage cell (how far the requester is filled)
BASIS_REF = "'ملخص'!$C$6"        # plan basis cell: which quantity the plan ships

# Which quantity the plan ships (owner 2026-10-05): the requested qty, the recommended qty
# (requester topped up to `fill` months of its own sales), or the smaller of the two.
BASIS = {'min': 'الأقل من الاثنين', 'recommended': 'الموصى بها', 'requested': 'المطلوبة'}
# The screen / API default is 'min' (plan_settings). The functions themselves default to
# 'requested' so any caller that passes no settings keeps the original behaviour.
DEFAULT_COVERAGE = 1.5          # requesting branch (fill coverage)
DEFAULT_DONOR_COVERAGE = 1.0    # donors keep one month before giving surplus (owner 2026-10-05)
# Name of the quantity actually supplied — it follows the basis (owner 2026-10-05).
PLAN_LABELS = {'min': 'الكمية الأقل من بين المطلوب و المحسوب',
               'recommended': 'الكمية الموصى بها', 'requested': 'الكمية المطلوبة'}


def plan_label_formula():
    """Excel header that follows the basis cell C6, so the name is right whatever is chosen."""
    return (f'=IF({BASIS_REF}="{BASIS["requested"]}","{PLAN_LABELS["requested"]}",'
            f'IF({BASIS_REF}="{BASIS["recommended"]}","{PLAN_LABELS["recommended"]}",'
            f'"{PLAN_LABELS["min"]}"))')


class IsrNotFound(ValueError):
    def __init__(self, missing):
        self.missing = list(missing)
        super().__init__('طلب التوريد غير موجود في SOFTECH: ' + '، '.join(self.missing))


def parse_isr_numbers(raw):
    """'261609, 2615043' / ['261609', 2615043] → ['261609', '2615043'] (unique, in order).
    Raises ValueError on anything that isn't a plain ISR number."""
    if isinstance(raw, (list, tuple)):
        parts = [str(x) for x in raw]
    else:
        parts = re.split(r'[\s,،;]+', str(raw or ''))
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if not p.isdigit() or len(p) > 10:
            raise ValueError(f'رقم طلب غير صالح: {p}')
        if p not in out:
            out.append(p)
    if not out:
        raise ValueError('أدخل رقم طلب توريد واحد على الأقل.')
    if len(out) > MAX_ISRS:
        raise ValueError(f'الحد الأقصى {MAX_ISRS} طلب في المرة الواحدة.')
    return out


def ceiling(rate, months):
    """Same as the workbook formula IF(rate>0, MAX(ROUND(rate×months,1),1), 0)."""
    if not rate or rate <= 0 or not months or months <= 0:
        return 0.0
    v = float((Decimal(str(rate)) * Decimal(str(months))).quantize(Decimal('0.1'), ROUND_HALF_UP))
    return max(v, 1.0)


def plan_settings(data) -> dict:
    """{months, fill, basis} from a request body — the three deterministic plan factors:
      coverage       months each DONOR branch keeps (its ceiling); default 1 month
      fill_coverage  months the REQUESTING branch is filled up to (recommended qty); default 1.5
      basis          min | recommended | requested — which quantity the plan ships; default min
    ValueError (Arabic) on anything out of range."""
    def months_of(key, label, default):
        try:
            v = float(data.get(key) or default)
        except (TypeError, ValueError):
            raise ValueError(f'{label} غير صالحة.')
        if not 0.25 <= v <= 12:
            raise ValueError(f'{label} بين 0.25 و 12 شهر.')
        return v
    basis = str(data.get('basis') or 'min')
    if basis not in BASIS:
        raise ValueError('اختيار الكمية التي تُوزَّع غير صالح.')
    return {'months': months_of('coverage', 'شهور تغطية الفروع المانحة', DEFAULT_DONOR_COVERAGE),
            'fill': months_of('fill_coverage', 'شهور تغطية الفرع الطالب', DEFAULT_COVERAGE), 'basis': basis}


def coverage_need(rate, have, months):
    """«الاحتياج» (owner 2026-10-05):
        raw  = months × monthly sales − current stock − in transit
        need = raw ROUNDED UP to whole packs when raw is POSITIVE (so any positive need is at
               least one pack — slow movers included), otherwise 0.
    `have` = stock + in transit. Exact decimal arithmetic. Same as the workbook formula
    MAX(0, ROUNDUP(months × rate − stock − in transit, 0))."""
    raw = Decimal(str(months)) * Decimal(str(rate or 0)) - Decimal(str(have or 0))
    if raw <= 0:
        return 0.0
    return float(raw.to_integral_value(rounding=ROUND_CEILING))


def recommended_qty(rate, have, requested, fill):
    """The requester's recommended qty = its «الاحتياج» at the fill coverage (coverage_need).
    An item the branch doesn't sell can't be judged by coverage → the requested qty
    (owner rule). Workbook: IF(rate<=0, requested, «الاحتياج»)."""
    if not rate or rate <= 0:
        return requested
    return coverage_need(rate, have, fill)


def plan_qty(requested, recommended, basis):
    if basis == 'requested':
        return requested
    if basis == 'recommended':
        return recommended
    return min(requested, recommended)


def _excess(stock, cap):
    """Whole packs above the ceiling — ROUNDDOWN(stock − cap, 0), never negative."""
    v = (stock or 0.0) - cap
    return max(0, int(v)) if v > 0 else 0


def user_names(codes):
    """{SOFTECH usercode: userid} from the synced SOFTECH users (ERPUser.username = the
    code, ERPUser.user_id = SOFTECH's userid, e.g. '1776' → 'Carol adel')."""
    from apps.users.models import ERPUser
    codes = {str(c or '').strip() for c in codes} - {''}
    return {u: (uid or fn or '').strip() for u, uid, fn in
            ERPUser.objects.filter(username__in=codes).values_list('username', 'user_id', 'full_name')}


def user_label(code, names):
    """'1776 · Carol adel' — code always shown, name when known."""
    code = str(code or '').strip()
    name = names.get(code, '')
    return f'{code} · {name}' if name else code


# ── 1. collect (reads SOFTECH + engine) ─────────────────────────────────────────
def _read_isrs(numbers):
    from config.sybase import get_sybase_connection
    c = get_sybase_connection()
    cur = c.cursor()
    out, missing = [], []
    try:
        for isr in numbers:
            cur.execute('SELECT branchcode, forbranchcode, docdate, israpp, docvalue, usercode '
                        'FROM stockisrm WHERE isrdocnumber = ?', [int(isr)])
            h = cur.fetchone()
            if h is None:
                missing.append(isr)
                continue
            cur.execute('SELECT isrdblitemflag, itemcode, itemqty, nowqty, itemcostprice, itemsaleprice '
                        'FROM stockisr WHERE isrdocnumber = ? ORDER BY isrdblitemflag', [int(isr)])
            lines = [{'code': str(r[1]).strip(), 'qty': float(r[2] or 0),
                      'nowqty_at_request': float(r[3] or 0),
                      'cost': float(r[4] or 0), 'price': float(r[5] or 0)} for r in cur.fetchall()]
            d = h[2]
            out.append({'isr': str(isr), 'branch': str(h[0]).strip(), 'for_branch': str(h[1]).strip(),
                        'date': d.strftime('%Y-%m-%d') if hasattr(d, 'strftime') else str(d or '')[:10],
                        'approved': int(h[3] or 0), 'value': float(h[4] or 0),
                        'user': str(h[5] or '').strip(), 'lines': lines})
    finally:
        cur.close()
        c.close()
    if missing:
        raise IsrNotFound(missing)
    return out


def _hq_copy_stock(branches, codes):
    """Fallback for unreachable branch servers: the CURRENT copy of the branch's stkbal on
    server 100 — i.e. everything SOFTECH's sync has delivered so far.
    "As of" = the newest transaction of that branch that has reached server 100
    (stktransm.trans_time, last 2 days). Checked 2026-10-04: for every reachable branch
    the newest transaction AND the 2-day document count on server 100 were identical to
    the branch's own server, so this is the true last-synced moment. (stkbal.trans_time
    is NOT — it is a row stamp, e.g. 170's rows said 08:19 yesterday while its sales had
    synced up to 00:38 today.) Returns ({branch: {itemcode: nowqty}}, {branch: 'YYYY-MM-DD HH:MM'})."""
    from config.sybase import get_sybase_connection
    from apps.purchasing.rate_writer import resolve_store
    out, as_of = {}, {}
    if not branches:
        return out, as_of
    conn = get_sybase_connection()
    cur = conn.cursor()
    try:
        for b in branches:
            bc, got = b.softech_branch_id, {}
            for i in range(0, len(codes), 400):
                chunk = codes[i:i + 400]
                ph = ','.join('?' for _ in chunk)
                cur.execute(f'SELECT itemcode, nowqty FROM stkbal WHERE branchcode=? AND storecode=? '
                            f'AND itemcode IN ({ph})', [bc, resolve_store(b), *chunk])
                got.update({str(r[0]).strip(): float(r[1] or 0) for r in cur.fetchall()})
            cur.execute('SELECT max(trans_time) FROM stktransm WHERE branchcode = ? AND docdate >= '
                        'dateadd(day, -2, convert(datetime, convert(char(8), getdate(), 112)))', [bc])
            row = cur.fetchone()
            last = row[0] if row else None
            out[bc] = got
            as_of[bc] = last.strftime('%Y-%m-%d %H:%M') if hasattr(last, 'strftime') else ''
    finally:
        cur.close()
        conn.close()
    return out, as_of


def _live_stock(branches, codes):
    """{branch: {itemcode: nowqty}} from each branch's own server; HQ = every real-balance
    store on server 100. An unreachable branch falls back to server 100's copy of its
    stock (listed in `fallback` with the copy's time); only if that also fails is it
    absent + listed in `down`. Messages are Arabic — they are shown to the user."""
    from config.sybase import get_sybase_connection
    from apps.purchasing.rate_writer import _read_conn_for_target, resolve_store
    out, down, unreachable = {}, [], []
    for bc, b in [(b.softech_branch_id, b) for b in branches] + [(HQ, None)]:
        try:
            conn = get_sybase_connection() if b is None else _read_conn_for_target(b, 'node')
            cur = conn.cursor()
            got = {}
            for i in range(0, len(codes), 400):
                chunk = codes[i:i + 400]
                ph = ','.join('?' for _ in chunk)
                if b is None:
                    cur.execute(f'SELECT s.itemcode, sum(s.nowqty) FROM stkbal s, stores st '
                                f'WHERE s.storecode=st.storecode AND st.storerealbal=1 '
                                f'AND s.branchcode=? AND s.itemcode IN ({ph}) GROUP BY s.itemcode',
                                [HQ, *chunk])
                else:
                    cur.execute(f'SELECT itemcode, nowqty FROM stkbal WHERE branchcode=? AND storecode=? '
                                f'AND itemcode IN ({ph})', [bc, resolve_store(b), *chunk])
                got.update({str(r[0]).strip(): float(r[1] or 0) for r in cur.fetchall()})
            cur.close()
            conn.close()
            out[bc] = got
        except Exception as exc:          # one branch down must not sink the report
            logger.warning('isr fulfilment: stock read failed for %s: %s', bc, exc)
            if b is None:
                down.append('تعذّر قراءة رصيد الرئيسي (سيرفر 100) — كمية «من الرئيسي» غير محسوبة.')
            else:
                unreachable.append(b)
    fallback = {}
    if unreachable:
        try:
            copy, as_of = _hq_copy_stock(unreachable, codes)
            out.update(copy)
            fallback = as_of
        except Exception as exc:
            logger.warning('isr fulfilment: HQ-copy fallback failed: %s', exc)
            down += [f'سيرفر فرع {BL(b.softech_branch_id)} غير متاح ونسخة الرئيسي تعذّرت — أرصدته غير محسوبة.'
                     for b in unreachable]
    return out, down, fallback


def fallback_notes(fallback):
    """Arabic notice per branch whose stock came from server 100's copy."""
    return [f'⚠ تنبيه: سيرفر فرع {BL(bc)} غير متاح الآن — تم استخدام آخر نسخة متزامنة من أرصدة الفرع '
            f'على سيرفر الرئيسي 100 (آخر حركة من الفرع وصلت للرئيسي: {t or "غير معروفة"}). '
            f'أي حركة بعد هذا الوقت غير محسوبة، وقد يختلف رصيد بعض الأصناف عن الفرع.'
            for bc, t in sorted(fallback.items())]


def _engine(codes):
    """(run, {'code|branch': [rate, gap]}) from the latest successful engine run."""
    from apps.purchasing.models import ItemDemandMetrics
    from apps.purchasing.rate_writer import _latest_run
    run = _latest_run()
    data = {}
    for m in (ItemDemandMetrics.objects.filter(run=run, item__softech_id__in=codes)
              .select_related('item', 'branch')
              .only('monthly_avg', 'gap', 'item__softech_id', 'branch__softech_branch_id')):
        data[f'{str(m.item.softech_id).strip()}|{m.branch.softech_branch_id}'] = [
            round(float(m.monthly_avg or 0), 2), round(float(m.gap or 0), 1)]
    return run, data


def collect(numbers):
    """Read the ISRs, live stock on every branch + HQ, and the engine numbers once.
    JSON-safe, so the screen can cache it and re-plan at another coverage."""
    numbers = parse_isr_numbers(numbers)
    return collect_requests(_read_isrs(numbers), numbers)


def collect_requests(isrs, numbers=None):
    """Same snapshot for requests that are NOT SOFTECH ISRs — e.g. a «طلبات واتساب» branch
    request (apps.supply.branch_requests.pseudo_isr) — so they get the identical analysis,
    screen and workbook. Each dict carries isr/branch/lines like _read_isrs's."""
    from apps.catalog.models import Item
    from apps.purchasing.rate_writer import _eligible_branches
    numbers = numbers or [r['isr'] for r in isrs]
    branches = sorted(_eligible_branches(), key=lambda b: b.softech_branch_id)   # never 100
    codes = sorted({ln['code'] for r in isrs for ln in r['lines']})
    stock, down, fallback = _live_stock(branches, codes)
    run, eng = _engine(codes)
    # dispatched-not-received transfers into each branch, issued within the engine's window
    # (apps/purchasing/in_transit.py — the SAME definition the demand engine nets out)
    try:
        from apps.purchasing.in_transit import by_branch_code
        transit, transit_days = by_branch_code(codes)
    except Exception as exc:
        logger.warning('isr fulfilment: in-transit unavailable: %s', exc)
        transit, transit_days = {}, None
    names = {str(k).strip(): v for k, v in
             Item.objects.filter(softech_id__in=codes).values_list('softech_id', 'name')}
    unames = user_names(r['user'] for r in isrs)
    for r in isrs:
        r['user_name'] = unames.get(r['user'], '')
    return {'isr_numbers': numbers, 'isrs': isrs,
            'branches': [b.softech_branch_id for b in branches],
            'branch_names': {b.softech_branch_id: b.name for b in branches},
            'stock': stock, 'eng': eng, 'names': names, 'down': down, 'fallback': fallback,
            'transit': transit, 'transit_days': transit_days,
            'run_id': getattr(run, 'id', None),
            'taken_at': datetime.datetime.now().isoformat(timespec='seconds')}


# ── 2. compute (pure; the screen's plan) ────────────────────────────────────────
def _rate_gap(snap, code, bc):
    v = snap['eng'].get(f'{code}|{bc}')
    return (float(v[0]), float(v[1])) if v else (0.0, 0.0)


def _transit(snap, bc, code):
    """Qty on the way INTO the branch (0 when none; older snapshots have no 'transit')."""
    return float((snap.get('transit') or {}).get(bc, {}).get(code) or 0.0)


def _stock(snap, bc, code):
    """None when the branch has no stkbal row (shown blank), else the quantity."""
    return snap['stock'].get(bc, {}).get(code)


def branch_column_order(codes):
    """Display order of branch columns (owner 2026-10-05): by branch code — 130, 140, 150,
    160, 170 … The requesting branch is always shown first on its own; this orders the rest.
    Display only: who gives first is donor_order (most excess first)."""
    return sorted(codes, key=lambda c: (0, int(c)) if str(c).isdigit() else (1, str(c)))


def donor_order(snap, isr, months):
    """Other branches, the one holding the most excess on this ISR's items first."""
    req = isr['branch']
    donors = [b for b in snap['branches'] if b != req]

    def est(b):
        return sum(max(0.0, (_stock(snap, b, ln['code']) or 0.0) -
                       ceiling(_rate_gap(snap, ln['code'], b)[0], months)) for ln in isr['lines'])
    return sorted(donors, key=lambda b: (-est(b), b))


def compute(snap, months, fill=None, basis='requested'):
    months = float(months)
    fill = float(fill if fill is not None else months)
    out, grand = [], {'requested': 0.0, 'transit': 0.0, 'recommended': 0.0, 'planned': 0.0, 'no_sales': 0,
                      'from_branches': 0.0, 'from_hq': 0.0, 'shortage': 0.0,
                      'value_branches': 0.0, 'value_shortage': 0.0, 'items': 0,
                      'full_branches': 0, 'full_all': 0, 'over_ceiling': 0}
    for isr in snap['isrs']:
        req = isr['branch']
        donors = donor_order(snap, isr, months)
        lines = []
        tot = {'requested': 0.0, 'transit': 0.0, 'recommended': 0.0, 'planned': 0.0, 'no_sales': 0,
               'from_branches': 0.0, 'from_hq': 0.0, 'shortage': 0.0,
               'value_branches': 0.0, 'value_shortage': 0.0, 'items': len(isr['lines']),
               'full_branches': 0, 'full_all': 0, 'over_ceiling': 0}
        by_donor = {b: 0.0 for b in donors}
        for ln in isr['lines']:
            code, asked, cost = ln['code'], ln['qty'], ln['cost']
            r_rate, r_gap = _rate_gap(snap, code, req)
            r_stock = _stock(snap, req, code)
            r_transit = _transit(snap, req, code)
            r_have = (r_stock or 0.0) + r_transit          # on the shelf + already on the way
            r_cap = ceiling(r_rate, fill)        # requester's maximum = ITS coverage (C5), not the donors'
            # requested vs recommended (requester topped up to `fill` months, counting what is
            # already in transit to it — never buy / move it twice) → the plan qty
            rec = recommended_qty(r_rate, r_have, asked, fill)
            q = plan_qty(asked, rec, basis)
            no_sales = not r_rate or r_rate <= 0
            after = r_have + q
            # flagged only when this supply pushes it over (existing overstock alone is not)
            over = q > 0 and r_cap > 0 and after > r_cap
            # Owner rule (2026-10-04): when HQ's whole packs cover the WHOLE request, HQ fills
            # it — one shipment, no branch transfer. Otherwise other branches' excess first,
            # then HQ for the rest, then shortage. (Same coverage either way.)
            hq_stock = _stock(snap, HQ, code)
            hq_first = int(max(0.0, hq_stock or 0.0)) >= q > 0
            left = q
            drows = []
            for b in donors:
                rate, gap = _rate_gap(snap, code, b)
                s = _stock(snap, b, code)
                tr = _transit(snap, b, code)
                cap = ceiling(rate, months)
                ex = _excess(s, cap)              # only what is physically on its shelf can move
                give = 0 if hq_first else max(0, min(ex, left))
                left -= give
                by_donor[b] += give
                drows.append({'branch': b, 'stock': s, 'transit': tr, 'rate': rate, 'gap': gap,
                              'need': coverage_need(rate, (s or 0.0) + tr, months),
                              'ceiling': cap, 'excess': ex, 'give': give})
            from_b = q - left
            from_hq = max(0, min(int(max(0.0, hq_stock or 0.0)), left))
            if hq_first:
                from_hq = q                                  # whole packs ≥ q, fractional q too
            shortage = max(0.0, q - from_b - from_hq)
            net_stock = (r_stock or 0.0) + sum(d['stock'] or 0.0 for d in drows)
            net_transit = r_transit + sum(d['transit'] for d in drows)
            net_rate = r_rate + sum(d['rate'] for d in drows)
            lines.append({
                'code': code, 'name': snap['names'].get(code, ''), 'cost': round(cost, 2),
                'qty': asked, 'recommended': rec, 'plan_qty': q, 'no_sales': no_sales,
                'fill_ceiling': ceiling(r_rate, fill),
                'req': {'stock': r_stock, 'transit': r_transit, 'rate': r_rate, 'gap': r_gap,
                        'ceiling': r_cap, 'need': coverage_need(r_rate, r_have, fill),
                        'after': after, 'over_ceiling': over},
                'donors': drows, 'hq_stock': hq_stock,
                'network': {'stock': net_stock, 'transit': net_transit,
                            'stock_with_hq': net_stock + (hq_stock or 0.0),
                            'rate': round(net_rate, 2),
                            'months': round((net_stock + net_transit) / net_rate, 1) if net_rate > 0 else None,
                            'need': coverage_need(r_rate, r_have, fill) + sum(d['need'] for d in drows),
                            'excess': sum(d['excess'] for d in drows)},
                'from_branches': from_b, 'from_hq': from_hq, 'shortage': shortage, 'hq_first': hq_first,
                'full_by_branches': q > 0 and from_b >= q, 'full_overall': shortage <= 0,
                'value_branches': round(cost * from_b, 2), 'value_shortage': round(cost * shortage, 2),
            })
            tot['requested'] += asked
            tot['transit'] += r_transit
            tot['recommended'] += rec
            tot['planned'] += q
            tot['no_sales'] += no_sales
            tot['from_branches'] += from_b
            tot['from_hq'] += from_hq
            tot['shortage'] += shortage
            tot['value_branches'] += cost * from_b
            tot['value_shortage'] += cost * shortage
            tot['full_branches'] += q > 0 and from_b >= q
            tot['full_all'] += shortage <= 0
            tot['over_ceiling'] += over
        for k in grand:
            grand[k] += tot[k]
        tot['value_branches'] = round(tot['value_branches'], 2)
        tot['value_shortage'] = round(tot['value_shortage'], 2)
        out.append({
            'isr': isr['isr'], 'branch': req, 'branch_name': snap.get('branch_names', {}).get(req, ''),
            'for_branch': isr['for_branch'], 'date': isr['date'], 'approved': bool(isr['approved']),
            'value': isr['value'], 'user': isr['user'], 'user_name': isr.get('user_name', ''),
            'kind': isr.get('kind', 'isr'),
            'donors': donors,
            'from_by_donor': {b: v for b, v in by_donor.items() if v}, 'totals': tot, 'lines': lines,
        })
    grand['value_branches'] = round(grand['value_branches'], 2)
    grand['value_shortage'] = round(grand['value_shortage'], 2)
    fallback = snap.get('fallback') or {}
    for r in out:
        r['requester_from_hq_copy'] = r['branch'] in fallback
        r['requester_copy_at'] = fallback.get(r['branch'])
    return {'coverage': months, 'fill_coverage': fill, 'basis': basis, 'basis_label': BASIS[basis],
            'plan_label': PLAN_LABELS[basis],
            'run_id': snap['run_id'], 'taken_at': snap['taken_at'],
            'transit_days': snap.get('transit_days'),
            'down': snap['down'], 'fallback': fallback, 'notices': notices(snap),
            'branches': snap['branches'], 'isrs': out, 'totals': grand}


def notices(snap):
    """Everything the reader must know about the stock read, in Arabic."""
    return fallback_notes(snap.get('fallback') or {}) + list(snap.get('down') or [])


# ── picker: recent ISRs raised by branches (server 100, READ-ONLY) ──────────────
RECENT_MAX_DAYS = 90


def recent_branch_isrs(days=14):
    """Branch-made ISRs (branchcode ≠ 100) of the last `days` days, newest first, with
    line count / qty, who made it, and whether it is one of OUR generated ISRs."""
    from config.sybase import get_sybase_connection
    from apps.purchasing.models import IsrPush
    days = max(1, min(int(days), RECENT_MAX_DAYS))
    c = get_sybase_connection()
    cur = c.cursor()
    try:
        cur.execute(
            'SELECT m.isrdocnumber, m.branchcode, m.forbranchcode, m.docdate, m.israpp, m.docvalue, '
            'm.usercode, count(l.itemcode), sum(l.itemqty) '
            'FROM stockisrm m, stockisr l WHERE l.isrdocnumber = m.isrdocnumber '
            f"AND m.docdate >= dateadd(day, -{days}, getdate()) AND m.branchcode <> '100' "
            'GROUP BY m.isrdocnumber, m.branchcode, m.forbranchcode, m.docdate, m.israpp, m.docvalue, m.usercode '
            'ORDER BY m.docdate DESC, m.isrdocnumber DESC')
        rows = cur.fetchall()
    finally:
        cur.close()
        c.close()
    nums = [int(r[0]) for r in rows]
    ours = set(IsrPush.objects.filter(isrdocnumber__in=nums).values_list('isrdocnumber', flat=True))
    users = user_names(r[6] for r in rows)
    out = []
    for r in rows:
        d, uc = r[3], str(r[6] or '').strip()
        out.append({'isr': str(int(r[0])), 'branch': str(r[1]).strip(), 'for_branch': str(r[2]).strip(),
                    'date': d.strftime('%Y-%m-%d') if hasattr(d, 'strftime') else str(d or '')[:10],
                    'approved': bool(r[4]), 'value': float(r[5] or 0), 'user': uc,
                    'user_name': users.get(uc, ''), 'lines': int(r[7] or 0), 'qty': float(r[8] or 0),
                    'ours': int(r[0]) in ours})
    return out


# ── return proposals: donor excess → HQ, serving the branch's original ISR ──────
def returns_for(isr_numbers):
    """{isr: [live/finished return proposals]} — shown next to each ISR on the screen."""
    from apps.purchasing.models import IsrPush
    out = {str(n): [] for n in isr_numbers}
    for p in (IsrPush.objects.filter(origin_isr__in=[int(n) for n in isr_numbers])
              .order_by('created_at')):
        out[str(p.origin_isr)].append({
            'id': p.id, 'donor': p.branchcode, 'status': p.status, 'status_label': p.get_status_display(),
            'line_count': p.line_count, 'qty': sum(float(l.get('itemqty') or 0) for l in p.lines_snapshot or []),
            'isrdocnumber': p.isrdocnumber, 'created_at': p.created_at.isoformat(timespec='minutes')})
    return out


def create_donor_returns(snap, months, *, only_isr=None, created_by=None, fill=None, basis='requested'):
    """For each ISR in the plan, one PROPOSED IsrPush per donor branch (kind branch_to_hq,
    donor → 100) with exactly what the plan takes from that donor's excess, tagged with
    origin_isr. HQ then fills the branch's ORIGINAL ISR (already in SOFTECH) through
    إذن الصرف — we never add a second HQ→branch ISR for the same need.
    PG only; SOFTECH is written later by the usual approve → push. A donor that already
    has a live return for that ISR is skipped (DB constraint backs this up).
    Returns {'created': [...], 'skipped': [...]}."""
    from django.db import IntegrityError, transaction
    from apps.purchasing import isr_writer
    from apps.purchasing.models import DemandCalculationRun, IsrPush
    plan = compute(snap, months, fill, basis)
    run_id = snap.get('run_id')
    if run_id and not DemandCalculationRun.objects.filter(id=run_id).exists():
        run_id = None                                   # run pruned since the read — audit only
    created, skipped = [], []
    for r in plan['isrs']:
        if only_isr and r['isr'] != str(only_isr):
            continue
        by_donor = {}
        for ln in r['lines']:
            for d in ln['donors']:
                if d['give'] > 0:
                    by_donor.setdefault(d['branch'], []).append((ln['code'], d['give']))
        live = set(IsrPush.objects.filter(
            origin_isr=int(r['isr']),
            status__in=[IsrPush.STATUS_PROPOSED, IsrPush.STATUS_APPROVED, IsrPush.STATUS_PUSHED],
        ).values_list('branchcode', flat=True))
        for donor in r['donors']:                       # plan order (most excess first)
            items = by_donor.get(donor)
            if not items:
                continue
            if donor in live:
                skipped.append({'isr': r['isr'], 'donor': donor, 'reason': 'exists'})
                continue
            lines = isr_writer.build_items_plan(donor, items)    # nowqty read live from the donor
            if not lines:
                skipped.append({'isr': r['isr'], 'donor': donor, 'reason': 'no_lines'})
                continue
            try:
                with transaction.atomic():
                    p = isr_writer._persist_proposal(
                        source=donor, dest=HQ, kind=IsrPush.KIND_BRANCH_TO_HQ, lines=lines,
                        run_id=run_id, created_by=created_by, coverage_months=months)
                    p.origin_isr = int(r['isr'])
                    copy_at = (snap.get('fallback') or {}).get(donor)
                    p.notes = (f'إرجاع فائض فرع {donor} إلى الرئيسي لتلبية طلب الفرع {r["branch"]} '
                               f'رقم {r["isr"]} — الرئيسي يصرف الطلب الأصلي بإذن الصرف. '
                               f'التغطية {months:g} شهر، الأرصدة {snap["taken_at"]}.'
                               + (f' تنبيه: سيرفر الفرع كان غير متاح — الفائض محسوب من نسخة الرئيسي '
                                  f'(آخر تحديث {copy_at}); راجع الرصيد قبل الاعتماد.' if copy_at is not None else ''))
                    p.save(update_fields=['origin_isr', 'notes'])
            except IntegrityError:                      # a parallel click got there first
                skipped.append({'isr': r['isr'], 'donor': donor, 'reason': 'exists'})
                continue
            created.append({'isr': r['isr'], 'donor': donor, 'id': p.id, 'line_count': p.line_count,
                            'qty': sum(float(l['itemqty']) for l in lines)})
    return {'created': created, 'skipped': skipped}


def transfers_for(req):
    """The two-leg transfer proposals already made for a WhatsApp request, per donor."""
    from apps.purchasing.models import IsrPush
    out = {}
    for p in IsrPush.objects.filter(origin_request=req).order_by('created_at'):
        d = out.setdefault(p.origin_donor, {'donor': p.origin_donor, 'legs': []})
        d['legs'].append({'id': p.id, 'kind': p.kind, 'kind_label': p.get_kind_display(),
                          'status': p.status, 'status_label': p.get_status_display(),
                          'line_count': p.line_count, 'isrdocnumber': p.isrdocnumber,
                          'qty': sum(float(l.get('itemqty') or 0) for l in p.lines_snapshot or [])})
    return list(out.values())


def create_request_transfers(snap, months, req, *, created_by=None, fill=None, basis='requested'):
    """«طلبات واتساب» → for each donor the plan draws from, TWO linked PROPOSED IsrPush:
         leg 1  donor → 100            (branch_to_hq)  — the donor sends its excess to HQ
         leg 2  100 → requesting branch (hq_to_branch) — HQ forwards it
    Unlike a SOFTECH ISR (create_donor_returns) there is no branch request in SOFTECH for
    HQ to fill, so leg 2 is its own ISR. PG only; SOFTECH is written later by the usual
    approve → push in the ISR tab. A donor that already has a live leg for this request is
    skipped (DB constraint backs this up). Returns {'created': [...], 'skipped': [...]}."""
    from django.db import IntegrityError, transaction
    from apps.purchasing import isr_writer
    from apps.purchasing.models import DemandCalculationRun, IsrPush
    plan = compute(snap, months, fill, basis)
    r = plan['isrs'][0]
    requester = r['branch']
    run_id = snap.get('run_id')
    if run_id and not DemandCalculationRun.objects.filter(id=run_id).exists():
        run_id = None
    by_donor = {}
    for ln in r['lines']:
        for d in ln['donors']:
            if d['give'] > 0:
                by_donor.setdefault(d['branch'], []).append((ln['code'], d['give']))
    live = set(IsrPush.objects.filter(
        origin_request=req,
        status__in=[IsrPush.STATUS_PROPOSED, IsrPush.STATUS_APPROVED, IsrPush.STATUS_PUSHED],
    ).values_list('origin_donor', flat=True))
    created, skipped = [], []
    for donor in r['donors']:                            # plan order (most excess first)
        items = by_donor.get(donor)
        if not items:
            continue
        if donor in live:
            skipped.append({'donor': donor, 'reason': 'exists'})
            continue
        leg1_lines = isr_writer.build_items_plan(donor, items)       # nowqty from the donor
        leg2_lines = isr_writer.build_items_plan(HQ, items)          # nowqty from HQ
        if not leg1_lines or not leg2_lines:
            skipped.append({'donor': donor, 'reason': 'no_lines'})
            continue
        copy_at = (snap.get('fallback') or {}).get(donor)
        note = (f'طلب واتساب WA-{req.pk} (فرع {requester}): فائض فرع {donor} ← الرئيسي ← فرع {requester}. '
                f'التغطية {months:g} شهر، الأرصدة {snap["taken_at"]}.'
                + (f' تنبيه: سيرفر فرع {donor} كان غير متاح — الفائض محسوب من نسخة الرئيسي '
                   f'(آخر حركة {copy_at}); راجع الرصيد قبل الاعتماد.' if copy_at is not None else ''))
        try:
            with transaction.atomic():
                leg1 = isr_writer._persist_proposal(
                    source=donor, dest=HQ, kind=IsrPush.KIND_BRANCH_TO_HQ, lines=leg1_lines,
                    run_id=run_id, created_by=created_by, coverage_months=months)
                leg2 = isr_writer._persist_proposal(
                    source=HQ, dest=requester, kind=IsrPush.KIND_HQ_TO_BRANCH, lines=leg2_lines,
                    run_id=run_id, created_by=created_by, coverage_months=months, linked=leg1)
                for p in (leg1, leg2):
                    p.origin_request, p.origin_donor, p.notes = req, donor, note
                leg1.linked_push = leg2
                leg1.save(update_fields=['origin_request', 'origin_donor', 'notes', 'linked_push'])
                leg2.save(update_fields=['origin_request', 'origin_donor', 'notes'])
        except IntegrityError:                          # a parallel click got there first
            skipped.append({'donor': donor, 'reason': 'exists'})
            continue
        created.append({'donor': donor, 'leg1_id': leg1.id, 'leg2_id': leg2.id,
                        'line_count': leg1.line_count, 'qty': sum(float(l['itemqty']) for l in leg1_lines)})
    return {'created': created, 'skipped': skipped}


# ── 3. workbook (formulas; same rules as compute) ───────────────────────────────
def build_workbook(snap, months, fill=None, basis='requested'):
    from openpyxl import Workbook
    months = float(months)
    fill = float(fill if fill is not None else months)
    taken_at = datetime.datetime.fromisoformat(snap['taken_at'])
    wb = Workbook()
    summary = wb.active
    summary.title = 'ملخص'
    sheets = []
    for r in snap['isrs']:
        ws = wb.create_sheet(r['isr'] if r.get('kind') == 'whatsapp' else f'ISR {r["isr"]}')
        sheets.append((r, ws.title, _isr_sheet(ws, r, snap, months)))
    _summary_sheet(summary, sheets, months, snap['run_id'], taken_at, notices(snap), fill, basis)
    _notes_sheet(wb.create_sheet('الشرح'), snap['run_id'], taken_at, notices(snap), months, fill, basis)
    wb.calculation.fullCalcOnLoad = True          # Excel computes every formula on open
    return wb


def workbook_filename(snap):
    return f'isr_fulfillment_{"_".join(snap["isr_numbers"])}_{snap["taken_at"][:10]}.xlsx'


def _isr_sheet(ws, r, snap, months):
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter as L
    from openpyxl.formatting.rule import CellIsRule

    req = r['branch']
    donors = donor_order(snap, r, months)         # allocation formulas draw in this order
    shown = branch_column_order(donors)           # …but the columns read 130, 140, 150, 160, 170

    ws.sheet_view.rightToLeft = True
    thin = Side(style='thin', color='C9CED6')
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill('solid', fgColor=NAVY)
    grp_fills = ['DCE6F2', 'EEF2F7']
    f_in = Font(name=FONT, size=10, color='0000FF')      # inputs (from SOFTECH / engine)
    f_fx = Font(name=FONT, size=10, color='000000')      # formulas
    f_hd = Font(name=FONT, size=10, bold=True, color='FFFFFF')
    f_gp = Font(name=FONT, size=10, bold=True, color=NAVY)
    QTY, VAL = '#,##0.0;-#,##0.0;-', '#,##0;-#,##0;-'

    cols = []      # (group, header, kind, width)  kind: 'in' | 'fx'

    def add(group, header, kind='fx', width=10):
        cols.append((group, header, kind, width))
        return len(cols)
    c_code = add('الصنف', 'الكود', 'in', 9)
    c_name = add('الصنف', 'اسم الصنف', 'in', 34)
    c_cost = add('الصنف', 'التكلفة / عبوة', 'in', 10)
    c_req = add('الصنف', 'الكمية المطلوبة', 'in', 10)
    c_rec = add('الصنف', 'الكمية الموصى بها (تغطية الطلب)', 'fx', 12)
    c_pl = add('الصنف', plan_label_formula(), 'fx', 14)      # header follows C6
    copy = snap.get('fallback') or {}                    # branches read from server 100's copy
    tag = lambda b: ' (نسخة الرئيسي)' if b in copy else ''
    g_req = f'الفرع الطالب {BL(req)}{tag(req)}'
    c_rs = add(g_req, 'الرصيد الحالي', 'in')
    c_rt = add(g_req, 'بالطريق (لم يُستلم)', 'in')
    c_rr = add(g_req, 'معدل البيع / شهر', 'in')
    c_rg = add(g_req, 'الاحتياج (حتى تغطية الطالب)', 'fx', 11)
    c_rc = add(g_req, 'الحد الأقصى')
    c_ra = add(g_req, 'الرصيد بعد التوريد')
    c_rx = add(g_req, 'يتجاوز الحد الأقصى؟', 'fx', 11)
    dcol = {}
    for b in shown:
        g = f'فرع {BL(b)}{tag(b)}'
        dcol[b] = {'s': add(g, 'الرصيد', 'in'), 't': add(g, 'بالطريق', 'in'), 'r': add(g, 'معدل البيع', 'in'),
                   'g': add(g, 'الاحتياج (حتى تغطية المانح)', 'fx', 11), 'c': add(g, 'الحد الأقصى'),
                   'x': add(g, 'فائض قابل للنقل')}
    c_hq = add('الرئيسي 100', 'رصيد الرئيسي (المخازن الفعلية)', 'in', 12)
    c_ns = add('إجمالي الفروع', 'رصيد الفروع')
    c_nt = add('إجمالي الفروع', 'بالطريق للفروع')
    c_nh = add('إجمالي الفروع', 'الرصيد + الرئيسي')
    c_nr = add('إجمالي الفروع', 'معدل البيع')
    c_nm = add('إجمالي الفروع', 'شهور التغطية')
    c_nn = add('إجمالي الفروع', 'احتياج الفروع')
    c_nx = add('إجمالي الفروع', 'فائض الفروع الأخرى')
    c_hf = add('خطة التوريد', 'الرئيسي يغطي الطلب؟', 'fx', 11)   # → HQ fills, no branch transfer
    acol = {b: add('خطة التوريد', f'من فرع {BL(b)}', 'fx', 14) for b in shown}
    c_ab = add('خطة التوريد', 'إجمالي من الفروع')
    c_ah = add('خطة التوريد', 'من الرئيسي')
    c_sh = add('خطة التوريد', 'نقص (شراء)')
    c_fb = add('خطة التوريد', 'مغطى من الفروع بالكامل؟', 'fx', 12)
    c_fa = add('خطة التوريد', 'مغطى بالكامل؟', 'fx', 11)
    c_vb = add('خطة التوريد', 'قيمة المنقول من الفروع', 'fx', 12)
    c_vs = add('خطة التوريد', 'قيمة النقص', 'fx', 11)

    # title rows
    ncol = len(cols)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncol)
    wa = r.get('kind') == 'whatsapp'
    ws.cell(1, 1, f'{"طلب واتساب" if wa else "طلب توريد"} {r["isr"]} — فرع {BL(req)} — خطة التوريد وإعادة التوزيع').font = Font(
        name=FONT, size=14, bold=True, color=NAVY)
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncol)
    status = 'طلب فرع من مجموعة واتساب (غير مسجَّل في SOFTECH)' if wa else \
        f'{"معتمد" if r["approved"] else "غير معتمد"} في SOFTECH'
    ws.cell(2, 1, f'تاريخ الطلب {r["date"]} · {status} · '
                  f'{len(r["lines"])} صنف · قيمة الطلب {r["value"]:,.0f} ج · المستخدم '
                  f'{user_label(r["user"], {r["user"]: r.get("user_name", "")})}'
                  + (f' · ترتيب السحب من الفروع (الأكثر فائضاً أولاً): {" ← ".join(donors)}' if donors else '')).font = Font(
        name=FONT, size=10, color='555555')
    if copy:                                             # the warning travels with every sheet
        ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=ncol)
        ws.cell(3, 1, ' '.join(fallback_notes(copy))).font = Font(name=FONT, size=10, bold=True, color='CC0000')

    # group + column headers (rows 4, 5)
    HR, CR, R0 = 4, 5, 6
    start, gi = 1, 0
    while start <= ncol:
        g = cols[start - 1][0]
        end = start
        while end + 1 <= ncol and cols[end][0] == g:
            end += 1
        if end > start:
            ws.merge_cells(start_row=HR, start_column=start, end_row=HR, end_column=end)
        cell = ws.cell(HR, start, g)
        cell.font, cell.alignment = f_gp, Alignment(horizontal='center', vertical='center')
        for c in range(start, end + 1):
            ws.cell(HR, c).fill = PatternFill('solid', fgColor=grp_fills[gi % 2])
            ws.cell(HR, c).border = box
        gi += 1
        start = end + 1
    for i, (_, header, kind, width) in enumerate(cols, start=1):
        cell = ws.cell(CR, i, header)
        cell.font, cell.fill, cell.border = f_hd, head_fill, box
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        ws.column_dimensions[L(i)].width = width
    ws.row_dimensions[CR].height = 32

    def A(col, row):
        return f'{L(col)}{row}'

    def cap(rate_cell, ref=COV_REF, eq='='):
        return f'{eq}IF({rate_cell}>0,MAX(ROUND({rate_cell}*{ref},1),1),0)'

    n = len(r['lines'])
    for k, ln in enumerate(r['lines']):
        row = R0 + k
        code = ln['code']
        rate_r, gap_r = _rate_gap(snap, code, req)
        vals = {c_code: code, c_name: snap['names'].get(code, ''), c_cost: round(ln['cost'], 2),
                c_req: ln['qty'], c_rs: _stock(snap, req, code), c_rt: _transit(snap, req, code),
                c_rr: rate_r, c_hq: _stock(snap, HQ, code)}
        for b in donors:
            rb, gb = _rate_gap(snap, code, b)
            vals[dcol[b]['s']] = _stock(snap, b, code)
            vals[dcol[b]['t']] = _transit(snap, b, code)
            vals[dcol[b]['r']] = rb
        for col, v in vals.items():
            ws.cell(row, col, v)
        ws.cell(row, c_rc, cap(A(c_rr, row), FILL_REF))          # requester's maximum: C5
        # need = C5 × sales − stock − in transit, rounded UP when positive (≥ 1 pack), else 0
        ws.cell(row, c_rg, f'=MAX(0,ROUNDUP({FILL_REF}*{A(c_rr, row)}-{A(c_rs, row)}-{A(c_rt, row)},0))')
        # recommended: requester topped up to the fill coverage; no sales → the requested qty
        ws.cell(row, c_rec, f'=IF({A(c_rr, row)}<=0,{A(c_req, row)},{A(c_rg, row)})')
        ws.cell(row, c_pl, f'=IF({BASIS_REF}="{BASIS["requested"]}",{A(c_req, row)},'
                           f'IF({BASIS_REF}="{BASIS["recommended"]}",{A(c_rec, row)},'
                           f'MIN({A(c_req, row)},{A(c_rec, row)})))')
        P = A(c_pl, row)                  # every allocation below works on the PLAN qty
        ws.cell(row, c_ra, f'={A(c_rs, row)}+{A(c_rt, row)}+{P}')
        ws.cell(row, c_rx, f'=IF(AND({P}>0,{A(c_rc, row)}>0,{A(c_ra, row)}>{A(c_rc, row)}),"نعم","")')
        for b in donors:
            dc = dcol[b]
            ws.cell(row, dc['c'], cap(A(dc['r'], row)))
            ws.cell(row, dc['g'], f'=MAX(0,ROUNDUP({COV_REF}*{A(dc["r"], row)}-{A(dc["s"], row)}-{A(dc["t"], row)},0))')
            ws.cell(row, dc['x'], f'=MAX(0,ROUNDDOWN({A(dc["s"], row)}-{A(dc["c"], row)},0))')
        ws.cell(row, c_ns, '=' + '+'.join([A(c_rs, row)] + [A(dcol[b]['s'], row) for b in donors]))
        ws.cell(row, c_nt, '=' + '+'.join([A(c_rt, row)] + [A(dcol[b]['t'], row) for b in donors]))
        ws.cell(row, c_nh, f'={A(c_ns, row)}+{A(c_hq, row)}')
        ws.cell(row, c_nr, '=' + '+'.join([A(c_rr, row)] + [A(dcol[b]['r'], row) for b in donors]))
        ws.cell(row, c_nm, f'=IF({A(c_nr, row)}>0,({A(c_ns, row)}+{A(c_nt, row)})/{A(c_nr, row)},"")')
        ws.cell(row, c_nn, '=' + '+'.join([f'MAX(0,{A(c_rg, row)})'] +
                                          [f'MAX(0,{A(dcol[b]["g"], row)})' for b in donors]))
        ws.cell(row, c_nx, ('=' + '+'.join(A(dcol[b]['x'], row) for b in donors)) if donors else 0)
        # HQ covers the whole request → it fills it alone (owner rule 2026-10-04)
        ws.cell(row, c_hf, f'=IF(AND({P}>0,ROUNDDOWN(MAX(0,{A(c_hq, row)}),0)>={P}),"نعم","")')
        prev = []
        for b in donors:                  # else cascade: each donor gives up to its excess
            left = P + ''.join(f'-{p}' for p in prev)
            ws.cell(row, acol[b], f'=IF({A(c_hf, row)}="نعم",0,MAX(0,MIN({A(dcol[b]["x"], row)},{left})))')
            prev.append(A(acol[b], row))
        ws.cell(row, c_ab, ('=' + '+'.join(prev)) if prev else 0)
        # HQ-first: HQ hands over the whole plan qty (fractional strips too) — same as compute()
        ws.cell(row, c_ah, f'=IF({A(c_hf, row)}="نعم",{P},'
                           f'MAX(0,MIN(ROUNDDOWN(MAX(0,{A(c_hq, row)}),0),{P}-{A(c_ab, row)})))')
        ws.cell(row, c_sh, f'=MAX(0,{P}-{A(c_ab, row)}-{A(c_ah, row)})')
        ws.cell(row, c_fb, f'=IF(AND({P}>0,{A(c_ab, row)}>={P}),"نعم","لا")')
        ws.cell(row, c_fa, f'=IF({A(c_sh, row)}<=0,"نعم","لا")')
        ws.cell(row, c_vb, f'={A(c_cost, row)}*{A(c_ab, row)}')
        ws.cell(row, c_vs, f'={A(c_cost, row)}*{A(c_sh, row)}')
        for i, (_, _, kind, _) in enumerate(cols, start=1):
            cell = ws.cell(row, i)
            cell.font = f_in if kind == 'in' else f_fx
            cell.border = box
            if i == c_name:
                continue
            cell.alignment = Alignment(horizontal='center')
            if i in (c_cost, c_vb, c_vs):
                cell.number_format = VAL
            elif i not in (c_code, c_rx, c_fb, c_fa, c_hf):
                cell.number_format = QTY

    # totals row
    last = R0 + max(n, 1) - 1
    tot = last + 1
    ws.cell(tot, c_name, 'الإجمالي').font = Font(name=FONT, size=10, bold=True)
    sum_cols = [c_req, c_rec, c_pl, c_rs, c_rt, c_hq, c_ns, c_nt, c_nh, c_nr, c_nn, c_nx, c_ab, c_ah, c_sh, c_vb, c_vs] + \
               list(acol.values()) + [dcol[b]['s'] for b in donors] + [dcol[b]['t'] for b in donors] + \
               [dcol[b]['x'] for b in donors]
    for col in sum_cols:
        cell = ws.cell(tot, col, f'=SUM({A(col, R0)}:{A(col, last)})')
        cell.font = Font(name=FONT, size=10, bold=True)
        cell.number_format = VAL if col in (c_vb, c_vs) else QTY
        cell.alignment = Alignment(horizontal='center')
    for col in (c_fb, c_fa, c_hf):
        cell = ws.cell(tot, col, f'=COUNTIF({A(col, R0)}:{A(col, last)},"نعم")&" / "&{n}')
        cell.font = Font(name=FONT, size=10, bold=True)
        cell.alignment = Alignment(horizontal='center')
    for i in range(1, ncol + 1):
        ws.cell(tot, i).fill = PatternFill('solid', fgColor='F3F4F6')
        ws.cell(tot, i).border = box

    # highlights
    def rng(col):
        return f'{A(col, R0)}:{A(col, last)}'
    red = PatternFill('solid', fgColor='FDE2E1')
    green = PatternFill('solid', fgColor='DDF4E4')
    ws.conditional_formatting.add(rng(c_sh), CellIsRule(operator='greaterThan', formula=['0'], fill=red))
    for col in (c_fb, c_fa):
        ws.conditional_formatting.add(rng(col), CellIsRule(operator='equal', formula=['"نعم"'], fill=green))
        ws.conditional_formatting.add(rng(col), CellIsRule(operator='equal', formula=['"لا"'], fill=red))
    ws.conditional_formatting.add(rng(c_rx), CellIsRule(operator='equal', formula=['"نعم"'],
                                                        fill=PatternFill('solid', fgColor='FFF4CC')))
    ws.conditional_formatting.add(rng(c_hf), CellIsRule(operator='equal', formula=['"نعم"'], fill=green))
    for b in donors:
        ws.conditional_formatting.add(rng(dcol[b]['x']), CellIsRule(
            operator='greaterThan', formula=['0'], fill=PatternFill('solid', fgColor='E8F0FE')))
    ws.freeze_panes = ws.cell(R0, c_rs)
    ws.auto_filter.ref = f'{A(1, CR)}:{A(ncol, last)}'

    return {'first': R0, 'last': last, 'total': tot, 'n': n, 'req': c_req, 'rec': c_rec, 'pl': c_pl,
            'ab': c_ab,
            'ah': c_ah, 'sh': c_sh, 'fb': c_fb, 'fa': c_fa, 'vb': c_vb, 'vs': c_vs, 'rx': c_rx,
            'donors': donors, 'acol': acol}


def _summary_sheet(ws, sheets, months, run_id, taken_at, down, fill=None, basis='requested'):
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter as L
    ws.sheet_view.rightToLeft = True
    thin = Side(style='thin', color='C9CED6')
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    ws.cell(1, 1, 'خطة توريد طلبات الفروع — ملخص').font = Font(name=FONT, size=14, bold=True, color=NAVY)
    ws.cell(2, 1, f'بيانات المخزون من SOFTECH بتاريخ {taken_at:%Y-%m-%d %H:%M} · معدلات البيع من تشغيل '
                  f'المحرك #{run_id}').font = Font(name=FONT, size=10, color='555555')
    from openpyxl.worksheet.datavalidation import DataValidation
    fill = months if fill is None else fill
    inputs = [
        (4, 'شهور تغطية الفروع المانحة (ما يحتفظ به كل فرع: معدل البيع × الشهور، لا يقل عن عبوة)', months),
        (5, 'شهور تغطية الفرع الطالب (الاحتياج = الشهور × معدل بيعه − رصيده − بالطريق)', fill),
        (6, 'الكمية التي تُوزَّع (المطلوبة / الموصى بها / الأقل من الاثنين)', BASIS[basis]),
    ]
    for r_, label, v in inputs:
        ws.cell(r_, 1, label).font = Font(name=FONT, size=10, bold=True)
        c = ws.cell(r_, 3, v)
        c.font = Font(name=FONT, size=11, bold=True, color='0000FF')
        c.fill = PatternFill('solid', fgColor='FFFF00')
        c.border = box
    dv = DataValidation(type='list', formula1='"' + ','.join(BASIS.values()) + '"', allow_blank=False)
    ws.add_data_validation(dv)
    dv.add('C6')
    ws.cell(7, 1, '← غيّر أي خانة صفراء لإعادة حساب الكميات والحدود والفائض وخطة التوريد في كل الطلبات').font = Font(
        name=FONT, size=9, italic=True, color='777777')

    heads = ['رقم الطلب', 'الفرع الطالب', 'عدد الأصناف', 'إجمالي المطلوب', 'إجمالي الموصى به',
             plan_label_formula().replace(BASIS_REF, '$C$6'), 'يُغطى من فائض الفروع',
             'من الرئيسي', 'نقص (شراء)', 'أصناف مغطاة من الفروع بالكامل', 'أصناف مغطاة بالكامل',
             'أصناف تتجاوز الحد الأقصى بعد التوريد', 'قيمة المنقول من الفروع', 'قيمة النقص']
    HR = 9

    def fmt(i):
        return '#,##0;-#,##0;-' if i in (13, 14) else '#,##0.0;-#,##0.0;-' if 4 <= i <= 9 else 'General'
    for i, h in enumerate(heads, start=1):
        c = ws.cell(HR, i, h)
        c.font = Font(name=FONT, size=10, bold=True, color='FFFFFF')
        c.fill = PatternFill('solid', fgColor=NAVY)
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        c.border = box
        ws.column_dimensions[L(i)].width = 30 if i == 2 else 15      # «الفرع الطالب» = code · name
    ws.row_dimensions[HR].height = 34
    for k, (r, title, m) in enumerate(sheets):
        row = HR + 1 + k
        s = f"'{title}'!"

        def rng(col):
            return f'{s}{L(col)}{m["first"]}:{L(col)}{m["last"]}'
        vals = [r['isr'], BL(r['branch']), m['n'],
                f'=SUM({rng(m["req"])})', f'=SUM({rng(m["rec"])})', f'=SUM({rng(m["pl"])})',
                f'=SUM({rng(m["ab"])})', f'=SUM({rng(m["ah"])})',
                f'=SUM({rng(m["sh"])})', f'=COUNTIF({rng(m["fb"])},"نعم")',
                f'=COUNTIF({rng(m["fa"])},"نعم")', f'=COUNTIF({rng(m["rx"])},"نعم")',
                f'=SUM({rng(m["vb"])})', f'=SUM({rng(m["vs"])})']
        for i, v in enumerate(vals, start=1):
            c = ws.cell(row, i, v)
            c.font = Font(name=FONT, size=10)
            c.border = box
            c.alignment = Alignment(horizontal='center')
            c.number_format = fmt(i)
    tr = HR + 1 + len(sheets)
    ws.cell(tr, 1, 'الإجمالي').font = Font(name=FONT, size=10, bold=True)
    for i in range(3, len(heads) + 1):
        c = ws.cell(tr, i, f'=SUM({L(i)}{HR + 1}:{L(i)}{tr - 1})')
        c.font = Font(name=FONT, size=10, bold=True)
        c.border = box
        c.alignment = Alignment(horizontal='center')
        c.number_format = fmt(i)
    ws.column_dimensions['A'].width = 18
    for k, msg in enumerate(down):                        # Arabic notices (fallback / outage)
        ws.cell(tr + 2 + k, 1, 'تنبيه: ' + msg).font = Font(name=FONT, size=10, color='CC0000')


def _transit_days_text():
    from apps.purchasing.in_transit import max_age_days
    return max_age_days()


def _notes_sheet(ws, run_id, taken_at, down, months, fill=None, basis='requested'):
    from openpyxl.styles import Alignment, Font
    ws.sheet_view.rightToLeft = True
    ws.column_dimensions['A'].width = 120
    lines = [
        ('الشرح والافتراضات', True),
        (f'• الرصيد: رصيد SOFTECH الحالي (stkbal.nowqty) لكل فرع من سيرفر الفرع نفسه. رصيد الرئيسي = مجموع المخازن الفعلية للفرع 100 (الرئيسي 100 + اكسسوارات 104)، ولا يشمل Washout (102) ولا منتهي الصلاحية (105). وقت القراءة {taken_at:%Y-%m-%d %H:%M}.', False),
        (f'• معدل البيع: من آخر تشغيل ناجح لمحرك الطلب (#{run_id}). الاحتياج = (شهور التغطية × معدل البيع الشهري) − الرصيد الحالي − الرصيد بالطريق؛ إذا كان موجباً يُقرَّب لأعلى لعبوة كاملة (فلا يقل عن عبوة، حتى للأصناف بطيئة الحركة)، وإلا صفر: للفرع الطالب بشهور تغطيته (خانة C5) ولكل فرع مانح بشهور تغطية المانحين (خانة C4). الكمية الموصى بها = احتياج الفرع الطالب (وللصنف الذي لا يبيعه = الكمية المطلوبة).', False),
        (f'• الحد الأقصى = معدل البيع × شهور التغطية (خانة الملخص، حالياً {months:g}) ولا يقل عن عبوة واحدة للأصناف التي تُباع؛ صنف بلا مبيعات في الفرع حدّه 0.', False),
        (f'• الكمية الموصى بها = احتياج الفرع الطالب = (شهور تغطية الطالب، حالياً {(months if fill is None else fill):g}) × معدل بيعه الشهري − رصيده الحالي − الرصيد بالطريق؛ إذا كان موجباً يُقرَّب لأعلى (عبوة على الأقل)، وإلا صفر. صنف لا يبيعه الفرع الطالب = الكمية المطلوبة كما هي.', False),
        (f'• «{PLAN_LABELS["min"]}» (الافتراضي) = الأقل من الكمية المطلوبة والكمية الموصى بها. يمكن تغييرها من الخانة C6 (حالياً: {BASIS[basis]}) إلى المطلوبة أو الموصى بها، ويتغير اسم العمود معها. كل التوزيع (الفروع/الرئيسي/النقص) محسوب على هذه الكمية.', False),
        (f'• بالطريق = تحويلات بين الفروع (125) صُرفت ولم تُستلم بعد في الفرع المستلم، الصادرة خلال آخر {_transit_days_text()} يوماً — نفس قاعدة محرك الاحتياج (الأقدم مستندات غير مُسوّاة لا تُحتسب). تُحسب مع الرصيد في الاحتياج والكمية الموصى بها والرصيد بعد التوريد حتى لا يُشترى أو يُحوَّل نفس الصنف مرتين؛ أما الفائض القابل للنقل فمن الرصيد الفعلي فقط.', False),
        ('• الفائض القابل للنقل = الرصيد − الحد الأقصى، بعبوات كاملة فقط (تقريب لأسفل). الفرع المانح يحتفظ دائماً بحده الأقصى.', False),
        ('• صنف بلا مبيعات في فرع مانح: كل رصيده يعتبر فائضاً — راجع الأصناف الجديدة قيد التجربة قبل نقلها.', False),
        ('• خطة التوريد: إذا كان رصيد الرئيسي (عبوات كاملة) يغطي الكمية المطلوبة بالكامل، يُصرف الطلب كله من الرئيسي — شحنة واحدة بلا تحويل من الفروع («الرئيسي يغطي الطلب؟» = نعم). وإلا تُسحب الكمية أولاً من فائض الفروع الأخرى — الأكثر فائضاً أولاً (الترتيب مكتوب في السطر الثاني من كل ورقة) — ثم من الرئيسي، والباقي = نقص يحتاج شراء. أعمدة الفروع معروضة دائماً: الفرع الطالب أولاً ثم بقية الفروع بالكود (130، 140، 150، 160، 170).', False),
        ('• الحد الأقصى للفرع الطالب = معدل بيعه × شهور تغطيته (خانة C5). «يتجاوز الحد الأقصى؟» = نعم فقط إذا كان هناك توريد فعلي، وكان الرصيد الحالي + بالطريق + الكمية الموردة أكبر من هذا الحد.', False),
        ('• القيم بسعر التكلفة المسجل في طلب التوريد. الأرقام الزرقاء مدخلات من SOFTECH/المحرك، والسوداء معادلات تُحسب تلقائياً.', False),
        ('• هذا التقرير للقراءة فقط — لا يكتب شيئاً في SOFTECH.', False),
    ]
    lines += [('• ' + msg, False) for msg in down]
    for i, (t, bold) in enumerate(lines, start=1):
        c = ws.cell(i, 1, t)
        c.font = Font(name=FONT, size=12 if bold else 10, bold=bold, color=NAVY if bold else '000000')
        c.alignment = Alignment(wrap_text=True, vertical='top')
