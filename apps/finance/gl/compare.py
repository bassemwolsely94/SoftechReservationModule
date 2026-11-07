"""Ledger vs SOFTECH comparison for a month (finance-gl Plan 3, Task 4).

Ledger side: net movement in the month (``movement``) or balance at period end (``balance``) of the check's
accounts/groups over approved + reversed entries, signed by the check's ``sign``; per branch (the line's
branch, else the entry's), or per GL party when ``per_party``. SOFTECH side: ``softech_checks``.
difference = ledger − SOFTECH. A line's explanation survives a recompute; if the difference then moves,
``GLComparisonLine.needs_explanation`` is true again.
"""
import logging
from collections import defaultdict
from contextlib import contextmanager
from decimal import ROUND_HALF_UP, Decimal

from django.db import connection, transaction
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.branches.models import Branch
from apps.finance.models import (GLAccount, GLComparisonLine, GLSoftechCheck, LedgerEntry,
                                 LedgerLine)

from . import softech_checks
from .balances import COUNTED, YEAR_END_CLOSING, account_statement
from .ledger import LedgerError, _audit

logger = logging.getLogger('elrezeiky.finance')

ZERO = Decimal('0.00')
CENT = Decimal('0.01')
SOFTECH_DOWN = 'تعذرت القراءة من سوفتيك، جرّب تاني.'
CHECK_UPDATED = 'gl_softech_check_updated'   # extra.figures_changed: the check's lines no longer say what it asks
REFRESH_LOCK = 7_302_001   # a manual refresh and the nightly job never overlap, across processes


class RefreshBusy(Exception):
    pass


@contextmanager
def refresh_lock():
    """Non-blocking PostgreSQL session lock: ``with refresh_lock() as got``. A dead run's connection releases it.
    Assumes one server session per connection: under transaction pooling (PgBouncer) a session lock would not hold."""
    with connection.cursor() as cur:
        cur.execute('SELECT pg_try_advisory_lock(%s)', [REFRESH_LOCK])
        got = bool(cur.fetchone()[0])
    try:
        yield got
    finally:
        if got:
            with connection.cursor() as cur:
                cur.execute('SELECT pg_advisory_unlock(%s)', [REFRESH_LOCK])


def refresh_running() -> bool:
    """Is a refresh holding the lock? Reads pg_locks, so asking never makes a starting run lose it."""
    with connection.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND granted AND classid = 0 AND objsubid = 1 "
                    'AND objid = %s AND database = (SELECT oid FROM pg_database WHERE datname = current_database())',
                    [REFRESH_LOCK])
        return cur.fetchone() is not None


def refresh(period, *, check_keys=None, user=None) -> list:
    """`compute` under the lock; RefreshBusy when another refresh holds it."""
    with refresh_lock() as got:
        if not got:
            raise RefreshBusy()
        return compute(period, check_keys=check_keys, user=user)


def _ledger_figures(check, period) -> dict:
    """{(branch_id | None, party_code): amount} on the check's sign."""
    accounts = Q(account__code__in=check.account_codes) | Q(account__group__name__in=check.group_names)
    qs = LedgerLine.objects.filter(entry__status__in=COUNTED).filter(accounts)
    if check.kind == 'movement':
        qs = qs.filter(entry__entry_date__gte=period.period_start, entry__entry_date__lte=period.period_end)
        qs = qs.exclude(YEAR_END_CLOSING)
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
    # the one rounding of this side, before the difference: a stored line always sums
    return {key: amount.quantize(CENT, rounding=ROUND_HALF_UP) for key, amount in out.items()}


def compute(period, *, check_keys=None, user=None) -> list:
    checks = GLSoftechCheck.objects.filter(is_active=True)
    if check_keys is not None:
        checks = checks.filter(key__in=check_keys)
    checks = list(checks)
    branch_ids = dict(Branch.objects.values_list('softech_branch_id', 'id'))
    now = timezone.now()
    lines = []
    # SOFTECH first (a sales read takes minutes): the write transaction stays short and holds no lock meanwhile
    softech_side = [_softech_figures(check, period, branch_ids) for check in checks]
    with transaction.atomic():
        for check, softech in zip(checks, softech_side):
            ledger = _ledger_figures(check, period)
            seen = set()
            keys = [k for k in set(ledger) | set(softech)
                    if ledger.get(k, ZERO) != 0 or softech.get(k, ZERO) != 0]
            # a check always leaves a line (zero/zero on the no-branch key), so "computed" is visible
            for key in sorted(keys or [(None, '')], key=lambda k: (k[0] or 0, k[1])):
                led, sof = ledger.get(key, ZERO), softech.get(key, ZERO)
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
    """True when an active check has no line for the period, a check's accounts or activity were edited after the
    oldest computation, or an entry (or its reversal) was approved after it. Movement checks read the month's
    entries; balance checks read every entry up to the period end, so an earlier-dated late entry counts too.
    Only active checks' lines count: a refresh never touches an inactive check's. No active check, nothing to refresh."""
    lines = GLComparisonLine.objects.filter(period=period, softech_check__is_active=True)
    computed = set(lines.values_list('softech_check_id', flat=True))
    active = list(GLSoftechCheck.objects.filter(is_active=True).values_list('id', 'kind'))
    if not active:
        return False
    if any(cid not in computed for cid, _ in active):
        return True
    oldest = lines.order_by('computed_at').values_list('computed_at', flat=True).first()
    if AuditLog.objects.filter(action=CHECK_UPDATED, created_at__gt=oldest, extra__figures_changed=True).exists():
        return True
    changed = Q(approved_at__gt=oldest) | Q(reversals__approved_at__gt=oldest)
    entries = LedgerEntry.objects.filter(status__in=COUNTED, entry_date__lte=period.period_end)
    if not any(kind == 'balance' for _, kind in active):
        entries = entries.filter(entry_date__gte=period.period_start)
    return entries.filter(changed).exists()


def _accounts(check):
    return list(GLAccount.objects.filter(
        Q(code__in=check.account_codes) | Q(group__name__in=check.group_names)).order_by('code')
        .values_list('code', flat=True))


def detail(line_id) -> dict:
    line = GLComparisonLine.objects.select_related('softech_check', 'branch').get(pk=line_id)
    check, period = line.softech_check, line.period
    # a movement check reads the month; a balance check opens with the balance carried into it
    start = period.period_start
    left_out = set()   # as _ledger_figures, so the rows sum to the line
    if check.kind == 'movement':
        left_out = set(LedgerLine.objects.filter(YEAR_END_CLOSING, entry__entry_date__gte=start,
                                                 entry__entry_date__lte=period.period_end)
                       .values_list('entry_id', flat=True))
    ledger = []
    for code in _accounts(check):
        st = account_statement(
            code, start, period.period_end,
            branch_id=None if check.per_party else line.branch_id,
            party_code=line.party_code or None,
            unbranched=not check.per_party and line.branch_id is None)
        if check.kind == 'balance' and st['opening_balance']:
            ob = st['opening_balance']   # what stood on the books before the month; makes the rows sum to the line
            ledger.append({'date': start, 'number': None, 'description': 'رصيد أول الشهر', 'opening': True,
                           'debit': max(ob, ZERO), 'credit': max(-ob, ZERO), 'running_balance': ob,
                           'entry_id': None, 'account': code})
        for r in st['lines']:
            if r['entry_id'] not in left_out:
                ledger.append({**r, 'account': code})
    ledger.sort(key=lambda r: (r['date'], not r.get('opening'), r['number'] or '', r['account']))
    code = None if check.per_party else (line.branch.softech_branch_id if line.branch_id else None)
    try:
        rows = softech_checks.detail(check.source, period, code, line.party_code)
    except Exception:   # the ledger side and the explanation box stay usable
        logger.exception('[GLCompare] SOFTECH detail of line %s failed', line_id)
        return {'ledger': ledger, 'softech': [], 'softech_error': SOFTECH_DOWN}
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
