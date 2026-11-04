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


def _build(date_from, date_to, fetch):
    seen, docs = set(), []
    for d1, d2 in sybase_gl.month_chunks(date_from, date_to):
        for r in fetch(sybase_gl.sql_cheques(d1, d2)):
            branch, sno = code(r['branchcode']), code(r['cheqsno'])
            if (branch, sno) in seen:
                continue
            seen.add((branch, sno))
            person, fdoc, ptcode = code(r['personcode']), code(r['financialdoccode']), code(r['ptcode'])
            if person == '-170' or (person == '-120' and int(r.get('has_expense') or 0) > 0):
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
            amount = q(r['cheqvalue'])
            attrs = {'financialdoc': fdoc, 'direction': 'receipt' if code(r['cheqtype']) == '10' else 'payment',
                     'bankcode': code(r['bankcode']), 'bank_type': code(r.get('banktype')),
                     'cheqno': code(r['cheqno']), 'due_date': due.isoformat() if due else None,
                     'note': (r.get('chequenote') or '').strip(), 'tf_branchcode': code(r.get('tf_branchcode')),
                     'tf_bankcode': code(r.get('tf_bankcode')), 'tf_cheqsno': code(r.get('tf_cheqsno'))}
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
