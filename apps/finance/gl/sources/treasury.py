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




HQ = sybase_gl.HQ_BRANCH
BOX_TRANSFER, BANK_TRANSFER = sybase_gl.TRANSFER_BOX_PERSON, '-181'
BANK_TYPE_BANK = '1'   # banks.banktype: 0 = cash box, 1 = bank account
_LOOKUP_CHUNK = 500


def _transfer_kinds(rows, fetch) -> dict:
    """(branch, cheqsno) -> (kind, counterpart_branch) for every -180 / -181 voucher.

    -181 box<->bank (Ruling P27, decided from the row alone): the leg whose own box is a bank
    (banktype 1) is 'transfer_bank_mirror' (skipped); the box leg is 'transfer_bank' (posts box vs
    bank(tf_bankcode)); no tf_bankcode -> 'transfer'.
    -180 box<->box (P24/P28/P29): counterpart branch = own tf_branchcode (another branch), else the
    one branch whose leg points back (tf_branchcode / tf_cheqsno) - first in this fetch, then for HQ
    legs by one read-only SELECT with no date bound (``sql_transfer_legs_pointing_at``). HQ on either
    side -> 'transfer_branch'; branch<->branch -> 'transfer_b2b'; an HQ leg still unpaired (or
    ambiguous) -> 'transfer_unpaired'; a branch leg with no counterpart stays 'transfer'. None of
    this depends on the range drafted, so the same voucher always gets the same kind."""
    tf = {(code(r['branchcode']), code(r['cheqsno'])): r for r in rows
          if code(r['personcode']) in (BOX_TRANSFER, BANK_TRANSFER)}

    def pointing(src):
        back = {}
        for r in src:
            if code(r['personcode']) != BOX_TRANSFER:
                continue
            b, tb, ts = code(r['branchcode']), code(r.get('tf_branchcode')), code(r.get('tf_cheqsno'))
            if tb and ts and tb != b:
                back.setdefault((tb, ts), set()).add(b)
        return back

    back = pointing(tf.values())
    own = {k: code(r.get('tf_branchcode')) for k, r in tf.items()}
    unresolved = sorted(sno for (b, sno), r in tf.items()
                        if b == HQ and code(r['personcode']) == BOX_TRANSFER
                        and not (own[(b, sno)] and own[(b, sno)] != b)
                        and len(back.get((b, sno), ())) != 1 and sno.isdigit())
    looked = {}
    for i in range(0, len(unresolved), _LOOKUP_CHUNK):
        part = unresolved[i:i + _LOOKUP_CHUNK]
        wanted = set(part)
        hits = [r for r in fetch(sybase_gl.sql_transfer_legs_pointing_at(part))   # re-checked in Python
                if code(r.get('tf_branchcode')) == HQ and code(r.get('tf_cheqsno')) in wanted]
        for k, v in pointing(hits).items():
            looked.setdefault(k, set()).update(v)

    out = {}
    for (branch, sno), r in tf.items():
        if code(r['personcode']) == BANK_TRANSFER:
            if code(r.get('banktype')) == BANK_TYPE_BANK:
                out[(branch, sno)] = ('transfer_bank_mirror', '')
            elif code(r.get('tf_bankcode')):
                out[(branch, sno)] = ('transfer_bank', '')
            else:
                out[(branch, sno)] = ('transfer', '')
            continue
        counterpart = own[(branch, sno)] if own[(branch, sno)] != branch else ''
        if not counterpart:
            cands = back.get((branch, sno), set())
            if len(cands) != 1 and branch == HQ:
                cands = looked.get((branch, sno), set()) | cands
            counterpart = next(iter(cands)) if len(cands) == 1 else ''
        if counterpart:
            kind = 'transfer_branch' if HQ in (branch, counterpart) else 'transfer_b2b'
            out[(branch, sno)] = (kind, counterpart)
        else:
            out[(branch, sno)] = ('transfer_unpaired' if branch == HQ else 'transfer', '')
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
