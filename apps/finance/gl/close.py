"""Month close on the ledger: checklist, SOFTECH closing stock, auto-reversal, reopen (finance-gl Plan 3, Task 6).

A close runs in three steps so the slow SOFTECH read holds no lock:
  (a) one transaction: the month is open, its database items pass, status becomes `closing` (approvals into it now
      get `period_closing`; `ledger.approve` takes the same row lock);
  (b) no transaction: SOFTECH's stock at month end;
  (c) one transaction: the items again (a draft may have landed meanwhile), snapshot, closing-stock entry, its
      auto-reversal on the 1st of the next month, status `closed`.
Any failure in (b) or (c) returns the month to `open`, with nothing of step (c) left, and audits it.

Months close in order and a reopen takes every later closed month with it, so the closed months are always one
unbroken run from the first ledger month: an open month never has a closed month after it.
"""
import logging
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.branches.models import Branch
from apps.finance.models import (ClosingStockSnapshot, ClosingStockStore, FinancialPeriod,
                                 GLComparisonLine, LedgerEntry)
from core.permissions import matrix_allows

from . import compare, ledger, plan2_adapter, softech_stock
from .ledger import _audit
from .periods import next_month, previous_month

logger = logging.getLogger('elrezeiky.finance')

ZERO = Decimal('0.00')
STOCK_ACCOUNT, RESULT_ACCOUNT = '1390', '5302'
DEFAULT_REOPEN_WINDOW = 3

MESSAGES = {
    'not_open':         'الشهر مش مفتوح، مينفعش يتقفل.',
    'checklist':        'شروط الإقفال لسه مكتملتش.',
    'outside_window':   'الشهر ده أقدم من المسموح بإعادة فتحه.',
    'not_closed':       'الشهر مش مقفول، مفيش حاجة تتفتح.',
    'snapshot_missing': 'لقطة المخزون من سوفتيك ناقصة لتاريخ آخر الشهر.',
    'reason_required':  'لازم تكتب سبب إعادة الفتح.',
    'close_running':    'فيه إقفال شغال على شهر بعده، استنى لما يخلص.',
    'unknown_branch':   'فيه مخزن عليه رصيد ومش مربوط بفرع.',
    'year_end_pending': 'إقفال ديسمبر محتاج إقفال السنة، ولسه مش متاح.',
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
                       detail=f'{open_exc} استثناء مفتوح' if open_exc else ''))

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
        names = '، '.join(f'{code} ({labels[code].label})' for code in stock.missing_stores)
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


def year_end_close(year: int, *, user):
    """December's extra step, inside step (c). Until the year-end close lands, a December cannot close."""
    raise CloseError('year_end_pending', detail={'year': year})


def _finish_close(period_id, stock, user) -> FinancialPeriod:
    """Step (c): one transaction, all of it or none of it."""
    with transaction.atomic():
        period = FinancialPeriod.objects.select_for_update().get(pk=period_id)
        if period.status != 'closing':
            raise CloseError('not_open')
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
        if period.month == 12:
            year_end_close(period.year, user=user)
        elif lines:
            mirrored = [{**ln, 'debit': ln['credit'], 'credit': ln['debit']} for ln in lines]
            snapshot.reversal = _post(mirrored, user=user, day=next_month(period).period_start,
                                      source_type='closing_stock_rev', source_key=f'closing_stock_rev:{ym}',
                                      description=f'عكس تلقائي لبضاعة آخر المدة {ym}')
        snapshot.save(update_fields=['entry', 'reversal'])

        period.status = 'closed'
        period.closed_by = user
        period.closed_at = timezone.now()
        period.closing_stock = snapshot
        period.save(update_fields=['status', 'is_closed', 'closed_by', 'closed_at', 'closing_stock'])
        _audit('gl_period_closed', user=user, obj=period, old_data={'status': 'closing'},
               new_data={'status': 'closed', 'closing_stock': snapshot.pk, 'total': str(stock.total),
                         'entry_id': snapshot.entry_id, 'reversal_id': snapshot.reversal_id},
               extra={'carried_stores': list(stock.carried_stores)})
    return period


def _close_failed(period_id, exc, user):
    with transaction.atomic():
        period = FinancialPeriod.objects.select_for_update().get(pk=period_id)
        old = period.status
        if old == 'closing':
            period.status = 'open'
            period.save(update_fields=['status', 'is_closed'])
        _audit('gl_period_close_failed', user=user, obj=period, old_data={'status': old},
               new_data={'status': period.status}, note=str(exc),
               extra={'error': str(exc), 'code': getattr(exc, 'code', type(exc).__name__)})


def close_month(period_id, *, user) -> FinancialPeriod:
    _require_finalize(user)
    with transaction.atomic():
        period = FinancialPeriod.objects.select_for_update().get(pk=period_id)
        if period.status != 'open' or period.period_type != 'month':
            raise CloseError('not_open')
        items = _database_items(period)
        if _blocked(items):
            raise CloseError('checklist', items)
        period.status = 'closing'
        period.save(update_fields=['status', 'is_closed'])
        _audit('gl_period_closing', user=user, obj=period, old_data={'status': 'open'},
               new_data={'status': 'closing'})
    try:
        stock = softech_stock.valuation(period.period_end)
        if stock.missing_stores:
            raise CloseError('snapshot_missing', _database_items(period) + [_stock_item(period, stock)])
        return _finish_close(period_id, stock, user)
    except Exception as exc:
        _close_failed(period_id, exc, user)
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
        later = FinancialPeriod.objects.select_for_update().filter(
            period_type='month', period_start__gt=target.period_start, status__in=('closed', 'closing'))
        months = [target, *later.order_by('period_start')]
        if any(m.status == 'closing' for m in months):
            raise CloseError('close_running')

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
                ledger.reverse(entry.pk, user=user, reason=reason)
                reversed_ids.append(entry.pk)
        _audit('gl_period_reopened', user=user, obj=target, old_data={'months': old}, note=reason,
               new_data={'months': {_ym(m): {'status': 'open'} for m in months}},
               extra={'reason': reason, 'months': [_ym(m) for m in months], 'reversed_entry_ids': reversed_ids})
    return months
