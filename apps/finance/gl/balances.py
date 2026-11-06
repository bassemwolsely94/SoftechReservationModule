"""Trial balance and account statement over the ledger (finance-gl Task 6).

Counted statuses are approved + reversed: a reversed original and its approved mirror both
count and net to zero.  Drafts never count.

Branch filter: LedgerLine.branch is authoritative; only when the line has no branch do we fall
back to the entry header's branch.
"""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Literal

from django.db.models import Q, Sum

from apps.finance.models import GLAccount, LedgerLine

ZERO = Decimal('0.00')
COUNTED = ('approved', 'reversed')
# lines of a year's closing entry and of its reversal on a reopen. The trial balance counts them (a P&L account opens
# next year at 0); a statement or comparison of movement leaves them out, or the year would read as nil.
YEAR_END_CLOSING = Q(entry__source_type='year_end') | Q(entry__reverses__source_type='year_end')


def _base(branch_id=None, party_code=None, unbranched=False):
    qs = LedgerLine.objects.filter(entry__status__in=COUNTED)
    if unbranched:   # lines with no branch of their own and none on the entry
        qs = qs.filter(branch__isnull=True, entry__branch__isnull=True)
    elif branch_id is not None:
        qs = qs.filter(Q(branch_id=branch_id) |
                       Q(branch__isnull=True, entry__branch_id=branch_id))
    if party_code:
        qs = qs.filter(party_code=party_code)
    return qs


def _sides(net: Decimal) -> tuple[Decimal, Decimal]:
    return (net, ZERO) if net > 0 else (ZERO, -net)


def _row(code, name, group, open_net, pd, pc):
    close_net = open_net + pd - pc
    od, oc = _sides(open_net)
    cd, cc = _sides(close_net)
    return {'code': code, 'name': name, 'group': group,
            'opening_debit': od, 'opening_credit': oc,
            'period_debit': pd, 'period_credit': pc,
            'closing_debit': cd, 'closing_credit': cc}


def trial_balance(date_from: datetime.date, date_to: datetime.date, *,
                  branch_id: int | None = None,
                  by: Literal['account', 'group'] = 'account') -> list[dict]:
    before = Q(entry__entry_date__lt=date_from)
    within = Q(entry__entry_date__gte=date_from, entry__entry_date__lte=date_to)
    data = (_base(branch_id)
            .filter(entry__entry_date__lte=date_to)
            .values('account__code', 'account__name', 'account__group_id',
                    'account__group__name', 'account__group__order')
            .annotate(od=Sum('debit', filter=before), oc=Sum('credit', filter=before),
                      pd=Sum('debit', filter=within), pc=Sum('credit', filter=within)))
    # (sort_key, key, code, name, group_name) -> [open_net, pd, pc]
    acc: dict[tuple, list[Decimal]] = {}
    for r in data:
        open_net = (r['od'] or ZERO) - (r['oc'] or ZERO)
        pd, pc = r['pd'] or ZERO, r['pc'] or ZERO
        if open_net == 0 and pd == 0 and pc == 0:
            continue
        if by == 'group':
            gid = r['account__group_id']
            key = (r['account__group__order'], gid, str(gid), r['account__group__name'],
                   r['account__group__name'])
        else:
            key = (0, r['account__code'], r['account__code'], r['account__name'],
                   r['account__group__name'])
        slot = acc.setdefault(key, [ZERO, ZERO, ZERO])
        slot[0] += open_net
        slot[1] += pd
        slot[2] += pc

    rows = [_row(k[2], k[3], k[4], *v) for k, v in sorted(acc.items(), key=lambda i: i[0][:2])]
    total = _row(None, 'الإجمالي', None, ZERO, ZERO, ZERO)
    for col in ('opening_debit', 'opening_credit', 'period_debit', 'period_credit',
                'closing_debit', 'closing_credit'):
        total[col] = sum((r[col] for r in rows), ZERO)
    total['is_total'] = True
    return rows + [total]


def account_statement(code: str, date_from: datetime.date, date_to: datetime.date, *,
                      branch_id: int | None = None, party_code: str | None = None,
                      unbranched: bool = False) -> dict:
    """Debit-minus-credit running balance for one account (raises GLAccount.DoesNotExist)."""
    account = GLAccount.objects.get(code=code)
    qs = _base(branch_id, party_code, unbranched).filter(account=account)
    opening = qs.filter(entry__entry_date__lt=date_from).aggregate(d=Sum('debit'), c=Sum('credit'))
    balance = (opening['d'] or ZERO) - (opening['c'] or ZERO)
    opening_balance = balance
    lines = []
    for ln in (qs.filter(entry__entry_date__gte=date_from, entry__entry_date__lte=date_to)
                 .select_related('entry')
                 .order_by('entry__entry_date', 'entry__number', 'entry_id', 'line_no')):
        balance += ln.debit - ln.credit
        lines.append({'date': ln.entry.entry_date, 'number': ln.entry.number,
                      'description': ln.description or ln.entry.description,
                      'debit': ln.debit, 'credit': ln.credit,
                      'running_balance': balance, 'entry_id': ln.entry_id})
    return {'opening_balance': opening_balance, 'lines': lines, 'closing_balance': balance}
