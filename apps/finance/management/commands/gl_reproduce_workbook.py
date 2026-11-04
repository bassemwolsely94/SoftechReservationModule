"""python manage.py gl_reproduce_workbook <xlsx> --year 2025 --closing-stock N [--user U] [--tb-sheet S]

Proof that the ledger reproduces finance's own statements.  Inside one transaction that is ALWAYS
rolled back: import the chart of accounts from the workbook's trial balance, post that year's
trial balance as one approved entry dated 31-12, post the closing stock (Dr 1390 / Cr 5302),
run trading_and_pl + financial_position, and print them beside the workbook's cells (sheets
«الختامية بسوفتيك» and «الميزانية 31-12-<year>», found by label).  Exit 1 on any difference.
Nothing persists — GL row counts are compared before and after.
"""
import datetime
import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import openpyxl
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.audit.models import AuditLog
from apps.finance.gl.coa_import import import_coa, parse_trial_balance_sheet_with_warnings
from apps.finance.gl.ledger import LedgerError, _period_for, approve, save_draft
from apps.finance.gl.names import normalize_ar
from apps.finance.gl.opening import _check_closing_stock
from apps.finance.gl.statements import financial_position, trading_and_pl
from apps.finance.models import (
    FinancialPeriod, GLAccount, GLAccountGroup, GLSequence, LedgerEntry, LedgerLine,
)
from apps.users.models import StaffProfile

_CENT = Decimal('0.01')
MONEY_TOL = Decimal('0.01')
RATIO_TOL = Decimal('0.00001')

TRADING_SHEET = 'الختامية بسوفتيك'
# (key, label, how) — how: 'left' value left of label (else right), 'below' value under label
TRADING_FIGURES = [
    ('opening_stock', 'رصيد اول المدة', 'left'),
    ('net_purchases', 'صافى المشتريات', 'left'),
    ('net_sales', 'صافى المبيعات', 'left'),
    ('closing_stock', 'رصيد اخر المدة', 'left'),
    ('gross_profit', 'مجمل الربح', 'left'),
    ('general_expenses', 'المصاريف العمومية', 'left'),
    ('selling_expenses', 'مصاريف البيع والتوزيع', 'left'),
    ('depreciation', 'الاهلاكات', 'left'),
    ('operating_expenses', 'مصاريف التشغيل', 'left'),
    ('financing_expenses', 'المصاريف التمويلية', 'left'),
    ('other_revenue', 'ايرادات', 'left'),
    ('capital_gains', 'ارباح راسمالية بيع اصول', 'left'),
    ('net_profit', 'صافى الارباح', 'left'),
    ('expenses_ex_depreciation', 'المصاريف', 'below'),
    ('monthly_avg_sales', 'متوسط المبيعات الشهرى', 'below'),
    ('monthly_avg_net_profit', 'المتوسط الشهرى', 'below'),
    ('monthly_avg_expenses', 'معدل الشهر', 'right'),
    ('gross_margin', 'نسبة مجمل الربح لصافى المبيعات', 'right'),
    ('net_margin', 'نسبة صافى الربح لصافى المبيعات', 'right'),
    ('net_margin_ex_depreciation', 'نسبة صافى الربح لصافى المبيعات بدون اهلاكات', 'right'),
    ('expense_ratio', 'نسبة المصاريف لصافى المبيعات', 'right'),
]
RATIO_KEYS = {'gross_margin', 'net_margin', 'net_margin_ex_depreciation', 'expense_ratio'}
# Shown but not counted: finance's cell is =(-depreciation + operating + net profit) / sales,
# which is not what its label says; ours is (net profit + depreciation) / sales.
INFO_ONLY = {
    'net_margin_ex_depreciation':
        'info only: workbook formula is (net - depreciation + operating) / sales, not its label',
}

# (key, label, column header, section label the row must follow or None)
# column None = «الصافى كلى» when filled, else the nearest «الصافى فرعى».
POSITION_FIGURES = [
    ('fixed_assets', 'الاصول الثابتة', 'التكلفة', None),
    ('accumulated_depreciation', 'الاصول الثابتة', 'مجمع الاهلاك', None),
    ('net_fixed_assets', 'اجمالى الاصول الثابتة', None, None),
    ('inventory', 'بضاعة اخر المدة', None, 'الاصول المتداولة'),
    ('receivables', 'عملاء مدينون واورق قبض', None, 'الاصول المتداولة'),
    ('other_debtors', 'مدينون متنوعون', None, 'الاصول المتداولة'),
    ('deposits', 'تامينات لدى الغير', None, 'الاصول المتداولة'),
    ('cash', 'نقدية بالبنوك والصندوق', None, 'الاصول المتداولة'),
    ('total_current_assets', 'اجمالى الاصول المتداولة', None, None),
    ('creditors', 'دائنون متنوعون', None, 'الالتزامات المتداولة'),
    ('overdraft', 'سحب على المكشوف', None, 'الالتزامات المتداولة'),
    ('notes_payable', 'اوراق الدفع', None, 'الالتزامات المتداولة'),
    ('suppliers', 'الموردين', None, 'الالتزامات المتداولة'),
    ('total_current_liabilities', 'اجمالى الالتزامات', None, 'الالتزامات المتداولة'),
    ('working_capital', 'راس المال العامل', None, None),
    ('total_investment', 'اجمالى الاستثمار', None, None),
    ('capital', 'راس المال', None, 'حقوق الملكية'),
    ('partners', 'جارى الشركاء', None, 'حقوق الملكية'),
    ('profit_and_loss', 'ح/ الارباح والخسائر', None, 'حقوق الملكية'),
    ('total_equity', 'اجمالى حقوق الملكية', None, None),
]

COUNTED_MODELS = (GLAccountGroup, GLAccount, LedgerEntry, LedgerLine, GLSequence,
                  FinancialPeriod, AuditLog, User, StaffProfile)


class _Rollback(Exception):
    pass


def _n(s) -> str:
    return normalize_ar(str(s)) if s is not None else ''


def _num(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    return None


class _Sheet:
    """Label lookup over a sheet read with data_only=True."""

    def __init__(self, ws):
        self.cells = {}
        self.order = []
        for row in ws.iter_rows():
            for c in row:
                if c.value not in (None, ''):
                    self.cells[(c.row, c.column)] = c.value
                    self.order.append((c.row, c.column))

    def find(self, label, after=None):
        want = _n(label)
        start = (0, 0)
        if after:
            pos = self.find(after)
            if pos is None:
                return None
            start = pos
        texts = [(p, _n(self.cells[p])) for p in self.order
                 if p > start and isinstance(self.cells[p], str)]
        exact = [p for p, t in texts if t == want]
        if exact:
            return exact[0]
        prefix = [p for p, t in texts if t.startswith(want)]
        return prefix[0] if prefix else None

    def value_beside(self, pos, how):
        r, c = pos
        if how == 'below':
            for rr in range(r + 1, r + 4):
                v = _num(self.cells.get((rr, c)))
                if v is not None:
                    return v
            return None
        left = [_num(self.cells.get((r, cc))) for cc in range(c - 1, 0, -1)]
        right = [_num(self.cells.get((r, cc))) for cc in range(c + 1, c + 10)]
        seq = left + right if how == 'left' else right + left
        return next((v for v in seq if v is not None), None)

    def header_cols(self, name):
        want = _n(name)
        return [p for p in self.order
                if isinstance(self.cells[p], str) and _n(self.cells[p]) == want]


def _read_trading(wb):
    if TRADING_SHEET not in wb.sheetnames:
        raise CommandError(f'sheet {TRADING_SHEET!r} not found')
    sh = _Sheet(wb[TRADING_SHEET])
    out = {}
    for key, label, how in TRADING_FIGURES:
        pos = sh.find(label)
        out[key] = sh.value_beside(pos, how) if pos else None
    return out


def _read_position(wb, year):
    name = next((s for s in wb.sheetnames if _n(s) == _n(f'الميزانية 31-12-{year}')), None)
    if name is None:
        raise CommandError(f'sheet «الميزانية 31-12-{year}» not found')
    sh = _Sheet(wb[name])
    out = {}
    for key, label, header, after in POSITION_FIGURES:
        pos = sh.find(label, after)
        if pos is None:
            out[key] = None
            continue
        row, lab_col = pos
        if header:
            cols = [c for (_r, c) in sh.header_cols(header)]
        else:
            total_cols = [c for (_r, c) in sh.header_cols('الصافى كلى')]
            v = next((_num(sh.cells.get((row, c))) for c in total_cols
                      if _num(sh.cells.get((row, c))) is not None), None)
            if v is not None:
                out[key] = v
                continue
            cols = [c for (_r, c) in sh.header_cols('الصافى فرعى')]
        cols.sort(key=lambda c: abs(c - lab_col))
        out[key] = next((_num(sh.cells.get((row, c))) for c in cols
                         if _num(sh.cells.get((row, c))) is not None), None)
    return out


def _counts():
    return {m.__name__: m.objects.count() for m in COUNTED_MODELS}


class Command(BaseCommand):
    help = "Rolled-back reproduction of finance's year-end statements from the ledger."

    def add_arguments(self, parser):
        parser.add_argument('xlsx')
        parser.add_argument('--year', type=int, required=True)
        parser.add_argument('--closing-stock', required=True)
        parser.add_argument('--user', default=None,
                            help='username of a staff member; default: a throwaway profile '
                                 'created inside the rolled-back transaction')
        parser.add_argument('--tb-sheet', default=None,
                            help='trial-balance sheet (default «ميزان المراجعة <year>»)')

    def handle(self, *args, **opts):
        year = opts['year']
        try:
            closing = _check_closing_stock(Decimal(opts['closing_stock']))
        except (InvalidOperation, LedgerError):
            raise CommandError('--closing-stock must be a positive number with at most 2 decimals')
        path = opts['xlsx']
        wb = openpyxl.load_workbook(path, data_only=True)
        try:
            tb_sheet = opts['tb_sheet']
            if tb_sheet is None:
                tb_sheet = next((s for s in wb.sheetnames
                                 if _n(s) == _n(f'ميزان المراجعة {year}')), None)
            expected_tp = _read_trading(wb)
            expected_fp = _read_position(wb, year)
        finally:
            wb.close()
        rows, warnings = parse_trial_balance_sheet_with_warnings(path, tb_sheet)
        for w in warnings:
            self.stdout.write(self.style.WARNING(f'warning: {w}'))

        before = _counts()
        notes = []
        try:
            with transaction.atomic():
                tp, fp = self._reproduce(rows, year, closing, opts['user'], notes)
                raise _Rollback
        except _Rollback:
            pass
        after = _counts()

        for n in notes:
            self.stdout.write(n)
        diffs = 0
        diffs += self._print('حساب المتاجرة والأرباح والخسائر (الختامية بسوفتيك)',
                             [(k, lbl) for k, lbl, _h in TRADING_FIGURES], tp, expected_tp)
        diffs += self._print(f'المركز المالى فى 31-12-{year}',
                             [(k, lbl) for k, lbl, _h, _a in POSITION_FIGURES]
                             + [('check', 'الفرق (الاستثمار − حقوق الملكية)')],
                             fp, {**expected_fp, 'check': Decimal('0')})
        self.stdout.write('')
        self.stdout.write('GL row counts before → after (must be equal):')
        leaked = False
        for k in before:
            flag = '' if before[k] == after[k] else '  <-- CHANGED'
            leaked |= bool(flag)
            self.stdout.write(f'  {k:<16} {before[k]:>8} → {after[k]:>8}{flag}')
        if leaked:
            raise CommandError('rows persisted after rollback')
        if diffs:
            raise CommandError(f'{diffs} figure(s) differ from the workbook')
        self.stdout.write(self.style.SUCCESS('all figures match the workbook; nothing persisted'))

    def _reproduce(self, rows, year, closing, username, notes):
        if username:
            staff = StaffProfile.objects.filter(user__username=username).first()
            if staff is None:
                raise CommandError(f'no staff profile for user {username!r}')
        else:
            u = User.objects.create(username=f'gl_reproduce_{uuid.uuid4().hex[:12]}')
            staff, _ = StaffProfile.objects.get_or_create(user=u)
        res = import_coa(rows, user=staff)
        notes.append(f'COA: rows={len(rows)} created={res.created} updated={res.updated}')
        if res.unknown_groups:
            raise CommandError(f'unknown trial-balance groups: {res.unknown_groups}')

        start, end = datetime.date(year, 1, 1), datetime.date(year, 12, 31)
        prior = LedgerEntry.objects.filter(status__in=('approved', 'reversed'),
                                           entry_date__lte=end).count()
        if prior:
            notes.append(f'warning: {prior} approved entries already dated ≤ {end} are included')
        period = _period_for(end)
        if period.status != 'open':
            notes.append(f'note: period {period} was {period.status}; opened inside the rollback')
            FinancialPeriod.objects.filter(pk=period.pk).update(status='open', is_closed=False)

        by_code = {}
        for r in rows:
            by_code[r.code] = by_code.get(r.code, Decimal('0')) + r.balance
        lines = []
        for code, bal in by_code.items():
            bal = bal.quantize(_CENT, rounding=ROUND_HALF_UP)
            if bal == 0:
                continue
            lines.append({'account_code': code, 'description': f'ميزان المراجعة {year}',
                          'debit': bal if bal > 0 else Decimal('0'),
                          'credit': -bal if bal < 0 else Decimal('0')})
        net = sum((ln['debit'] - ln['credit'] for ln in lines), Decimal('0'))
        if net != 0:
            raise CommandError(f'trial balance does not balance after rounding: {net}')
        try:
            tb = save_draft(user=staff, entry_date=end, description=f'ميزان المراجعة {year}',
                            lines=lines, book='general', source_type='reproduce',
                            source_key=f'reproduce:tb:{year}')
            approve(tb.pk, user=staff, _allow_before_opening=True)
            cs = save_draft(user=staff, entry_date=end, description=f'بضاعة آخر المدة {year}',
                            lines=[{'account_code': '1390', 'debit': closing, 'credit': 0},
                                   {'account_code': '5302', 'debit': 0, 'credit': closing}],
                            book='closing', source_type='reproduce',
                            source_key=f'reproduce:closing:{year}')
            approve(cs.pk, user=staff, _allow_before_opening=True)
        except LedgerError as e:
            raise CommandError(f'{e} {e.detail}')
        notes.append(f'posted (rolled back): trial balance {len(lines)} lines + closing stock {closing}')
        return trading_and_pl(start, end), financial_position(end)

    def _print(self, title, items, ours, theirs):
        self.stdout.write('')
        self.stdout.write(title)
        self.stdout.write(f"  {'key':<28} {'ledger':>18} {'workbook':>18} {'diff':>14}")
        diffs = 0
        for key, label in items:
            mine, exp = ours.get(key), theirs.get(key)
            tol = RATIO_TOL if key in RATIO_KEYS else MONEY_TOL
            if exp is None:
                status, d = 'NOT IN WORKBOOK', None
                diffs += 1
            elif mine is None:
                status, d = 'MISSING', None
                diffs += 1
            else:
                d = Decimal(mine) - exp
                status = 'ok' if abs(d) <= tol else 'DIFF'
                if status == 'DIFF' and key in INFO_ONLY:
                    status = INFO_ONLY[key]
                else:
                    diffs += status != 'ok'
            places = Decimal('0.000001') if key in RATIO_KEYS else _CENT
            fmt = (lambda v: '' if v is None else  # + 0 drops a negative zero
                   f'{Decimal(v).quantize(places, rounding=ROUND_HALF_UP) + 0:,}')
            self.stdout.write(f'  {key:<28} {fmt(mine):>18} {fmt(exp):>18} {fmt(d):>14}  '
                              f'{status}  {label}')
        return diffs
