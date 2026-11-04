"""Opening entry at 1-1-2026 from finance's 31-12-2025 trial balance (finance-gl Task 5).

Balance-sheet accounts are carried at their balances; trading and P&L accounts are closed
into retained earnings (2409) together with the year's profit, and stock is opened on 5301.
"""
import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import transaction

from .coa_import import parse_trial_balance_sheet
from .ledger import LedgerError, approve, save_draft
from apps.finance.models import GLAccount

OPENING_DATE = datetime.date(2026, 1, 1)
SOURCE_KEY = 'opening:2026'
RETAINED = '2409'
OPENING_STOCK = '5301'
_CENT = Decimal('0.01')


def _check_closing_stock(v) -> Decimal:
    """User input: finite, > 0, at most 2 decimals (sheet balances are quantized instead)."""
    try:
        d = v if isinstance(v, Decimal) else Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        raise LedgerError('bad_amount', {'field': 'closing_stock'})
    if not d.is_finite() or d <= 0 or d != d.quantize(_CENT):
        raise LedgerError('bad_amount', {'field': 'closing_stock'})
    return d.quantize(_CENT)


def _q(v) -> Decimal:
    return Decimal(v).quantize(_CENT, rounding=ROUND_HALF_UP)


def _section_by_code(codes) -> dict:
    found = {a.code: a.group.section
             for a in GLAccount.objects.filter(code__in=codes).select_related('group')}
    missing = sorted(set(codes) - set(found))
    if missing:
        raise LedgerError('missing_accounts', {'codes': missing})
    return found


def _line(code, amount: Decimal, description: str) -> dict:
    return {'account_code': code, 'description': description,
            'debit': amount if amount > 0 else Decimal('0.00'),
            'credit': -amount if amount < 0 else Decimal('0.00')}


def build_opening_lines(rows, closing_stock) -> list:
    closing_stock = _check_closing_stock(closing_stock)
    codes = {r.code for r in rows} | {RETAINED, OPENING_STOCK}
    sections = _section_by_code(codes)
    carried: dict = {}
    closed = Decimal('0')
    for r in rows:
        bal = _q(r.balance)
        if sections[r.code] == 'balance_sheet':
            carried[r.code] = carried.get(r.code, Decimal('0')) + bal
        else:
            closed += bal
    # profit goes to retained earnings: one line of (S - closing_stock)
    carried_2409 = carried.get(RETAINED, Decimal('0'))
    result = closed - closing_stock  # year's result (credit = profit), shown as a debit-positive figure
    carried[RETAINED] = carried_2409 + result
    lines = []
    for code, amt in carried.items():
        if amt == 0:
            continue
        note = 'رصيد افتتاحي'
        if code == RETAINED:
            note = f'مرحل {carried_2409:.2f} + نتيجة السنة {result:.2f} (مدين موجب / دائن سالب)'
        lines.append(_line(code, amt, note))
    lines.append(_line(OPENING_STOCK, closing_stock, 'مخزون اول المدة'))
    total = sum(ln['debit'] - ln['credit'] for ln in lines)
    if total != 0:
        raise LedgerError('unbalanced', {'difference': str(total)})
    return lines


def post_opening(path, *, closing_stock, user, sheet_name=None):
    rows = parse_trial_balance_sheet(path, sheet_name)
    lines = build_opening_lines(rows, closing_stock)
    with transaction.atomic():  # a failed approve must not leave a draft holding the source key
        entry = save_draft(user=user, entry_date=OPENING_DATE, description='قيد افتتاحي 1-1-2026',
                           lines=lines, book='opening', source_type='opening',
                           source_key=SOURCE_KEY)
        return approve(entry.pk, user=user)
