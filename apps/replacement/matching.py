"""
apps/replacement/matching.py — PURE, explainable matching (no ORM, no SOFTECH).

Two questions the native data never answers directly (doc 25 §0.2):

1. resolve_contract_sale — which contract sale does a virtual-supplier purchase buy back?
   SOFTECH stores no purchase↔sale reference, so we match on branch + item + qty + public
   price + date window, following sale/return chains (a sale fully returned the same day is
   a VOID pair; a partial return reduces the standing sale).

2. select_funding — which POS receipts did a supplier-payment voucher's cash pay for?
   Receipts carry the patient's phcode (or a «عميل تبديل» account) — high confidence — or
   are anonymous cash sales matched only by time + amount — never above MEDIUM, so a person
   must confirm them.

Every score is a list of {signal, points, detail} so the UI can show WHY (§51). Inputs are
plain dicts so the functions are unit-testable without a database.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from itertools import combinations

from . import config as C

D0 = Decimal('0')
CENT = Decimal('0.01')


def _d(v) -> Decimal:
    return v if isinstance(v, Decimal) else Decimal(str(v or 0))


def _ev(signal, points, detail):
    return {'signal': signal, 'points': float(points), 'detail': detail}


# ═══════════════════════════════════════════════════════════════════════════════
# 1. contract sale ↔ purchase
# ═══════════════════════════════════════════════════════════════════════════════

def pair_returns(sales: list[dict], returns: list[dict]) -> tuple[dict, dict]:
    """Attach contract returns (doc 30) to the sales they reverse.

    sales/returns: {key, phcode, date, total, lines: {itemcode: {'qty','unit','list'}}}
    Returns (void_by_sale {sale_key: return}, partial_by_sale {sale_key: [returns]}).
      • FULL return: same patient, within RETURN_PAIR_DAYS after the sale, identical total
        and identical item set → the sale is VOID (cancelled pair).
      • otherwise PARTIAL: attached to the latest same-patient sale on/before the return
        date that contains every returned item.
    """
    days = C.get('RETURN_PAIR_DAYS')
    void, partial, used = {}, {}, set()
    for r in sorted(returns, key=lambda x: x['date']):
        best = None
        for s in sales:
            if s['key'] in void or s['phcode'] != r['phcode']:
                continue
            if not (s['date'] <= r['date'] <= s['date'] + timedelta(days=days)):
                continue
            if abs(_d(s['total']) - _d(r['total'])) <= CENT and set(s['lines']) == set(r['lines']):
                best = s
                break
        if best:
            void[best['key']] = r
            used.add(r['key'])
    for r in sorted(returns, key=lambda x: x['date']):
        if r['key'] in used:
            continue
        cands = [s for s in sales
                 if s['key'] not in void and s['phcode'] == r['phcode']
                 and s['date'] <= r['date'] <= s['date'] + timedelta(days=days)
                 and set(r['lines']) <= set(s['lines'])]
        if cands:
            s = max(cands, key=lambda x: (x['date'], x.get('trans_time') or x['date']))
            partial.setdefault(s['key'], []).append(r)
    return void, partial


def effective_lines(sale: dict, partial_returns: list[dict]) -> dict:
    """Sale lines net of partial returns (qty only; prices stay the sale's)."""
    out = {code: dict(v) for code, v in sale['lines'].items()}
    for r in partial_returns or []:
        for code, v in r['lines'].items():
            if code in out:
                out[code]['qty'] = _d(out[code]['qty']) - _d(v['qty'])
    return {c: v for c, v in out.items() if _d(v['qty']) > D0}


def score_contract_sale(purchase: dict, sale: dict, eff_lines: dict) -> tuple[Decimal, list]:
    """purchase: {date, lines: {itemcode: {'qty','public'}}}. Max 100."""
    ev, pts = [], D0
    p_items = set(purchase['lines'])
    covered = p_items & set(eff_lines)
    if not covered:
        return D0, [_ev('items', 0, 'لا يوجد صنف مشترك بعد خصم المرتجعات')]
    if covered == p_items:
        pts += 40
        ev.append(_ev('items', 40, f'كل أصناف الشراء ({len(p_items)}) موجودة في بيع التعاقد'))
    else:
        # proportional, so the patient whose sale covers MORE of a multi-item purchase wins
        p = (Decimal(30) * len(covered) / len(p_items)).quantize(Decimal('0.1'))
        pts += p
        ev.append(_ev('items', p, f'{len(covered)} من {len(p_items)} أصناف موجودة'))

    qty_ok = all(_d(purchase['lines'][c]['qty']) <= _d(eff_lines[c]['qty']) + Decimal('0.0001')
                 for c in covered)
    qty_eq = all(abs(_d(purchase['lines'][c]['qty']) - _d(eff_lines[c]['qty'])) <= Decimal('0.0001')
                 for c in covered)
    if qty_eq:
        pts += 20
        ev.append(_ev('qty', 20, 'الكمية المشتراة = الكمية المباعة'))
    elif qty_ok:
        pts += 12
        ev.append(_ev('qty', 12, 'الكمية المشتراة ≤ الكمية المباعة'))
    else:
        ev.append(_ev('qty', 0, 'الكمية المشتراة أكبر من المباعة'))

    price_ok = all(
        _d(eff_lines[c].get('list')) > 0
        and abs(_d(purchase['lines'][c]['public']) - _d(eff_lines[c]['list']))
        <= max(Decimal('0.5'), _d(eff_lines[c]['list']) * Decimal('0.005'))
        for c in covered)
    if price_ok:
        pts += 15
        ev.append(_ev('public_price', 15, 'سعر الجمهور في الشراء = سعر الجمهور في البيع'))

    delta = (purchase['date'] - sale['date']).days          # >0 ⇒ sale came first
    if delta == 0:
        pts += 15
        ev.append(_ev('timing', 15, 'الشراء والبيع في نفس اليوم'))
    elif delta < 0:
        p = 15 if -delta <= 7 else 8
        pts += p
        ev.append(_ev('timing', p, f'الشراء قبل البيع بـ {-delta} يوم (الترتيب المفضّل)'))
    else:
        p = 12 if delta <= 7 else (8 if delta <= 31 else 3)
        pts += p
        ev.append(_ev('timing', p, f'البيع قبل الشراء بـ {delta} يوم'))

    pts += 10
    ev.append(_ev('channel', 10, f'قناة تعاقد ({sale.get("channel", "")})'))

    # clock proximity: the buy-back purchase is typed close to that patient's contract sale.
    # Not capped here — it is a tie-breaker between otherwise identical same-day candidates.
    pt, st = purchase.get('trans_time'), sale.get('trans_time')
    if pt is not None and st is not None and delta == 0:
        mins = abs((pt - st).total_seconds()) / 60
        if mins <= 30:
            pts += 10
            ev.append(_ev('clock', 10, f'الشراء على بعد {mins:.0f} دقيقة من بيع التعاقد'))
        elif mins <= 120:
            pts += 5
            ev.append(_ev('clock', 5, f'الشراء على بعد {mins:.0f} دقيقة من بيع التعاقد'))
    return pts, ev


def remaining_capacity(eff_lines: dict, sale_key, claimed: dict) -> dict:
    """Sale lines minus quantities ALREADY bought back by earlier cases (capacity)."""
    out = {}
    for code, v in eff_lines.items():
        left = _d(v['qty']) - _d(claimed.get((sale_key, code), 0))
        if left > Decimal('0.0001'):
            out[code] = {**v, 'qty': left}
    return out


def resolve_contract_sale(purchase: dict, sales: list[dict], returns: list[dict],
                          patient_hint: set | frozenset = frozenset(), claimed: dict | None = None) -> dict:
    """Pick the standing contract sale the purchase buys back.

    patient_hint = phcodes seen on product receipts near this purchase's vouchers — the
    redemption itself names the patient, which breaks ties between patients who were all
    prescribed the same (often chronic) item.

    claimed = {(sale_key, itemcode): qty} already bought back by EARLIER cases. A sale line can
    only be bought back up to its sold quantity, so capacity is consumed first-come; a purchase
    whose items have no capacity left anywhere is an over-claim (`over_claim`), the genuine
    double-processing signal.

    Returns {sale, partial_returns, void_pairs [(sale, return)], score, conf, evidence,
             eff_lines, ambiguous_patients [phcode…], over_claim [{itemcode, purchased, left}]}
    — sale None when nothing qualifies.
    """
    claimed = claimed or {}
    void, partial = pair_returns(sales, returns)
    scored, over_cands = [], []
    for s in sales:
        if s['key'] in void:
            continue
        full = effective_lines(s, partial.get(s['key']))
        eff = remaining_capacity(full, s['key'], claimed)
        score, ev = score_contract_sale(purchase, s, eff)
        if score <= 0 and set(purchase['lines']) & set(full):
            # the item WAS sold here but every unit is already bought back by an earlier case
            over_cands.append(s)
            continue
        if score > 0:
            if s['phcode'] and s['phcode'] in patient_hint:
                score += 20            # ranked UNCAPPED so the hint keeps its margin over rivals
                ev = ev + [_ev('receipt_patient', 20, 'فواتير منتجات البدل يوم السند على كود نفس المريض')]
            scored.append((score, s, eff, ev))
    if not scored:
        if over_cands:
            # nothing left to buy back → bind to the nearest exhausted sale and flag the over-claim
            s = min(over_cands, key=lambda x: abs((purchase['date'] - x['date']).days))
            full = effective_lines(s, partial.get(s['key']))
            over = [{'itemcode': c, 'purchased': str(_d(purchase['lines'][c]['qty'])),
                     'sold': str(_d(full[c]['qty'])), 'already_bought_back': str(_d(claimed.get((s['key'], c), 0)))}
                    for c in purchase['lines'] if c in full]
            score, ev = score_contract_sale(purchase, s, full)
            ev = ev + [_ev('capacity', -40, 'كل الكمية المباعة من هذا الصنف مشتراة بالفعل في حالة سابقة')]
            score = max(D0, min(Decimal('100'), score) - 40)
            return {'sale': s, 'partial_returns': partial.get(s['key'], []), 'void_pairs': [],
                    'score': score, 'conf': C.conf_class(score), 'evidence': ev, 'eff_lines': full,
                    'ambiguous_patients': [], 'over_claim': over}
        return {'sale': None, 'partial_returns': [], 'void_pairs': [], 'score': D0,
                'conf': 'low', 'evidence': [], 'eff_lines': {}, 'ambiguous_patients': [], 'over_claim': []}
    # best score; tie → the sale closest to the purchase date, then latest
    scored.sort(key=lambda t: (-t[0], abs((purchase['date'] - t[1]['date']).days), -t[1]['date'].toordinal()))
    rank, sale, eff, ev = scored[0]
    rivals = sorted({t[1]['phcode'] for t in scored
                     if t[0] >= rank - 5 and t[1]['phcode'] != sale['phcode'] and t[1]['phcode']})
    score = min(Decimal('100'), rank)
    if rivals:
        score = max(D0, score - 25)
        ev = ev + [_ev('ambiguity', -25, 'مرضى آخرون لديهم بيع تعاقد مماثل: ' + '، '.join(rivals))]
    pair_items = set(purchase['lines'])
    void_pairs = [(s, void[s['key']]) for s in sales
                  if s['key'] in void and s['phcode'] == sale['phcode'] and pair_items & set(s['lines'])]
    over = [{'itemcode': c, 'purchased': str(_d(purchase['lines'][c]['qty'])), 'left': str(_d(eff[c]['qty']))}
            for c in purchase['lines'] if c in eff and _d(purchase['lines'][c]['qty']) > _d(eff[c]['qty']) + Decimal('0.0001')]
    return {'sale': sale, 'partial_returns': partial.get(sale['key'], []), 'void_pairs': void_pairs,
            'score': score, 'conf': C.conf_class(score), 'evidence': ev, 'eff_lines': eff,
            'ambiguous_patients': rivals, 'over_claim': over}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. voucher → product receipts
# ═══════════════════════════════════════════════════════════════════════════════

def _minutes(a, b):
    if a is None or b is None:
        return None
    return (a - b).total_seconds() / 60.0


def _in_window(r_time, v_time, before, after):
    m = _minutes(r_time, v_time)          # negative ⇒ receipt BEFORE voucher
    if m is None:
        return True                       # no clock → same-day only (caller pre-filters)
    return -before <= m <= after


def _best_subset(receipts, cap: Decimal, limit: int):
    """Largest Σ ≤ cap (ties → fewer receipts, then closer in time). Brute force, n small."""
    pool = receipts[:limit]
    best, best_key = [], (D0, 0)
    for k in range(1, len(pool) + 1):
        for combo in combinations(pool, k):
            s = sum((_d(r['amount']) for r in combo), D0)
            if s <= cap and (s, -k) > best_key:
                best, best_key = list(combo), (s, -k)
    return best


def select_funding(voucher: dict, receipts: list[dict], patient_phcode: str,
                   tabdeel_pics: set | frozenset = frozenset(), known_keys: set | frozenset = frozenset()) -> dict:
    """voucher: {amount, trans_time}; receipts: [{key, amount, phcode, trans_time}] already
    restricted to same branch + same day + non-contract sales + not claimed elsewhere.

    Returns {receipts, total, product, cash_remainder, excess, excess_kind, score, conf,
             status, evidence, alternatives}.
    """
    v_amt = _d(voucher['amount'])
    v_time = voucher.get('trans_time')
    absorb = max(C.get('ABSORB_ABS'), (v_amt * C.get('ABSORB_PCT')).quantize(CENT))
    ev = []

    # known_keys = receipts THIS case's own product orders became (live workflow) — patient's by
    # construction, whatever PIC the cashier left on them.
    patient_pool = [r for r in receipts
                    if (r['key'] in known_keys
                        or (r.get('phcode') and (r['phcode'] == patient_phcode or r['phcode'] in tabdeel_pics)))
                    and _in_window(r.get('trans_time'), v_time,
                                   C.get('FUND_PATIENT_BEFORE_MIN'), C.get('FUND_PATIENT_AFTER_MIN'))]
    chosen, score, anonymous = [], D0, False
    if patient_pool:
        patient_pool.sort(key=lambda r: abs(_minutes(r.get('trans_time'), v_time) or 0))
        total_all = sum((_d(r['amount']) for r in patient_pool), D0)
        chosen = patient_pool if total_all <= v_amt + absorb else \
            _best_subset(patient_pool, v_amt + absorb, C.get('FUND_MAX_SUBSET'))
        is_tabdeel = all(r['phcode'] != patient_phcode and r['key'] not in known_keys for r in chosen)
        score += 35 if is_tabdeel else 50
        ev.append(_ev('patient', 35 if is_tabdeel else 50,
                      'فواتير على حساب «عميل تبديل»' if is_tabdeel else 'فواتير على كود المريض نفسه'))
        score += 10
        ev.append(_ev('same_day', 10, 'نفس يوم السند ونفس الفرع'))
        score += 20
        ev.append(_ev('time', 20, 'كل الفواتير داخل النافذة الزمنية للسند'))
    else:
        anon_pool = [r for r in receipts
                     if not r.get('phcode')
                     and _in_window(r.get('trans_time'), v_time,
                                    C.get('FUND_ANON_BEFORE_MIN'), C.get('FUND_ANON_AFTER_MIN'))
                     and _d(r['amount']) <= v_amt + absorb]
        # owner rule: exactly ONE anonymous receipt close before the voucher at 80–100 % of it
        auto = [r for r in anon_pool
                if _minutes(r.get('trans_time'), v_time) is not None
                and -C.get('ANON_AUTO_BEFORE_MIN') <= _minutes(r.get('trans_time'), v_time) <= C.get('ANON_AUTO_AFTER_MIN')
                and v_amt * C.get('ANON_AUTO_MIN_RATIO') <= _d(r['amount']) <= v_amt + absorb]
        if len(auto) == 1:
            pick = auto[0]
            m = _minutes(pick.get('trans_time'), v_time)
            total = _d(pick['amount'])
            ev = [_ev('unique_anonymous', 85, f'الفاتورة الوحيدة بدون كود مريض خلال {C.get("ANON_AUTO_BEFORE_MIN")} دقائق قبل السند '
                                              f'(على بعد {abs(m):.0f} دقيقة) وقيمتها {total / v_amt * 100:.0f}% من السند'),
                  _ev('same_day', 10, 'نفس يوم السند ونفس الفرع')]
            excess = max(D0, total - v_amt)
            return {'receipts': [pick], 'total': total, 'product': min(total, v_amt),
                    'cash_remainder': max(D0, v_amt - total), 'excess': excess,
                    'excess_kind': '' if not excess else ('absorbed' if excess <= absorb else 'customer_topup'),
                    'score': Decimal('95'), 'conf': 'high', 'status': 'confirmed', 'anonymous': True,
                    'auto_rule': 'anon_unique', 'evidence': ev}
        if anon_pool:
            anonymous = True
            anon_pool.sort(key=lambda r: (-_d(r['amount']), abs(_minutes(r.get('trans_time'), v_time) or 0)))
            pick = anon_pool[0]
            chosen = [pick]
            m = _minutes(pick.get('trans_time'), v_time)
            score += 10
            ev.append(_ev('same_day', 10, 'نفس يوم السند ونفس الفرع'))
            tp = 25 if (m is not None and abs(m) <= 10) else 15
            score += tp
            ev.append(_ev('time', tp, f'فاتورة بدون كود مريض على بعد {abs(m or 0):.0f} دقيقة من السند'))
            ratio = _d(pick['amount']) / v_amt if v_amt else D0
            ap = 20 if ratio >= Decimal('0.8') else (10 if ratio >= Decimal('0.5') else 0)
            score += ap
            ev.append(_ev('amount', ap, f'قيمة الفاتورة = {ratio * 100:.0f}% من السند'))

    total = sum((_d(r['amount']) for r in chosen), D0)
    if chosen and not anonymous:
        gap = abs(total - v_amt)
        ap = 20 if gap <= absorb else (10 if total < v_amt else 0)
        score += ap
        ev.append(_ev('amount', ap, f'إجمالي الفواتير {total} مقابل السند {v_amt}'))

    product = min(total, v_amt)
    remainder = max(D0, v_amt - total)
    excess = max(D0, total - v_amt)
    excess_kind = '' if not excess else ('absorbed' if excess <= absorb else 'customer_topup')
    score = min(score, Decimal('100'))
    if anonymous:
        score = min(score, C.get('CONF_HIGH') - 1)      # never auto-confirm an anonymous link
    conf = C.conf_class(score) if chosen else 'low'
    return {
        'receipts': chosen, 'total': total, 'product': product, 'cash_remainder': remainder,
        'excess': excess, 'excess_kind': excess_kind, 'score': score, 'conf': conf,
        'status': 'confirmed' if (chosen and conf == 'high') else ('proposed' if chosen else 'none'),
        'anonymous': anonymous, 'evidence': ev,
    }


def applied_deduction_pct(lines: list[dict]) -> Decimal | None:
    """1 − Σ purchase value / Σ public × qty, in %, from purchase lines {qty, public, value}."""
    pub = sum((_d(l['public']) * _d(l['qty']) for l in lines), D0)
    val = sum((_d(l['value']) for l in lines), D0)
    if pub <= 0:
        return None
    return ((Decimal('1') - val / pub) * 100).quantize(CENT)
