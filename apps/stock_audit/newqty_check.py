"""
apps/stock_audit/newqty_check.py

P-30 step 0 (docs/product-review/06_SPEC_P-30_measured_availability.md): what does the stock ledger's `newqty`
("stock after this line") really hold? Nothing in P-30 is built on it until this passes. Read-only: PostgreSQL
mirror (StockLedgerLine, ItemStock) only — no SOFTECH query, no database write.

  1 store_mix     which stores a branch's lines carry, and the share outside its selling store
  2 chain_check   for consecutive lines of one (store, item): previous newqty ± transqty (± bonus) = this newqty;
                  the in/out direction per doccode is inferred from the data, for the owner to confirm
  3 end_state     last newqty vs ItemStock.quantity_on_hand, where no line came after that stock sync
  4 units_signs   strips (fractional newqty) and negatives
  5 pick_samples  20 cases (10 at zero or below, 10 above) for a store specialist to check on the SOFTECH item card
Pass rule (proposed, owner confirms): ≥ 19 of 20 sheet cases match AND checks 2 and 3 are each ≥ 95 % consistent.
"""
import datetime as dt
from collections import Counter, defaultdict
from decimal import Decimal

ZERO = Decimal('0')
EPS = Decimal('0.00001')
PASS_PCT = Decimal('95')
PASS_SAMPLES = 19
SAMPLE_SIZE = 20


def _pct(part, whole):
    return (Decimal(part) * 100 / whole).quantize(Decimal('0.1')) if whole else None


def load_lines(branch_code, since):
    """The branch's ledger lines since `since`, as dicts, in chain order (store, item, time, document)."""
    from apps.stock_audit.models import StockLedgerLine
    rows = (StockLedgerLine.objects.filter(branchcode=branch_code, docdate__gte=since)
            .values('id', 'storecode', 'itemcode', 'item__name', 'doccode', 'docnumber', 'docdate', 'trans_time',
                    'transqty', 'bonusqty', 'newqty'))
    key = lambda r: (r['storecode'], r['itemcode'], r['trans_time'] or dt.datetime.combine(       # noqa: E731
        r['docdate'], dt.time.max, tzinfo=dt.timezone.utc), r['docnumber'], r['id'])
    return sorted(rows, key=key)


def store_mix(lines, selling_store):
    stores = Counter(r['storecode'] for r in lines)
    other = sum(n for s, n in stores.items() if s != selling_store)
    return {'selling_store': selling_store, 'stores': dict(stores), 'other_share_pct': _pct(other, len(lines))}


def _direction(delta, qty, bonus):
    for label, value in (('in', qty), ('out', -qty), ('in_bonus', qty + bonus), ('out_bonus', -(qty + bonus))):
        if label.endswith('bonus') and not bonus:
            continue
        if abs(delta - value) <= EPS:
            return label
    return 'break'


def chain_check(lines, keep_breaks=50):
    by_doc = defaultdict(Counter)
    pairs = consistent = 0
    breaks = []
    prev = None
    for r in lines:
        if prev is not None and (prev['storecode'], prev['itemcode']) == (r['storecode'], r['itemcode']):
            pairs += 1
            delta = r['newqty'] - prev['newqty']
            d = _direction(delta, r['transqty'], r['bonusqty'] or ZERO)
            by_doc[r['doccode']][d] += 1
            if d == 'break':
                if len(breaks) < keep_breaks:
                    breaks.append({'itemcode': r['itemcode'], 'name': r['item__name'], 'storecode': r['storecode'],
                                   'doccode': r['doccode'], 'docnumber': r['docnumber'], 'docdate': r['docdate'],
                                   'previous_newqty': prev['newqty'], 'transqty': r['transqty'],
                                   'bonusqty': r['bonusqty'], 'newqty': r['newqty'], 'difference': delta})
            else:
                consistent += 1
        prev = r
    return {'pairs': pairs, 'consistent': consistent, 'pct': _pct(consistent, pairs),
            'by_doccode': {dc: dict(c) for dc, c in sorted(by_doc.items())}, 'breaks': breaks}


def end_state(branch_code, lines, keep=50):
    """Last newqty per (store, item) vs ItemStock, only where the stock sync came after that line."""
    from apps.catalog.models import ItemStock
    last = {}
    for r in lines:
        last[(r['storecode'], r['itemcode'])] = r
    compared = equal = 0
    mismatches = []
    for st in (ItemStock.objects.filter(branch__softech_branch_id=branch_code)
               .values('softech_store_code', 'item__softech_id', 'quantity_on_hand', 'last_synced')):
        r = last.get((st['softech_store_code'], st['item__softech_id']))
        if r is None or r['trans_time'] is None or st['last_synced'] is None or st['last_synced'] <= r['trans_time']:
            continue
        compared += 1
        if abs(r['newqty'] - st['quantity_on_hand']) <= Decimal('0.001'):
            equal += 1
        elif len(mismatches) < keep:
            mismatches.append({'itemcode': r['itemcode'], 'name': r['item__name'], 'storecode': r['storecode'],
                               'ledger_newqty': r['newqty'], 'item_stock': st['quantity_on_hand'],
                               'line_time': r['trans_time'], 'stock_synced': st['last_synced']})
    return {'compared': compared, 'equal': equal, 'pct': _pct(equal, compared), 'mismatches': mismatches}


def units_signs(lines):
    return {'lines': len(lines),
            'fractional': sum(1 for r in lines if r['newqty'] != r['newqty'].to_integral_value()),
            'negative': sum(1 for r in lines if r['newqty'] < 0),
            'zero_or_less': sum(1 for r in lines if r['newqty'] <= 0)}


def pick_samples(lines, n=SAMPLE_SIZE):
    """n cases, half at zero or below and half above, spread evenly over the window, one per item where possible.
    Deterministic: the same lines give the same sheet."""
    def spread(group, k):
        seen, uniq = set(), []
        for r in sorted(group, key=lambda r: (r['trans_time'] or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
                                              r['docnumber'], r['id'])):
            uniq.append(r)
        firsts = [r for r in uniq if not (r['itemcode'] in seen or seen.add(r['itemcode']))]
        pool = firsts if len(firsts) >= k else uniq
        if not pool:
            return []
        step = len(pool) / k
        return [pool[min(int(i * step), len(pool) - 1)] for i in range(min(k, len(pool)))]
    half = n // 2
    picked = spread([r for r in lines if r['newqty'] <= 0], half) + spread([r for r in lines if r['newqty'] > 0],
                                                                           n - half)
    return [{'itemcode': r['itemcode'], 'name': r['item__name'], 'storecode': r['storecode'], 'doccode': r['doccode'],
             'docnumber': r['docnumber'], 'docdate': r['docdate'], 'trans_time': r['trans_time'],
             'transqty': r['transqty'], 'newqty': r['newqty']} for r in picked]


def score_samples(rows):
    """rows: {'newqty', 'seen'} — 'seen' is what the specialist read on the SOFTECH item card (None = not filled)."""
    filled = [r for r in rows if r.get('seen') is not None]
    return {'filled': len(filled),
            'matches': sum(1 for r in filled if abs(Decimal(r['seen']) - Decimal(r['newqty'])) <= Decimal('0.001'))}


def verdict(chain_pct, end_pct, samples):
    checks = {'chain': chain_pct is not None and chain_pct >= PASS_PCT,
              'end_state': end_pct is not None and end_pct >= PASS_PCT}
    if samples is None or samples['filled'] < SAMPLE_SIZE:
        result = 'fail' if not all(checks.values()) else 'awaiting_sheet'
    else:
        checks['samples'] = samples['matches'] >= PASS_SAMPLES
        result = 'pass' if all(checks.values()) else 'fail'
    return {'result': result, 'checks': checks, 'rule': f'≥{PASS_SAMPLES}/{SAMPLE_SIZE} cases · checks 2–3 ≥{PASS_PCT}%'}


def run(branch_code, since):
    from apps.branches.models import Branch
    from apps.purchasing.rate_writer import resolve_store
    branch = Branch.objects.filter(softech_branch_id=branch_code).first()
    selling = resolve_store(branch) if branch else branch_code
    lines = load_lines(branch_code, since)
    chain = chain_check(lines)
    end = end_state(branch_code, lines)
    return {'branch': branch_code, 'since': since, 'store_mix': store_mix(lines, selling), 'chain': chain,
            'end_state': end, 'units': units_signs(lines), 'samples': pick_samples(lines),
            'verdict': verdict(chain['pct'], end['pct'], None)}
