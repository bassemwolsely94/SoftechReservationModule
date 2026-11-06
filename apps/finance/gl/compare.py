"""Ledger vs SOFTECH comparison for a month (finance-gl Plan 3, Task 4).

Ledger side: net movement in the month (``movement``) or balance at period end (``balance``) of the check's
accounts/groups over approved + reversed entries, signed by the check's ``sign``; per branch (the line's
branch, else the entry's), or per GL party when ``per_party``. SOFTECH side: ``softech_checks``.
difference = ledger − SOFTECH. A line's explanation survives a recompute; if the difference then moves,
``GLComparisonLine.needs_explanation`` is true again.
"""
from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.branches.models import Branch
from apps.finance.models import (GLAccount, GLComparisonLine, GLSoftechCheck, LedgerEntry,
                                 LedgerLine)

from . import softech_checks
from .balances import COUNTED, account_statement
from .ledger import LedgerError, _audit

ZERO = Decimal('0.00')


def _ledger_figures(check, period) -> dict:
    """{(branch_id | None, party_code): amount} on the check's sign."""
    accounts = Q(account__code__in=check.account_codes) | Q(account__group__name__in=check.group_names)
    qs = LedgerLine.objects.filter(entry__status__in=COUNTED).filter(accounts)
    if check.kind == 'movement':
        qs = qs.filter(entry__entry_date__gte=period.period_start, entry__entry_date__lte=period.period_end)
    else:
        qs = qs.filter(entry__entry_date__lte=period.period_end)
    rows = (qs.annotate(br=Coalesce('branch_id', 'entry__branch_id'))
              .values('br', 'party_code').annotate(d=Sum('debit'), c=Sum('credit')))
    out: dict = defaultdict(lambda: ZERO)
    for r in rows:
        net = (r['d'] or ZERO) - (r['c'] or ZERO)
        if check.sign == 'credit':
            net = -net
        key = (None, r['party_code']) if check.per_party else (r['br'], '')
        out[key] += net
    return dict(out)


def _softech_figures(check, period, branch_ids: dict) -> dict:
    """Same keys as the ledger side: SOFTECH branch codes mapped to Branch ids (unknown codes -> None)."""
    out: dict = defaultdict(lambda: ZERO)
    for (code, party), amount in softech_checks.figures(check.source, period).items():
        key = (None, party) if check.per_party else (branch_ids.get(code), '')
        out[key] += amount
    return dict(out)


def compute(period, *, check_keys=None, user=None) -> list:
    checks = GLSoftechCheck.objects.filter(is_active=True)
    if check_keys is not None:
        checks = checks.filter(key__in=check_keys)
    checks = list(checks)
    branch_ids = dict(Branch.objects.values_list('softech_branch_id', 'id'))
    now = timezone.now()
    lines = []
    with transaction.atomic():
        for check in checks:
            ledger = _ledger_figures(check, period)
            softech = _softech_figures(check, period, branch_ids)
            seen = set()
            for key in sorted(set(ledger) | set(softech), key=lambda k: (k[0] or 0, k[1])):
                led, sof = ledger.get(key, ZERO), softech.get(key, ZERO)
                if led == 0 and sof == 0:
                    continue
                seen.add(key)
                line, _ = GLComparisonLine.objects.update_or_create(
                    period=period, softech_check=check, branch_id=key[0], party_code=key[1],
                    defaults={'ledger_amount': led, 'softech_amount': sof, 'difference': led - sof,
                              'computed_at': now})
                lines.append(line)
            # a line whose two sides are now both zero: kept (with its explanation) at zero, else dropped
            for old in GLComparisonLine.objects.filter(period=period, softech_check=check):
                if (old.branch_id, old.party_code) in seen:
                    continue
                if old.explanation:
                    GLComparisonLine.objects.filter(pk=old.pk).update(
                        ledger_amount=ZERO, softech_amount=ZERO, difference=ZERO, computed_at=now)
                else:
                    old.delete()
        _audit('gl_comparison_computed', user=user, obj=period,
               extra={'checks': [c.key for c in checks], 'lines': len(lines)})
    return lines


def explain(line_id, *, user, text) -> GLComparisonLine:
    text = (text or '').strip()
    if not text:
        raise LedgerError('explanation_required')
    with transaction.atomic():
        line = GLComparisonLine.objects.select_for_update().select_related('softech_check').get(pk=line_id)
        old = {'explanation': line.explanation, 'explained_difference': _str(line.explained_difference)}
        line.explanation = text
        line.explained_by = user
        line.explained_at = timezone.now()
        line.explained_difference = line.difference
        line.save(update_fields=['explanation', 'explained_by', 'explained_at', 'explained_difference'])
        _audit('gl_comparison_explained', user=user, obj=line, old_data=old,
               new_data={'explanation': text, 'explained_difference': str(line.difference)},
               extra={'check': line.softech_check.key, 'period_id': line.period_id,
                      'branch_id': line.branch_id, 'party_code': line.party_code})
    return line


def _str(v):
    return None if v is None else str(v)


def is_stale(period) -> bool:
    """True when no lines exist, or an entry dated in the period (or its reversal) was approved after the oldest
    computation of the period's lines."""
    stamps = list(GLComparisonLine.objects.filter(period=period).values_list('computed_at', flat=True))
    if not stamps:
        return True
    oldest = min(stamps)
    return LedgerEntry.objects.filter(
        status__in=COUNTED, entry_date__gte=period.period_start, entry_date__lte=period.period_end,
    ).filter(Q(approved_at__gt=oldest) | Q(reversals__approved_at__gt=oldest)).exists()


def _accounts(check):
    return list(GLAccount.objects.filter(
        Q(code__in=check.account_codes) | Q(group__name__in=check.group_names)).order_by('code')
        .values_list('code', flat=True))


def detail(line_id) -> dict:
    line = GLComparisonLine.objects.select_related('softech_check', 'branch').get(pk=line_id)
    check, period = line.softech_check, line.period
    # a movement check reads the month; a balance check also shows what led to the closing figure
    start = period.period_start
    ledger = []
    for code in _accounts(check):
        st = account_statement(
            code, start, period.period_end,
            branch_id=None if check.per_party else line.branch_id,
            party_code=line.party_code or None,
            unbranched=not check.per_party and line.branch_id is None)
        for r in st['lines']:
            ledger.append({**r, 'account': code})
    ledger.sort(key=lambda r: (r['date'], r['number'] or '', r['account']))
    code = None if check.per_party else (line.branch.softech_branch_id if line.branch_id else None)
    rows = softech_checks.detail(check.source, period, code, line.party_code)
    out = {'ledger': ledger, 'softech': rows}
    if check.kind == 'movement':
        days: dict = defaultdict(lambda: {'ledger': ZERO, 'softech': ZERO})
        for r in ledger:
            net = r['debit'] - r['credit']
            days[r['date']]['ledger'] += -net if check.sign == 'credit' else net
        for r in rows:
            days[r['date']]['softech'] += r['amount']
        out['by_day'] = [{'date': d, **v, 'difference': v['ledger'] - v['softech']}
                         for d, v in sorted(days.items())]
    return out
