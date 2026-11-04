"""Seed posting rules and source maps (Plan 2 / Task 7).

Idempotent: a rule is created only when its ``code`` has no version at all (so finance edits are
never overwritten); a map only when its ``(kind, source_value)`` is absent. Anything whose account
(or branch) does not exist yet is skipped and reported under ``result['skipped']`` instead of
raising (Ruling P5) - run the seed again after the chart of accounts is imported.
"""
import datetime

from apps.branches.models import Branch
from apps.finance.models import GLAccount, GLSourceMap, PostingRule

from .rules import RuleError, save_map, save_rule

EFFECTIVE_FROM = datetime.date(2026, 1, 1)

BANK_MAPS = [   # (bankcode, account, branch softech_branch_id or None, note)
    ('10', '1301', '100', 'خزينة المركز الرئيسي'),
    ('40', '1302', '130', 'خزينة فرع'), ('50', '1302', '140', 'خزينة فرع'),
    ('60', '1302', '150', 'خزينة فرع'), ('70', '1302', '160', 'خزينة فرع'),
    ('80', '1302', '170', 'خزينة فرع'),
    ('04', '1310', '100', 'حساب بنكي للشركة'), ('06', '1308', '100', 'حساب بنكي للشركة'),
    ('01', '1316', '100', 'حساب بنكي للشركة'),
]
EXPENSE_MAPS = [   # name-verified only; every other expcode raises unmapped_account
    ('92', '3173'), ('45', '3113'), ('46', '3116'), ('47', '3169'), ('108', '3119'),
    ('11', '3112'), ('16', '3114'), ('14', '3115'), ('19', '3111'), ('17', '3125'),
    ('10', '3117'), ('102', '3188'), ('97', '3156'), ('50', '3122'), ('86', '3200'),
    ('32', '1304'), ('109', '1351'),
]


def _ln(side, amount, account=None, *, map=None, key=None, branch='source', party=None,
        cheque=False, description=''):
    d = {'side': side, 'amount': amount, 'branch': branch}
    if map:
        d.update(account_map=map, map_key=key)
    else:
        d['account'] = account
    if party:
        d['party'] = party
    if cheque:
        d['cheque'] = True
    if description:
        d['description'] = description
    return d


_BANK = dict(map='bank', key='bankcode', branch='map')

RULES = [
    dict(code='sales.cash', source_type='sales_tenders', granularity='branch_day', book='cash',
         conditions={'kind_in': ['cash'], 'branch_not_in': ['100']},
         lines=[_ln('debit', 'net', '1302', description='مبيعات نقدية {branch} {date}'),
                _ln('credit', 'net', '6002')]),
    dict(code='sales.hq_store', source_type='sales_tenders', granularity='branch_day', book='cash',
         conditions={'kind_in': ['cash'], 'branch_in': ['100']},
         lines=[_ln('debit', 'net', '1301', branch='hq', description='مبيعات نقدية المركز {date}'),
                _ln('credit', 'net', '6011', branch='hq')]),
    dict(code='sales.card', source_type='sales_tenders', granularity='branch_day', book='cash',
         conditions={'kind_in': ['card']},
         lines=[_ln('debit', 'net', map='card_clearing', key='branch_code', branch='map',
                    description='مبيعات بطاقات {branch} {date}'),
                _ln('credit', 'net', '6006')]),
    dict(code='sales.change_discount', source_type='sales_tenders', granularity='branch_day',
         book='cash', conditions={'kind_in': ['change_discount']},
         lines=[_ln('debit', 'net', '6022'), _ln('credit', 'net', '6002')]),
    dict(code='sales.credit', source_type='credit_sales', granularity='party_day', book='credit',
         conditions={},
         lines=[_ln('debit', 'credit', '1341', branch='hq', party='source',
                    description='مبيعات آجلة {party} {date}'),
                _ln('credit', 'credit', '6003', branch='hq'),
                _ln('debit', 'discount_share', '6021', branch='hq'),
                _ln('credit', 'discount_share', '6003', branch='hq')]),
    dict(code='purchases.hq', source_type='purchases', granularity='document', book='credit',
         conditions={'branch_in': ['100'], 'kind_in': ['invoice']},
         lines=[_ln('debit', 'value', '5104', branch='hq', description='مشتريات {docnumber}'),
                _ln('credit', 'value', '2341', branch='hq', party='source')]),
    dict(code='purchases.hq_return', source_type='purchases', granularity='document', book='credit',
         conditions={'branch_in': ['100'], 'kind_in': ['return']},
         lines=[_ln('debit', 'value', '2341', branch='hq', party='source',
                    description='مرتجع مشتريات {docnumber}'),
                _ln('credit', 'value', '5105', branch='hq')]),
    dict(code='purchases.branch', source_type='purchases', granularity='document', book='credit',
         action='skip', conditions={'branch_not_in': ['100']}, lines=[],
         description='تُسجل عند السداد النقدي من خزينة الفرع'),
    dict(code='supplier.cash', source_type='supplier_payments', granularity='branch_day', book='cash',
         conditions={'financialdoc_in': ['10'], 'direction_in': ['payment']},
         lines=[_ln('debit', 'amount', '5100', branch='map', description='سداد موردين نقداً {branch} {date}'),
                _ln('credit', 'amount', **_BANK)]),
    dict(code='supplier.cheque', source_type='supplier_payments', granularity='document',
         book='credit', conditions={'financialdoc_in': ['20'], 'direction_in': ['payment']},
         lines=[_ln('debit', 'amount', '2341', branch='hq', party='source',
                    description='شيك مورد {cheqno}'),
                _ln('credit', 'amount', '2343', branch='hq', cheque=True)]),
    dict(code='cheque.maturity', source_type='cheque_maturity', granularity='document',
         book='general', conditions={'direction_in': ['payment']},
         lines=[_ln('debit', 'amount', '2343', branch='hq', cheque=True,
                    description='استحقاق شيك {cheqno}'),
                _ln('credit', 'amount', **_BANK)]),
    dict(code='customer.collection', source_type='customer_collections', granularity='document',
         book='general', conditions={'financialdoc_in': ['10', '20'], 'direction_in': ['receipt']},
         lines=[_ln('debit', 'amount', description='تحصيل عميل {cheqno}', **_BANK),
                _ln('credit', 'amount', '1341', branch='hq', party='source')]),
    dict(code='expenses.box', source_type='expenses', granularity='branch_day', book='cash',
         conditions={},
         lines=[_ln('debit', 'amount', map='expense', key='expcode',
                    description='مصروفات {branch} {date}'),
                _ln('credit', 'amount', **_BANK)]),
    dict(code='treasury.transfer_in', source_type='treasury_other', granularity='document',
         book='general', conditions={'kind_in': ['transfer'], 'direction_in': ['receipt']},
         lines=[_ln('debit', 'amount', description='تحويل خزينة وارد {cheqno}', **_BANK),
                _ln('credit', 'amount', '1320', branch='hq')]),
    dict(code='treasury.transfer_out', source_type='treasury_other', granularity='document',
         book='general', conditions={'kind_in': ['transfer'], 'direction_in': ['payment']},
         lines=[_ln('debit', 'amount', '1320', branch='hq', description='تحويل خزينة صادر {cheqno}'),
                _ln('credit', 'amount', **_BANK)]),
]


def _rule_accounts(rule):
    return sorted({ln['account'] for ln in rule['lines'] if ln.get('account')})


def _missing(codes):
    have = set(GLAccount.objects.filter(code__in=list(codes)).values_list('code', flat=True))
    return sorted(set(codes) - have)


def seed_gl_drafting(*, user) -> dict:
    result = {'rules_created': [], 'rules_existing': [], 'maps_created': [], 'maps_existing': [],
              'skipped': []}
    for r in RULES:
        if PostingRule.objects.filter(code=r['code']).exists():
            result['rules_existing'].append(r['code'])
            continue
        gone = _missing(_rule_accounts(r))
        if gone:
            result['skipped'].append({'what': 'rule', 'code': r['code'],
                                      'reason': 'missing_account', 'accounts': gone})
            continue
        try:
            save_rule(user=user, effective_from=EFFECTIVE_FROM, priority=100, **r)
        except RuleError as e:
            result['skipped'].append({'what': 'rule', 'code': r['code'], 'reason': 'invalid',
                                      'errors': e.errors})
            continue
        result['rules_created'].append(r['code'])

    entries = ([('bank', code, acc, br, note) for code, acc, br, note in BANK_MAPS]
               + [('expense', code, acc, None, '') for code, acc in EXPENSE_MAPS])
    for kind, value, acc, branch_code, note in entries:
        label = f'{kind}:{value}'
        if GLSourceMap.objects.filter(kind=kind, source_value=value).exists():
            result['maps_existing'].append(label)
            continue
        if _missing([acc]):
            result['skipped'].append({'what': 'map', 'code': label, 'reason': 'missing_account',
                                      'accounts': [acc]})
            continue
        branch_id = None
        if branch_code:
            br = Branch.objects.filter(softech_branch_id=branch_code).first()
            if br is None:
                result['skipped'].append({'what': 'map', 'code': label, 'reason': 'missing_branch',
                                          'branch_code': branch_code})
                continue
            branch_id = br.pk
        try:
            save_map(user=user, kind=kind, source_value=value, account_code=acc,
                     branch_id=branch_id, note=note)
        except RuleError as e:
            result['skipped'].append({'what': 'map', 'code': label, 'reason': 'invalid',
                                      'errors': e.errors})
            continue
        result['maps_created'].append(label)
    return result
