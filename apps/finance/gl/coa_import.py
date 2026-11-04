"""Chart-of-accounts importer from finance's trial-balance pivot sheet (finance-gl Task 4).

Idempotent upsert by account code. Never deletes; never touches is_active or the
requires_branch / requires_party flags of an existing account.
"""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

import openpyxl
from django.db import transaction

from apps.audit.models import AuditLog
from apps.finance.models import GLAccount, GLAccountGroup
from .names import normalize_ar

BS, TR, PL = 'balance_sheet', 'trading', 'pl'

# (display name, section, account_type, nature, default statement_line) — order = group order.
_GROUPS = [
    ('اصول ثابته', BS, 'asset', 'debit', 'fixed_assets'),
    ('مجمع الإهلاك', BS, 'contra_asset', 'credit', 'accumulated_depreciation'),
    ('النقديه بالصندوق', BS, 'asset', 'debit', 'cash'),
    ('النقديه بالبنوك', BS, 'asset', 'debit', 'cash'),
    ('التحويلات', BS, 'asset', 'debit', 'cash'),
    ('المقبوضات التجاريه', BS, 'asset', 'debit', 'receivables'),
    ('المقبوضات غير التجاريه', BS, 'asset', 'debit', 'other_debtors'),
    ('مصروفات مدفوعه مقدماً', BS, 'asset', 'debit', 'other_debtors'),
    ('الضرائب', BS, 'liability', 'credit', 'creditors'),
    ('المدفوعات التجاريه', BS, 'liability', 'credit', 'suppliers'),
    ('المدفوعات الغير تجاريه', BS, 'liability', 'credit', 'creditors'),
    ('خصوم اخرى', BS, 'liability', 'credit', 'creditors'),
    ('الهيئه العامه للتأمينات الاجتماعيه', BS, 'liability', 'credit', 'creditors'),
    ('شركات شقيقة', BS, 'liability', 'credit', 'creditors'),
    ('جارى الشركاء', BS, 'equity', 'credit', 'partners'),
    ('حقوق الملكيه', BS, 'equity', 'credit', 'capital'),
    ('المبيعات', TR, 'revenue', 'credit', 'net_sales'),
    ('ايرادات', PL, 'revenue', 'credit', 'other_revenue'),
    ('ارباح و خسائر راسمالية', PL, 'revenue', 'credit', 'capital_gains'),
    ('تكلفة المبيعات', TR, 'cogs', 'debit', 'net_purchases'),
    ('محزون أول المده', TR, 'cogs', 'debit', 'opening_stock'),
    ('المصروفات العموميه', PL, 'expense', 'debit', 'general_expenses'),
    ('مصروفات بيع وتوزيع', PL, 'expense', 'debit', 'selling_expenses'),
    ('مصروفات التشغيل', PL, 'expense', 'debit', 'operating_expenses'),
    ('المصروفات التمويلية', PL, 'expense', 'debit', 'financing_expenses'),
    ('الاهلاكات', PL, 'expense', 'debit', 'depreciation'),
]
GROUP_MAP = {normalize_ar(n): (sec, typ, nat, line) for n, sec, typ, nat, line in _GROUPS}
GROUP_DISPLAY = {normalize_ar(g[0]): (g[0], i + 1) for i, g in enumerate(_GROUPS)}

# Overrides reproducing finance's 31-12-2025 statement of position (by account code).
BS_LINE_BY_ACCOUNT = {
    **{c: 'cash' for c in ('1301', '1302', '1303', '1320')},
    **{c: 'receivables' for c in ('1321', '1329', '1341', '1343', '1344', '1345')},
    **{c: 'other_debtors' for c in ('1304', '1351', '1357', '1366', '1368', '1370',
                                    '2362', '2363', '2364', '2366', '2367')},
    '1353': 'deposits',
    **{c: 'creditors' for c in ('1369', '2132', '2351', '2354', '2360', '2361', '2365')},
    '2343': 'notes_payable', '2341': 'suppliers',
    '2400': 'capital', '2409': 'retained',
}

PARTY_BY_ACCOUNT = {'2341': 'supplier', '2351': 'supplier', '1341': 'customer', '1351': 'employee'}
PARTY_BY_GROUP = {normalize_ar('جارى الشركاء'): 'partner'}
CONTRA_REVENUE = {'6018', '6019', '6021', '6022', '6023'}

# code -> (name, group name, section, account_type, nature, statement_line)
SYSTEM_ACCOUNTS = {
    '1390': ('بضاعة آخر المدة', 'بضاعة آخر المدة', BS, 'asset', 'debit', 'inventory'),
    '5302': ('مخزون آخر المدة', 'مخزون آخر المدة', TR, 'cogs', 'credit', 'closing_stock'),
}


@dataclass
class TBRow:
    group: str
    code: str
    name: str
    debit: Decimal
    credit: Decimal
    balance: Decimal


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    unknown_groups: list = field(default_factory=list)


def _dec(v) -> Decimal:
    if v is None or (isinstance(v, str) and not v.strip()):
        return Decimal('0')
    try:
        return Decimal(str(v).strip().replace(',', ''))
    except InvalidOperation:
        return Decimal('0')


def _code(v) -> str:
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip() if v is not None else ''


def _find_header(ws):
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        cells = [str(c).strip() if c is not None else '' for c in row]
        if 'Sub account name' in cells and 'رقم العملية' in cells and 'Trans. Name' in cells:
            low = [c.lower() for c in cells]
            debit_i = next((j for j, c in enumerate(low) if c in ('debt', 'debit')), None)
            credit_i = low.index('credit') if 'credit' in low else None
            return (i, cells.index('Sub account name'), cells.index('رقم العملية'),
                    cells.index('Trans. Name'), debit_i, credit_i)
    return None


def parse_trial_balance_sheet(path, sheet_name=None):
    wb = openpyxl.load_workbook(path, data_only=True)
    try:
        sheets = [wb[sheet_name]] if sheet_name else list(wb.worksheets)
        for ws in sheets:
            hdr = _find_header(ws)
            if hdr:
                break
        else:
            raise ValueError('trial-balance header row not found')
        h_idx, g_i, c_i, n_i, d_i, cr_i = hdr
        rows, group = [], ''
        for r, row in enumerate(ws.iter_rows(values_only=True)):
            if r <= h_idx:
                continue
            first = row[g_i] if g_i < len(row) else None
            first = str(first).strip() if first is not None else ''
            if first.endswith('Total'):  # "<group> Total" and "Grand Total"
                continue
            if first:
                group = first
            code = _code(row[c_i] if c_i < len(row) else None)
            if not code:
                continue
            debit = _dec(row[d_i]) if d_i is not None and d_i < len(row) else Decimal('0')
            credit = abs(_dec(row[cr_i])) if cr_i is not None and cr_i < len(row) else Decimal('0')
            name = row[n_i] if n_i < len(row) else None
            rows.append(TBRow(group, code, str(name).strip() if name is not None else '',
                              debit, credit, debit - credit))
        return rows
    finally:
        wb.close()


class _DryRun(Exception):
    pass


def _group(key_norm, name, section, order, cache):
    if key_norm not in cache:
        cache[key_norm], _ = GLAccountGroup.objects.get_or_create(
            name=name, defaults={'section': section, 'order': order})
    return cache[key_norm]


def _import(rows, res):
    cache = {normalize_ar(g.name): g for g in GLAccountGroup.objects.all()}
    for code, (name, gname, sec, typ, nat, line) in SYSTEM_ACCOUNTS.items():
        if GLAccount.objects.filter(code=code).exists():
            continue
        grp = _group(normalize_ar(gname), gname, sec, 100 + len(cache), cache)
        GLAccount.objects.create(code=code, name=name, group=grp, nature=nat, account_type=typ,
                                 statement_line=line, is_system=True)
        res.created += 1
    unknown = []
    for row in rows:
        if row.code in SYSTEM_ACCOUNTS:
            continue
        key = normalize_ar(row.group)
        spec = GROUP_MAP.get(key)
        if not spec:
            if row.group not in unknown:
                unknown.append(row.group)
            continue
        sec, typ, nat, line = spec
        gname, order = GROUP_DISPLAY[key]
        grp = _group(key, gname, sec, order, cache)
        line = BS_LINE_BY_ACCOUNT.get(row.code, line)
        if row.code in CONTRA_REVENUE and key == normalize_ar('المبيعات'):
            typ, nat = 'contra_revenue', 'debit'
        party = PARTY_BY_ACCOUNT.get(row.code) or PARTY_BY_GROUP.get(key) or 'none'
        acc = GLAccount.objects.filter(code=row.code).first()
        if acc is None:
            GLAccount.objects.create(code=row.code, name=row.name, group=grp, nature=nat,
                                     account_type=typ, statement_line=line, party_type=party)
            res.created += 1
        else:
            acc.name, acc.group, acc.statement_line = row.name, grp, line
            acc.nature, acc.account_type = nat, typ
            if acc.party_type == 'none':
                acc.party_type = party
            acc.save()
            res.updated += 1
    res.unknown_groups = unknown


def import_coa(rows, *, user, dry_run=False) -> ImportResult:
    res = ImportResult()
    try:
        with transaction.atomic():
            _import(rows, res)
            if dry_run:
                raise _DryRun
    except _DryRun:
        return res
    AuditLog.log('gl_coa_imported', user=user, note='chart of accounts import',
                 extra={'created': res.created, 'updated': res.updated,
                        'unknown_groups': res.unknown_groups, 'rows': len(rows)})
    return res
