"""
apps/crews/unattributed.py

«بائع غير محدد» (spec 2026-11-13 §6.8): sales whose seller (PurchaseHistory.softech_user =
SOFTECH stktransm.usercode, never cashiercode) is blank or a generic / station account cannot be
credited to a person, so no crew sees them. This shows that share per branch so it is visible;
fixing the habit at the till is an operations matter.

The generic rule is owner-editable: SOFTECH user groups (default 17 = cashier stations) plus
single user codes, stored as one SystemSetting json row (created on the first save). Reads the
local mirror only — no SOFTECH access. Company-level, not branch-scoped (permission_matrix.py).
"""
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Sum

from apps.audit.models import AuditLog
from apps.branches.models import Branch
from apps.config.models import SystemSetting
from apps.customers.models import PurchaseHistory
from apps.users.models import ErpUserGroup, ERPUser

from .branches import live_branches

SETTING_KEY = 'crews.generic_sellers'
DEFAULT_RULE = {'groups': ['17'], 'usercodes': []}
SALE_DOC = '115'
TOP_SELLERS = 50


def _clean(values) -> list:
    out = []
    for v in values or []:
        v = str(v).strip()
        if v and v not in out:
            out.append(v)
    return sorted(out)


def generic_rule() -> dict:
    value = SystemSetting.get(SETTING_KEY)
    if not isinstance(value, dict):
        return {'groups': list(DEFAULT_RULE['groups']), 'usercodes': list(DEFAULT_RULE['usercodes'])}
    return {'groups': _clean(value.get('groups')), 'usercodes': _clean(value.get('usercodes'))}


@transaction.atomic
def set_generic_rule(groups, usercodes, user) -> dict:
    old = generic_rule()
    new = {'groups': _clean(groups), 'usercodes': _clean(usercodes)}
    row, _ = SystemSetting.objects.update_or_create(key=SETTING_KEY, defaults={
        'label': 'الأطقم — حسابات «بائع غير محدد»',
        'description': 'مجموعات مستخدمي SOFTECH وأكواد مستخدمين لا تُنسب مبيعاتها لشخص (spec 2026-11-13 §6.8)',
        'value': json.dumps(new, ensure_ascii=False), 'value_type': 'json', 'category': 'general'})
    if new != old:
        AuditLog.log('crew_generic_sellers_set', user=user, obj=row, old_data=old, new_data=new,
                     extra={'crew_id': None, 'row': None, 'row_id': None})
    return new


def is_generic(code: str, rule: dict, group_of: dict) -> bool:
    code = (code or '').strip()
    if not code:
        return True
    if code in rule.get('usercodes', ()):
        return True
    return group_of.get(code) in set(rule.get('groups', ()))


def branch_label(b) -> str:
    return b.name_ar or b.name or b.code or b.softech_branch_id


def _money(v) -> float:
    return float(round(v or Decimal('0'), 2))


def unattributed_by_branch(start: date, end: date) -> dict:
    rule = generic_rule()
    users = {u: (g or '', n or '') for u, g, n in
             ERPUser.objects.values_list('username', 'user_group', 'full_name')}
    group_of = {u: g for u, (g, _) in users.items()}
    group_names = {str(g): n for g, n in ErpUserGroup.objects.values_list('usergroup', 'name')}

    rows = (PurchaseHistory.objects
            .filter(doc_code=SALE_DOC, invoice_date__date__gte=start, invoice_date__date__lte=end)
            .values('branch_id', 'softech_user')
            .annotate(n=Count('id'), amount=Sum('total_amount')))
    per_branch = defaultdict(lambda: {'invoices': 0, 'amount': Decimal('0'),
                                      'unattributed_invoices': 0, 'unattributed_amount': Decimal('0')})
    per_seller = defaultdict(lambda: {'invoices': 0, 'amount': Decimal('0')})
    for r in rows:
        code = (r['softech_user'] or '').strip()
        amount = r['amount'] or Decimal('0')
        b = per_branch[r['branch_id']]
        b['invoices'] += r['n']
        b['amount'] += amount
        if is_generic(code, rule, group_of):
            b['unattributed_invoices'] += r['n']
            b['unattributed_amount'] += amount
        s = per_seller[code]
        s['invoices'] += r['n']
        s['amount'] += amount

    # live branches, plus any branch with sales in range, so nothing silently drops
    branches = {b.id: b for b in live_branches()}
    missing = set(per_branch) - set(branches)
    if missing:
        branches.update({b.id: b for b in Branch.objects.filter(id__in=missing)})
    out_branches = []
    for bid, b in branches.items():
        t = per_branch.get(bid) or per_branch.default_factory()
        out_branches.append({
            'branch_id': bid, 'label': branch_label(b),
            'invoices': t['invoices'], 'amount': _money(t['amount']),
            'unattributed_invoices': t['unattributed_invoices'],
            'unattributed_amount': _money(t['unattributed_amount']),
            'share': round(float(t['unattributed_amount'] / t['amount']), 4) if t['amount'] else 0,
        })
    out_branches.sort(key=lambda x: (-x['amount'], x['label']))

    top = sorted(per_seller.items(), key=lambda kv: (-kv[1]['amount'], kv[0]))[:TOP_SELLERS]
    sellers = []
    for code, t in top:
        group, name = users.get(code, ('', ''))
        sellers.append({'code': code, 'name': name, 'group': group, 'group_name': group_names.get(group, ''),
                        'invoices': t['invoices'], 'amount': _money(t['amount']),
                        'generic': is_generic(code, rule, group_of)})
    return {'rule': rule, 'start': start.isoformat(), 'end': end.isoformat(),
            'branches': out_branches, 'sellers': sellers}
