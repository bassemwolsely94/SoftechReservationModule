"""Treasury readers from SOFTECH ``cheques``: supplier_payments, cheque_maturity, customer_collections,
treasury_other. One fetch per month serves all four types (memoised per fetch+range, Ruling P3)."""
from apps.finance.queries import sybase_gl

from . import READERS, SourceDoc
from .sales import code, q, to_date

OTHER_KINDS = {'30': 'employee', '60': 'partner', '70': 'asset_supplier', '80': 'sister_company'}
_CACHE: list = []   # [(fetch, d1, d2, docs)], newest last; strong refs so ids are never reused


def _kind_other(ptcode: str, personcode: str) -> str:
    if personcode in ('-180', '-181'):
        return 'transfer'
    if personcode == '-120':
        return 'expense_unlinked'
    return OTHER_KINDS.get(ptcode, 'other')




_hq = sybase_gl._hq   # HQ's branch code at call time
BOX_TRANSFER, BANK_TRANSFER = sybase_gl.TRANSFER_BOX_PERSON, sybase_gl.TRANSFER_BANK_PERSON
BANK_TYPE_BOX, BANK_TYPE_BANK = '0', '1'   # banks.banktype: 0 = cash box, 1 = bank account
PAIR_DAYS = sybase_gl.TRANSFER_PAIR_DAYS
_LOOKUP_CHUNK = 200


def _day(r):
    return to_date(r['cheqdate']) if r.get('cheqdate') else None


def _near(a, b) -> bool:
    return a is not None and b is not None and abs((a - b).days) <= PAIR_DAYS


def _chunks(items):
    for i in range(0, len(items), _LOOKUP_CHUNK):
        yield items[i:i + _LOOKUP_CHUNK]


def _transfer_kinds(rows, fetch) -> dict:
    """(branch, cheqsno) -> (kind, counterpart_branch) for every -180 / -181 voucher.

    The other leg of a transfer counts only when its cheqdate is within PAIR_DAYS of this leg's
    (Ruling P30: cheqsno repeats across years). It is looked for in this fetch first, then by one
    read-only SELECT per kind of lookup, with no range bound - so the kind never depends on the
    range drafted.
    -181 box<->bank (P27/P30/P31), by BOTH banktypes (own `banktype` and `tf_type` of tf_bankcode):
    box(0) -> bank(1) = 'transfer_bank' (posts box vs bank(tf_bankcode), also alone); bank(1) -> box(0)
    = 'transfer_bank_mirror' (skipped) only when its box-side partner exists (same branch, cheqsno =
    its tf_cheqsno, bankcode = its tf_bankcode, tf_bankcode = its bankcode, banktype 0); anything else - no partner,
    box<->box, bank<->bank, unknown tf type - is 'transfer_unpaired' (exception, never 0 or 2 posts).
    -180 box<->box (P24/P28/P29): counterpart branch = own tf_branchcode (another branch), else the
    one branch whose leg points back (tf_branchcode / tf_cheqsno) - for an HQ leg also by
    ``sql_transfer_legs_pointing_at``. HQ on either side -> 'transfer_branch'; branch<->branch ->
    'transfer_b2b'; an HQ leg still unpaired (or ambiguous) -> 'transfer_unpaired'; a branch leg
    with no counterpart stays 'transfer'."""
    tf = {(code(r['branchcode']), code(r['cheqsno'])): r for r in rows
          if code(r['personcode']) in (BOX_TRANSFER, BANK_TRANSFER)}

    def pointing(src):   # (tf_branchcode, tf_cheqsno) -> [(branch, date)] for -180 legs
        back = {}
        for r in src:
            if code(r['personcode']) != BOX_TRANSFER:
                continue
            b, tb, ts = code(r['branchcode']), code(r.get('tf_branchcode')), code(r.get('tf_cheqsno'))
            if tb and ts and tb != b:
                back.setdefault((tb, ts), []).append((b, _day(r)))
        return back

    def branches_near(back, key, day):
        return {b for b, d in back.get(key, ()) if _near(d, day)}

    def leg(r):   # the bank-side row's pointer at its box partner (live SOFTECH, fix round 5)
        return (code(r['branchcode']), code(r.get('tf_cheqsno')), code(r.get('tf_bankcode')),
                code(r['bankcode']), _day(r))

    def box_partner(src, branch, tf_sno, tf_bank, bank, day):   # P30 (b) / P31
        """The bank-side row points at its box leg: partner.cheqsno = its tf_cheqsno, partner.bankcode =
        its tf_bankcode (a box, banktype 0), partner.tf_bankcode = its bankcode, same branch, near."""
        return bool(tf_sno) and any(
            code(p['personcode']) == BANK_TRANSFER and code(p['branchcode']) == branch
            and code(p.get('banktype')) == BANK_TYPE_BOX and code(p['cheqsno']) == tf_sno
            and code(p['bankcode']) == tf_bank and code(p.get('tf_bankcode')) == bank
            and _near(_day(p), day) for p in src)

    back = pointing(tf.values())
    own = {k: code(r.get('tf_branchcode')) for k, r in tf.items()}

    # P28/P30 (a): HQ -180 legs not paired in the fetch -> one bounded SELECT
    hq_open = sorted((sno, _day(r)) for (b, sno), r in tf.items()
                     if b == _hq() and code(r['personcode']) == BOX_TRANSFER and _day(r)
                     and not (own[(b, sno)] and own[(b, sno)] != b)
                     and len(branches_near(back, (b, sno), _day(r))) != 1 and sno.isdigit())
    looked = {}
    for part in _chunks(hq_open):
        hits = [h for h in fetch(sybase_gl.sql_transfer_legs_pointing_at(part))   # re-checked below
                if code(h.get('tf_branchcode')) == _hq()]
        for k, v in pointing(hits).items():
            looked.setdefault(k, []).extend(v)

    # P30 (b): bank-side -181 rows whose box leg is not in the fetch -> one bounded SELECT
    def types(r):
        return code(r.get('banktype')), code(r.get('tf_type'))

    def is_bank_side(r):   # bank(1) leg pointing at a box(0)
        return code(r['personcode']) == BANK_TRANSFER and types(r) == (BANK_TYPE_BANK, BANK_TYPE_BOX)

    bank_open = sorted(leg(r) for r in tf.values()
                       if is_bank_side(r) and _day(r) and not box_partner(tf.values(), *leg(r))
                       and all(x.isdigit() for x in leg(r)[:4]))
    partners = []
    for part in _chunks(bank_open):
        partners.extend(fetch(sybase_gl.sql_bank_transfer_partners(part)))   # re-checked below

    out = {}
    for (branch, sno), r in tf.items():
        day = _day(r)
        if code(r['personcode']) == BANK_TRANSFER:
            if is_bank_side(r):
                paired = box_partner(list(tf.values()) + partners, *leg(r))
                out[(branch, sno)] = ('transfer_bank_mirror' if paired else 'transfer_unpaired', '')
            elif types(r) == (BANK_TYPE_BOX, BANK_TYPE_BANK) and code(r.get('tf_bankcode')):
                out[(branch, sno)] = ('transfer_bank', '')
            else:   # box<->box, bank<->bank or unknown tf type (Ruling P31)
                out[(branch, sno)] = ('transfer_unpaired', '')
            continue
        counterpart = own[(branch, sno)] if own[(branch, sno)] != branch else ''
        if not counterpart:
            cands = branches_near(back, (branch, sno), day)
            if len(cands) != 1 and branch == _hq():
                cands = branches_near(looked, (branch, sno), day) | cands
            counterpart = next(iter(cands)) if len(cands) == 1 else ''
        if counterpart:
            kind = 'transfer_branch' if _hq() in (branch, counterpart) else 'transfer_b2b'
            out[(branch, sno)] = (kind, counterpart)
        else:
            out[(branch, sno)] = ('transfer_unpaired' if branch == _hq() else 'transfer', '')
    return out



def _build(date_from, date_to, fetch):
    seen, rows = set(), []
    for d1, d2 in sybase_gl.month_chunks(date_from, date_to):
        for r in fetch(sybase_gl.sql_cheques(d1, d2)):
            branch, sno = code(r['branchcode']), code(r['cheqsno'])
            if (branch, sno) in seen:
                continue
            seen.add((branch, sno))
            rows.append(r)
    transfers = _transfer_kinds(rows, fetch)
    docs = []
    for r in rows:
        branch, sno = code(r['branchcode']), code(r['cheqsno'])
        person, fdoc, ptcode = code(r['personcode']), code(r['financialdoccode']), code(r['ptcode'])
        # -170 = POS takings (in sales_tenders); a -120 voucher linked to a dailyexpenses row
        # (Ruling P20, predicate in sql_cheques) is posted by the expenses reader
        if person == '-170' or (person == sybase_gl.EXPENSE_VOUCHER_PERSON
                                and int(r.get('has_expense') or 0) > 0):
            continue
        due = to_date(r['cheqdate']) if r.get('cheqdate') else None
        reg = to_date(r['cheqregisterdate']) if r.get('cheqregisterdate') else None
        cheque = fdoc == '20'
        doc_date = (reg or due) if cheque else due
        if ptcode == '20':
            stype, kind = 'supplier_payments', ''
        elif ptcode == '10':
            stype, kind = 'customer_collections', ''
        else:
            stype, kind = 'treasury_other', _kind_other(ptcode, person)
        transfer = kind == 'transfer'
        if transfer:
            kind, counterpart = transfers.get((branch, sno), ('transfer', ''))
        amount = q(r['cheqvalue'])
        attrs = {'financialdoc': fdoc, 'direction': 'receipt' if code(r['cheqtype']) == '10' else 'payment',
                 'bankcode': code(r['bankcode']), 'bank_type': code(r.get('banktype')),
                 'cheqno': code(r['cheqno']), 'due_date': due.isoformat() if due else None,
                 'note': (r.get('chequenote') or '').strip(), 'tf_branchcode': code(r.get('tf_branchcode')),
                 'tf_bankcode': code(r.get('tf_bankcode')), 'tf_cheqsno': code(r.get('tf_cheqsno'))}
        if transfer:   # transfer vouchers only, so other cheques keep their content hash
            attrs['counterpart_branch'] = counterpart
        if doc_date and date_from <= doc_date <= date_to:
            docs.append(SourceDoc(stype, f'chq:{branch}:{sno}', doc_date, branch, kind, person,
                                  {'amount': amount}, attrs))
        if cheque and due and date_from <= due <= date_to:
            docs.append(SourceDoc('cheque_maturity', f'chqdue:{branch}:{sno}', due, branch, '', person,
                                  {'amount': amount}, attrs))
    docs.sort(key=lambda d: (d.doc_date, d.source_key))
    return docs


def read_cheques(date_from, date_to, fetch):
    for f, a, b, docs in _CACHE:
        if f is fetch and a == date_from and b == date_to:
            return iter(docs)
    docs = _build(date_from, date_to, fetch)
    _CACHE.append((fetch, date_from, date_to, docs))
    del _CACHE[:-4]
    return iter(docs)


def _reader(source_type):
    def reader(date_from, date_to, fetch):
        return (d for d in read_cheques(date_from, date_to, fetch) if d.source_type == source_type)
    return reader


for _t in ('supplier_payments', 'cheque_maturity', 'customer_collections', 'treasury_other'):
    READERS[_t] = _reader(_t)
