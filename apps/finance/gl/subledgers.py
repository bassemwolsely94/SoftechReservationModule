"""Sub-ledgers over the GL (finance-gl Plan 3, Task 5): suppliers, creditors, notes payable,
customers, employees and partners, each tied back to the control accounts.

Counted statuses are the trial balance's (approved + reversed). Every figure is one grouped
aggregate query, never a loop over the year's lines. Party codes are only unique per party type,
so names and links are looked up with the type of the account's party.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from django.db.models import Max, Q, Sum

from apps.finance.models import GLAccountGroup, LedgerLine

from . import plan2_adapter
from .balances import COUNTED
from .names import normalize_ar

ZERO = Decimal('0.00')
NO_PARTY = 'بدون طرف'
NO_DUE_DATE = 'بدون تاريخ استحقاق'
NO_LINK = 'لا يوجد ربط بسوفتيك'
OPENING_AFTER = 'رصيد افتتاحي بعد التاريخ'
TOTAL_LABEL = 'الإجمالي'

# 2354 is finance's cross-book clearing account, never a creditor: creditors is 2351 only.
SUBLEDGERS = {
    'suppliers': {'accounts': ['2341'], 'by': 'party'},
    'creditors': {'accounts': ['2351'], 'by': 'party'},
    'notes_payable': {'accounts': ['2343'], 'by': 'due_month'},
    'customers': {'accounts': ['1341'], 'by': 'party'},
    'employees': {'accounts': ['1351'], 'by': 'party'},
    'partners': {'groups': ['جارى الشركاء'], 'by': 'account'},
}
# the side a balance is shown on, and the GLParty type its codes belong to
_NATURE = {'suppliers': 'credit', 'creditors': 'credit', 'customers': 'debit', 'employees': 'debit'}
_PARTY_TYPE = {'suppliers': 'supplier', 'creditors': 'supplier', 'notes_payable': 'supplier',
               'customers': 'customer', 'employees': 'employee'}


def _row(key, name, sign, od, oc, pd, pc, link=None):
    opening, closing = sign * (od - oc), sign * (od - oc + pd - pc)
    return {'key': key, 'name': name, 'opening': opening or ZERO, 'debit': pd, 'credit': pc,
            'closing': closing or ZERO, 'link': link}   # `or ZERO`: no negative zero


def _totals(rows):
    out = {'key': None, 'name': TOTAL_LABEL, 'link': None, 'is_total': True}
    for col in ('opening', 'debit', 'credit', 'closing'):
        out[col] = sum((r[col] for r in rows), ZERO)
    return out


def _lines(kind, date_to):
    spec = SUBLEDGERS[kind]
    qs = LedgerLine.objects.filter(entry__status__in=COUNTED, entry__entry_date__lte=date_to)
    if 'accounts' in spec:
        return qs.filter(account__code__in=spec['accounts'])
    wanted = {normalize_ar(g) for g in spec['groups']}
    ids = [g.pk for g in GLAccountGroup.objects.all() if normalize_ar(g.name) in wanted]
    return qs.filter(account__group_id__in=ids)


def _link(kind, code, personcodes):
    pc = personcodes.get(code)
    if not pc:
        return None   # only a confirmed party links
    if kind == 'suppliers':
        return {'to': '/reconciliation', 'party': pc}
    if kind == 'customers':
        return {'to': '/finance/receivables', 'personcode': pc}
    return None


def subledger(kind: str, date_from: datetime.date, date_to: datetime.date) -> dict:
    """Rows `{key, name, opening, debit, credit, closing, link}` in the account's nature, a totals
    row (which includes the unassigned row) and `unassigned`: the lines with a blank party_code,
    kept apart so the party rows never hide them (None when there are none, or by account)."""
    spec = SUBLEDGERS[kind]   # KeyError on an unknown kind
    if spec['by'] == 'due_month':
        return _notes_payable(date_to)
    qb = Q(entry__entry_date__lt=date_from)
    qw = Q(entry__entry_date__gte=date_from, entry__entry_date__lte=date_to)

    if spec['by'] == 'account':
        data = (_lines(kind, date_to)
                .values('account__code', 'account__name', 'account__nature')
                .annotate(od=Sum('debit', filter=qb), oc=Sum('credit', filter=qb),
                          pd=Sum('debit', filter=qw), pc=Sum('credit', filter=qw))
                .order_by('account__code'))
        rows = []
        for r in data:
            od, oc, pd, pc = (r['od'] or ZERO, r['oc'] or ZERO, r['pd'] or ZERO, r['pc'] or ZERO)
            if od == oc and pd == 0 and pc == 0:
                continue
            sign = 1 if r['account__nature'] == 'debit' else -1
            rows.append(_row(r['account__code'], r['account__name'], sign, od, oc, pd, pc))
        return {'kind': kind, 'rows': rows, 'unassigned': None, 'totals': _totals(rows)}

    sign = 1 if _NATURE[kind] == 'debit' else -1
    data = (_lines(kind, date_to).values('party_code')
            .annotate(od=Sum('debit', filter=qb), oc=Sum('credit', filter=qb),
                      pd=Sum('debit', filter=qw), pc=Sum('credit', filter=qw)))
    pending, unassigned = [], None
    for r in data:
        od, oc, pd, pc = (r['od'] or ZERO, r['oc'] or ZERO, r['pd'] or ZERO, r['pc'] or ZERO)
        if od == oc and pd == 0 and pc == 0:
            continue   # nothing open and nothing moved
        if not r['party_code']:
            unassigned = _row('', NO_PARTY, sign, od, oc, pd, pc)
        else:
            pending.append((r['party_code'], od, oc, pd, pc))
    codes = [p[0] for p in pending]
    ptype = _PARTY_TYPE[kind]
    names = plan2_adapter.party_names(codes, ptype)
    personcodes = plan2_adapter.party_personcodes(codes, ptype)
    rows = [_row(c, names.get(c, c), sign, od, oc, pd, pc, _link(kind, c, personcodes))
            for c, od, oc, pd, pc in pending]
    rows.sort(key=lambda r: (r['name'], r['key']))
    return {'kind': kind, 'rows': rows, 'unassigned': unassigned,
            'totals': _totals(rows + ([unassigned] if unassigned else []))}


def _notes_payable(date_to):
    """Open cheques (credit - debit != 0 at date_to) grouped by the month of their due date."""
    data = (_lines('notes_payable', date_to).values('cheque_no')
            .annotate(c=Sum('credit'), d=Sum('debit'), due=Max('due_date'), party=Max('party_code'))
            .order_by('cheque_no'))
    open_ = [r for r in data if (r['c'] or ZERO) - (r['d'] or ZERO) != 0]
    names = plan2_adapter.party_names({r['party'] for r in open_ if r['party']}, 'supplier')
    months: dict[str, dict] = {}
    for r in open_:
        due = r['due']
        key = due.strftime('%Y-%m') if due else ''
        m = months.setdefault(key, {'key': key, 'name': key or NO_DUE_DATE, 'opening': ZERO,
                                    'debit': ZERO, 'credit': ZERO, 'closing': ZERO,
                                    'link': None, 'cheques': []})
        amount = (r['c'] or ZERO) - (r['d'] or ZERO)
        m['cheques'].append({'cheque_no': r['cheque_no'], 'party': names.get(r['party'], r['party']),
                             'due_date': due, 'amount': amount})
        m['closing'] += amount
        m['credit'] += amount if amount > 0 else ZERO
        m['debit'] += -amount if amount < 0 else ZERO
    rows = [months[k] for k in sorted(months, key=lambda k: (k == '', k))]   # undated month last
    return {'kind': 'notes_payable', 'rows': rows, 'unassigned': None, 'totals': _totals(rows)}


def supplier_vs_ap(as_of: datetime.date) -> list[dict]:
    """Per supplier party: the GL balance on 2341 (credit nature, up to and including `as_of`)
    against the A/P reconciliation balance. Rows: `{party_code, name, gl_balance, ap_balance,
    difference, reason}`; `ap_balance`/`difference` are None with the reason when there is no
    figure to compare. Covers every party with a 2341 balance plus every party linked to a
    reconciliation party (an A/P balance with nothing in the ledger is a difference too)."""
    from apps.finance.recon_balances import ap_balance_as_of

    gl = {r['party_code']: (r['c'] or ZERO) - (r['d'] or ZERO)
          for r in (LedgerLine.objects
                    .filter(entry__status__in=COUNTED, entry__entry_date__lte=as_of,
                            account__code__in=SUBLEDGERS['suppliers']['accounts'])
                    .exclude(party_code='').values('party_code')
                    .annotate(c=Sum('credit'), d=Sum('debit')))}
    codes = {c for c, v in gl.items() if v != 0} | set(plan2_adapter.party_codes_with_recon('supplier'))
    recon = plan2_adapter.party_recon_parties(codes, 'supplier')
    names = plan2_adapter.party_names(codes, 'supplier')
    out = []
    for code in codes:
        gl_bal = gl.get(code, ZERO)
        rp = recon.get(code)
        ap, reason = None, ''
        if rp is None:
            reason = NO_LINK
        else:
            ap = ap_balance_as_of(rp, as_of)
            if ap is None:
                reason = OPENING_AFTER
        if rp is not None and ap is not None and gl_bal == 0 and ap == 0:
            continue
        out.append({'party_code': code, 'name': names.get(code, code), 'gl_balance': gl_bal,
                    'ap_balance': ap, 'difference': None if ap is None else gl_bal - ap,
                    'reason': reason})
    out.sort(key=lambda r: (r['name'], r['party_code']))
    return out
