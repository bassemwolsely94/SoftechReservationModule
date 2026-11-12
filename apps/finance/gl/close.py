"""Month close on the ledger: checklist, SOFTECH closing stock, auto-reversal, reopen (finance-gl Plan 3, Task 6).

A close runs in three steps so the slow SOFTECH read holds no lock:
  (a) one transaction: the month is open, its database items pass, status becomes `closing` (approvals into it now
      get `period_closing`; `ledger.approve` takes the same row lock) and `closing_started_at` is this run's token;
  (b) no transaction: SOFTECH's stock at month end;
  (c) one transaction: the items again (a draft may have landed meanwhile), snapshot, closing-stock entry, its
      auto-reversal on the 1st of the next month, status `closed`.
Any failure in (b) or (c) returns the month to `open`, with nothing of step (c) left, and audits it.
A run that died (restart) leaves `closing` behind: after CLOSING_TAKEOVER a new close takes the month over, and a
run that was only slow finds its token gone at step (c) and stops without posting.

Months close in order and a reopen takes every later closed month with it, so the closed months are always one
unbroken run from the first ledger month: an open month never has a closed month after it.

December has no auto-reversal: step (c) runs the year-end close instead, in the same transaction, and a failure there
undoes the whole step. Balance-sheet balances need no carry-forward entry: `trial_balance` opens with everything
before its date_from.
"""
import datetime
import logging
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.branches.models import Branch
from apps.finance.models import (ClosingStockSnapshot, ClosingStockStore, FinancialPeriod,
                                 GLComparisonLine, LedgerEntry, LedgerLine)
from core.permissions import matrix_allows

from . import compare, ledger, plan2_adapter, softech_stock
from .balances import COUNTED
from .ledger import LedgerError, _audit
from .periods import next_month, previous_month
from .statements import TRADING_PL_SECTIONS

logger = logging.getLogger('elrezeiky.finance')

ZERO = Decimal('0.00')
STOCK_ACCOUNT, RESULT_ACCOUNT = '1390', '5302'
RETAINED_ACCOUNT, OPENING_STOCK_ACCOUNT = '2409', '5301'
DEFAULT_REOPEN_WINDOW = 3
CLOSING_TAKEOVER = datetime.timedelta(minutes=30)

MESSAGES = {
    'not_open':         'الشهر مش مفتوح، مينفعش يتقفل.',
    'checklist':        'شروط الإقفال لسه مكتملتش.',
    'outside_window':   'الشهر ده أقدم من المسموح بإعادة فتحه.',
    'not_closed':       'الشهر مش مقفول، مفيش حاجة تتفتح.',
    'snapshot_missing': 'لقطة المخزون من سوفتيك ناقصة لتاريخ آخر الشهر.',
    'reason_required':  'لازم تكتب سبب إعادة الفتح.',
    'close_running':    'فيه إقفال شغال، استنى لما يخلص.',
    'superseded':       'إقفال أحدث استلم الشهر، والإقفال ده وقف من غير ما يرحّل حاجة.',
    'next_not_open':    'الشهر اللي بعده مش مفتوح.',
    'unknown_branch':   'فيه مخزن عليه رصيد ومش مربوط بفرع.',
    'bad_stock_row':    'تقرير رصيد المخازن في سوفتيك فيه صنف من غير كمية أو تكلفة، صلّحه وأعد الإقفال.',
    'year_end_account': 'إقفال السنة وقف: حساب مطلوب في قيد الإقفال مينفعش يترحل عليه، صلّحه وأعد الإقفال.',
}


class CloseError(Exception):
    def __init__(self, code: str, items: list | None = None, detail: dict | None = None):
        self.code = code
        self.message = MESSAGES.get(code, code)
        self.items = items or []
        self.detail = detail or {}
        super().__init__(f'{code}: {self.message}')


def _require_finalize(user):
    if not matrix_allows(user, 'ledger', 'finalize'):
        raise PermissionDenied('ليس لديك صلاحية لهذا الإجراء')


def _ym(period) -> str:
    return f'{period.year}-{period.month:02d}'


# ── checklist ────────────────────────────────────────────────────────────────

def _item(key, label_ar, ok, *, blocking=True, detail='', link=None) -> dict:
    return {'key': key, 'label_ar': label_ar, 'ok': bool(ok), 'blocking': blocking, 'detail': detail, 'link': link}


def _unexplained(period, **check_filter) -> list:
    lines = GLComparisonLine.objects.filter(period=period, softech_check__is_active=True, **check_filter)
    return [ln for ln in lines.select_related('softech_check') if ln.needs_explanation]


def _database_items(period) -> list:
    """Every item but the stock one; no SOFTECH read, so safe under the period's lock."""
    items = []

    prev = previous_month(period)
    ok = prev is None or prev.status == 'closed'
    items.append(_item('previous_closed', 'الشهر السابق مقفول', ok,
                       detail='' if ok else f'لازم شهر {_ym(prev)} يتقفل الأول'))

    start, end = period.period_start, period.period_end
    drafts = LedgerEntry.objects.filter(status='draft', entry_date__gte=start, entry_date__lte=end).count()
    items.append(_item('no_drafts', 'مفيش قيود مسودة في الشهر', drafts == 0,
                       detail=f'{drafts} قيد مسودة' if drafts else '',
                       link={'status': 'draft', 'date_from': start.isoformat(), 'date_to': end.isoformat()}))

    open_exc = plan2_adapter.open_exception_count(start, end)
    items.append(_item('no_exceptions', 'مفيش استثناءات مفتوحة', open_exc == 0,
                       detail=f'{open_exc} استثناء مفتوح' if open_exc else '',
                       link={'date_from': start.isoformat(), 'date_to': end.isoformat()}))

    late = plan2_adapter.open_late_change_count(start)
    items.append(_item('late_changes', 'تغييرات متأخرة لسه مش متصححة', late == 0, blocking=False,
                       detail=f'{late} تغيير من شهور مقفولة مستني التصحيح' if late else '',
                       link={'kind': 'closed_period_change',
                             'date_to': (start - datetime.timedelta(days=1)).isoformat()}))

    stale = compare.is_stale(period)
    items.append(_item('comparison_fresh', 'مقارنة سوفتيك محدّثة', not stale,
                       detail='حدّث المقارنة قبل الإقفال' if stale else ''))

    lines = _unexplained(period, softech_check__blocks_close=True)
    labels = sorted({ln.softech_check.label for ln in lines})
    items.append(_item('comparison_explained', 'فروق سوفتيك متفسّرة', not lines,
                       detail=f'{len(lines)} فرق بدون تفسير: {"، ".join(labels)}' if lines else ''))

    lines = _unexplained(period, softech_check__source='supplier_balance')
    total = sum((abs(ln.difference) for ln in lines), ZERO)
    items.append(_item('suppliers_explained', 'فروق أرصدة الموردين متفسّرة', not lines, blocking=False,
                       detail=f'{len(lines)} مورد بدون تفسير، إجمالي الفروق {total}' if lines else ''))

    ran = plan2_adapter.last_draft_run_through(period)
    items.append(_item('drafting_ran', 'التسجيل الآلي من سوفتيك غطى الشهر', ran is not None, blocking=False,
                       detail=(f'آخر تغطية للشهر كله: {timezone.localtime(ran):%Y-%m-%d %H:%M}' if ran
                               else 'التسجيل الآلي من سوفتيك لم يغطِّ الشهر كله')))
    return items


def _stock_item(period, stock) -> dict:
    parts = []
    if stock.missing_stores:
        labels = softech_stock.store_map(stock.missing_stores)
        # a store that is its branch: the label says it all; an HQ store: the label is the branch, so keep the code
        names = '، '.join(labels[code].label if labels[code].branch_code == code else f'{code} ({labels[code].label})'
                         for code in stock.missing_stores)
        parts.append(f'لقطة {period.period_end.isoformat()} ناقصة للمخازن: {names}. '
                     'شغّل تقرير رصيد المخازن في تاريخ من سوفتيك لهذا التاريخ')
    for s in stock.stores:
        if s['carried']:
            parts.append(f'{s["store_name"] or s["store_code"]} محمول من {s["snapshot_date"].isoformat()}')
    return _item('stock_snapshot', 'لقطة مخزون آخر الشهر من سوفتيك', not stock.missing_stores,
                 detail=' — '.join(parts))


def checklist(period) -> list:
    """The close checklist, in order. A failed SOFTECH read fails the stock item, not the list."""
    try:
        stock_item = _stock_item(period, softech_stock.valuation(period.period_end))
    except softech_stock.BadStockRow as exc:
        stock_item = _item('stock_snapshot', 'لقطة مخزون آخر الشهر من سوفتيك', False, detail=str(exc))
    except Exception:
        logger.exception('[GLClose] stock read failed for %s', _ym(period))
        stock_item = _item('stock_snapshot', 'لقطة مخزون آخر الشهر من سوفتيك', False,
                           detail='تعذر القراءة من سوفتيك، جرّب تاني')
    return _database_items(period) + [stock_item]


def _blocked(items) -> bool:
    return any(i['blocking'] and not i['ok'] for i in items)


# ── close ────────────────────────────────────────────────────────────────────

def _branch_lines(stock) -> list:
    """Dr 1390 / Cr 5302 per branch on the included stores' total. The ledger takes positive amounts only, so a
    branch whose stock nets negative (SOFTECH books can) has the sides flipped; a branch at exactly zero has no line."""
    totals = {}
    for s in stock.stores:
        if s['included']:
            totals[s['branch_code']] = totals.get(s['branch_code'], ZERO) + s['value']
    branch_ids = dict(Branch.objects.filter(softech_branch_id__in=list(totals)).values_list('softech_branch_id', 'id'))
    lines = []
    for code in sorted(totals):
        value = totals[code]
        if not value:
            continue
        if code not in branch_ids:
            raise CloseError('unknown_branch', detail={'branch_code': code, 'value': str(value)})
        debit, credit = (value, ZERO) if value > 0 else (ZERO, -value)
        lines.append({'account_code': STOCK_ACCOUNT, 'branch_id': branch_ids[code], 'debit': debit, 'credit': credit})
        lines.append({'account_code': RESULT_ACCOUNT, 'branch_id': branch_ids[code], 'debit': credit, 'credit': debit})
    return lines


def _post(lines, *, user, day, source_type, source_key, description, book='closing') -> LedgerEntry:
    draft = ledger.save_draft(user=user, entry_date=day, description=description, lines=lines, book=book,
                              source_type=source_type, source_key=source_key)
    return ledger.approve(draft.pk, user=user, _close_service=True)


def _save_snapshot(period, stock, user) -> ClosingStockSnapshot:
    snapshot = ClosingStockSnapshot.objects.create(
        period=period, as_of=stock.as_of, read_by=user, total=stock.total, excluded_total=stock.excluded_total,
        missing_stores=list(stock.missing_stores))
    branches = dict(Branch.objects.values_list('softech_branch_id', 'id'))
    ClosingStockStore.objects.bulk_create([
        ClosingStockStore(snapshot=snapshot, store_code=s['store_code'], store_name=s['store_name'],
                          branch_id=branches.get(s['branch_code']), included=s['included'], rows=s['rows'],
                          value=s['value'], snapshot_date=s['snapshot_date'], carried=s['carried'])
        for s in stock.stores])
    return snapshot


def _signed_line(code, branch_id, amount, party_code='') -> dict:
    """A line of `amount`, debit positive: the ledger takes positive amounts only, so a negative one is a credit."""
    return {'account_code': code, 'branch_id': branch_id, 'party_code': party_code,
            'debit': max(amount, ZERO), 'credit': max(-amount, ZERO)}


def _year_end_lines(year) -> list:
    """Clears each (account, branch, party) of the trading and P&L sections, nets each branch to 2409. The branch is
    the line's, else the entry's, as balances.py reads it; a balance with neither stays unbranched on both sides."""
    rows = (LedgerLine.objects
            .filter(entry__status__in=COUNTED, account__group__section__in=TRADING_PL_SECTIONS,
                    entry__entry_date__gte=datetime.date(year, 1, 1), entry__entry_date__lte=datetime.date(year, 12, 31))
            .annotate(br=Coalesce('branch_id', 'entry__branch_id'))
            .values('account__code', 'br', 'party_code').annotate(d=Sum('debit'), c=Sum('credit'))
            .order_by('account__code', 'br', 'party_code'))
    lines, results = [], {}
    for r in rows:
        balance = r['d'] - r['c']
        if balance:
            lines.append(_signed_line(r['account__code'], r['br'], -balance, r['party_code']))
            results[r['br']] = results.get(r['br'], ZERO) + balance
    lines += [_signed_line(RETAINED_ACCOUNT, br, net)
              for br, net in sorted(results.items(), key=lambda i: i[0] or 0) if net]
    return lines


def _stock_carry_lines(year) -> list:
    """Dr 5301 / Cr 1390 per branch for December's closing stock, flipped where that stock was negative."""
    lines = []
    for ln in LedgerLine.objects.filter(entry__source_key=f'closing_stock:{year}-12', entry__status='approved',
                                        account__code=STOCK_ACCOUNT).order_by('line_no'):
        value = ln.debit - ln.credit
        lines += [_signed_line(OPENING_STOCK_ACCOUNT, ln.branch_id, value),
                  _signed_line(STOCK_ACCOUNT, ln.branch_id, -value)]
    return lines


def _post_year_end(lines, **kwargs) -> LedgerEntry | None:
    """None when there is nothing to post. A line the ledger refuses (a deactivated account with a balance, say) fails
    the close by the account's code: the accountant fixes that account, the year is not closed around it."""
    if not lines:
        return None
    try:
        return _post(lines, **kwargs)
    except LedgerError as exc:
        line_no = exc.detail.get('line_no')
        if line_no is None:
            raise
        raise CloseError('year_end_account', detail={'account_code': lines[line_no - 1]['account_code'],
                                                     'code': exc.code}) from exc


def year_end_close(year: int, *, user) -> tuple[LedgerEntry | None, LedgerEntry | None]:
    """December's extra step, inside step (c): the closing entry to retained earnings on 31-12 and next year's opening
    stock on 1-1 (the month step (c) has locked open). Either is None when it has no lines."""
    closing = _post_year_end(_year_end_lines(year), user=user, day=datetime.date(year, 12, 31), source_type='year_end',
                             source_key=f'year_end:{year}', description=f'إقفال سنة {year} في الأرباح المرحلة')
    stock = _post_year_end(_stock_carry_lines(year), user=user, day=datetime.date(year + 1, 1, 1),
                           source_type='year_end_stock', source_key=f'year_end_stock:{year + 1}', book='opening',
                           description=f'مخزون أول المدة {year + 1} من بضاعة آخر المدة {year}-12')
    return closing, stock


def _finish_close(period_id, stock, user, token) -> FinancialPeriod:
    """Step (c): one transaction, all of it or none of it."""
    with transaction.atomic():
        period = FinancialPeriod.objects.select_for_update().get(pk=period_id)
        if period.status != 'closing' or period.closing_started_at != token:
            raise CloseError('superseded')
        # locked first, in month order: the auto-reversal lands here, and _close_service would pass a closing month
        following = FinancialPeriod.objects.select_for_update().get(pk=next_month(period).pk)
        if following.status != 'open':
            raise CloseError('next_not_open')
        items = _database_items(period) + [_stock_item(period, stock)]
        if _blocked(items):
            raise CloseError('checklist', items)

        ym = _ym(period)
        snapshot = _save_snapshot(period, stock, user)
        lines = _branch_lines(stock)
        if lines:
            snapshot.entry = _post(lines, user=user, day=period.period_end, source_type='closing_stock',
                                   source_key=f'closing_stock:{ym}',
                                   description=f'بضاعة آخر المدة {ym} — تقييم سوفتيك')
        year_end = {}
        if period.month == 12:
            closing, carried = year_end_close(period.year, user=user)
            year_end = {'year_end_entry_id': closing.pk if closing else None,
                        'year_end_stock_entry_id': carried.pk if carried else None}
        elif lines:
            mirrored = [{**ln, 'debit': ln['credit'], 'credit': ln['debit']} for ln in lines]
            snapshot.reversal = _post(mirrored, user=user, day=following.period_start,
                                      source_type='closing_stock_rev', source_key=f'closing_stock_rev:{ym}',
                                      description=f'عكس تلقائي لبضاعة آخر المدة {ym}')
        snapshot.save(update_fields=['entry', 'reversal'])

        period.status = 'closed'
        period.closed_by = user
        period.closed_at = timezone.now()
        period.closing_started_at = None
        period.closing_stock = snapshot
        period.save(update_fields=['status', 'is_closed', 'closed_by', 'closed_at', 'closing_started_at',
                                   'closing_stock'])
        _audit('gl_period_closed', user=user, obj=period, old_data={'status': 'closing'},
               new_data={'status': 'closed', 'closing_stock': snapshot.pk, 'total': str(stock.total),
                         'entry_id': snapshot.entry_id, 'reversal_id': snapshot.reversal_id, **year_end},
               extra={'carried_stores': list(stock.carried_stores)})
    return period


def _close_failed(period_id, exc, user, token):
    """Back to open, unless a newer run owns the month by now: then only the audit row."""
    with transaction.atomic():
        period = FinancialPeriod.objects.select_for_update().get(pk=period_id)
        old = period.status
        if old == 'closing' and period.closing_started_at == token:
            period.status = 'open'
            period.closing_started_at = None
            period.save(update_fields=['status', 'is_closed', 'closing_started_at'])
        _audit('gl_period_close_failed', user=user, obj=period, old_data={'status': old},
               new_data={'status': period.status}, note=str(exc),
               extra={'error': str(exc), 'code': getattr(exc, 'code', type(exc).__name__),
                      'detail': getattr(exc, 'detail', None)})


def _begin_close(period_id, user) -> tuple:
    """Step (a), committed on return: (period, the run's token). A takeover whose items do not pass returns the month
    to open, so what blocks it can be fixed: approvals are refused while it stays `closing`."""
    with transaction.atomic():
        period = FinancialPeriod.objects.select_for_update().get(pk=period_id)
        if period.period_type != 'month':
            raise CloseError('not_open')
        started = period.closing_started_at
        old = {'status': period.status, 'closing_started_at': started.isoformat() if started else None}
        takeover = period.status == 'closing'
        if takeover:
            if started and timezone.now() - started <= CLOSING_TAKEOVER:
                raise CloseError('close_running')
        elif period.status != 'open':
            raise CloseError('not_open')
        items = _database_items(period)
        blocked = _blocked(items)
        token = None if blocked else timezone.now()
        if takeover or not blocked:
            period.status = 'open' if blocked else 'closing'
            period.closing_started_at = token
            period.save(update_fields=['status', 'is_closed', 'closing_started_at'])
            _audit('gl_period_close_takeover' if takeover else 'gl_period_closing', user=user, obj=period,
                   old_data=old, new_data={'status': period.status,
                                           'closing_started_at': token.isoformat() if token else None})
    if blocked:
        raise CloseError('checklist', items)
    return period, token


def begin_close(period_id, *, user) -> tuple:
    """Step (a), for a caller that runs the rest elsewhere: refusals reach it here, and the month is `closing` from
    the moment this returns. -> what `run_close` takes."""
    _require_finalize(user)
    return _begin_close(period_id, user)


def close_month(period_id, *, user) -> FinancialPeriod:
    period, token = begin_close(period_id, user=user)
    return run_close(period, token, user=user)


def run_close(period, token, *, user) -> FinancialPeriod:
    """Steps (b) and (c) of a run `begin_close` started."""
    period_id = period.pk
    try:
        stock = softech_stock.valuation(period.period_end)
        if stock.missing_stores:
            raise CloseError('snapshot_missing', _database_items(period) + [_stock_item(period, stock)])
        return _finish_close(period_id, stock, user, token)
    except Exception as exc:
        _close_failed(period_id, exc, user, token)
        raise


# ── reopen ───────────────────────────────────────────────────────────────────

def _reopen_window() -> int:
    from apps.config.models import SystemSetting
    try:
        months = int(SystemSetting.get('gl_reopen_window_months', DEFAULT_REOPEN_WINDOW))
    except (TypeError, ValueError):
        months = 0
    if months < 1:
        logger.warning('[GLClose] gl_reopen_window_months is not a positive number — using the default')
        return DEFAULT_REOPEN_WINDOW
    return months


def _close_keys(period) -> list:
    """The source keys of everything closing `period` posted; a December also has the year-end's."""
    ym = _ym(period)
    keys = [f'closing_stock:{ym}', f'closing_stock_rev:{ym}']
    if period.month == 12:
        keys += [f'year_end:{period.year}', f'year_end_stock:{period.year + 1}']
    return keys


def reopen_month(period_id, *, user, reason: str) -> list:
    """Reopen `period` and every later closed month, undoing their close entries, in one transaction. The months
    are then closed again one by one, in order, with `close_month`. Returns them in date order."""
    _require_finalize(user)
    reason = (reason or '').strip()
    if not reason:
        raise CloseError('reason_required')
    with transaction.atomic():
        target = FinancialPeriod.objects.select_for_update().get(pk=period_id)
        if target.status != 'closed' or target.period_type != 'month':
            raise CloseError('not_closed')
        closed = FinancialPeriod.objects.filter(period_type='month', status='closed')
        latest = list(closed.order_by('-period_start').values_list('pk', flat=True)[:_reopen_window()])
        if target.pk not in latest:
            raise CloseError('outside_window')
        # every later month, whatever its status: a status filter would miss a row another run is setting to closing
        later = list(FinancialPeriod.objects.select_for_update().filter(
            period_type='month', period_start__gt=target.period_start).order_by('period_start'))
        if any(m.status == 'closing' for m in later):
            raise CloseError('close_running')
        months = [target, *(m for m in later if m.status == 'closed')]
        # the last month's auto-reversal is dated here (next_month may have just created the row)
        after = FinancialPeriod.objects.select_for_update().get(pk=next_month(months[-1]).pk)
        if after.status != 'open':
            raise CloseError('next_not_open')

        old = {_ym(m): {'status': m.status, 'closed_by': m.closed_by_id, 'closing_stock': m.closing_stock_id,
                        'closed_at': m.closed_at.isoformat() if m.closed_at else None} for m in months}
        for m in months:   # first: the reversals are dated as their originals, in these months
            m.status = 'open'
            m.closed_by = None
            m.closed_at = None
            m.closing_stock = None
            m.save(update_fields=['status', 'is_closed', 'closed_by', 'closed_at', 'closing_stock'])
        reversed_ids = []
        for m in months:
            entries = LedgerEntry.objects.filter(source_key__in=_close_keys(m), status='approved').order_by('pk')
            for entry in entries:
                # an explicit date: anything unexpected raises closed_period instead of moving the mirror
                ledger.reverse(entry.pk, user=user, reason=reason, entry_date=entry.entry_date,
                               _close_service=True)
                reversed_ids.append(entry.pk)
        _audit('gl_period_reopened', user=user, obj=target, old_data={'months': old}, note=reason,
               new_data={'months': {_ym(m): {'status': 'open'} for m in months}},
               extra={'reason': reason, 'months': [_ym(m) for m in months], 'reversed_entry_ids': reversed_ids})
    return months
