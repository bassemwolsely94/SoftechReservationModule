"""Versioned posting rules and source maps (Plan 2 / Task 3).

Rules decide amounts from a fixed per-source whitelist of fields (no expressions, no LLM, no fuzzy
matching). Editing a rule creates a new version; maps are audited with before/after. Nothing here
writes ledger entries or touches SOFTECH: ``build_lines`` returns Plan 1 ``save_draft`` line dicts.
"""
from collections import OrderedDict
from contextlib import ExitStack
from datetime import date, datetime, timedelta
from decimal import Decimal
from string import Formatter

from django.db import transaction

from apps.branches.models import Branch
from apps.finance.models import GLAccount, GLSourceMap, PostingRule
from .parties import _audit, resolve_party
from .sources import READERS, SourceDoc

SOURCE_FIELDS = {
    'sales_tenders': ('net', 'sales', 'returns'),
    'credit_sales': ('credit', 'gross_share', 'discount_share', 'tax_share'),
    'purchases': ('value',),
    'supplier_payments': ('amount',),
    'cheque_maturity': ('amount',),
    'customer_collections': ('amount',),
    'expenses': ('amount',),
    'treasury_other': ('amount',),
}
_ALL = tuple(SOURCE_FIELDS)
_CHEQUES = ('supplier_payments', 'cheque_maturity', 'customer_collections', 'treasury_other')

# condition key -> source types it applies to
CONDITION_KEYS = {
    'branch_in': _ALL, 'branch_not_in': _ALL, 'kind_in': _ALL,
    'paymenttype_in': ('sales_tenders',),
    'doccode_in': ('purchases', 'credit_sales'),
    'financialdoc_in': _CHEQUES, 'direction_in': _CHEQUES, 'bank_type_in': _CHEQUES,
    'expcode_in': ('expenses',),
}
# condition key -> where the doc value lives
_COND_SOURCE = {
    'branch_in': ('attr', 'branch_code'), 'branch_not_in': ('attr', 'branch_code'),
    'kind_in': ('attr', 'kind'), 'paymenttype_in': ('attrs', 'paymenttype'),
    'doccode_in': ('attrs', 'doccode'), 'financialdoc_in': ('attrs', 'financialdoc'),
    'direction_in': ('attrs', 'direction'), 'bank_type_in': ('attrs', 'bank_type'),
    'expcode_in': ('attrs', 'expcode'),
}
# Ruling P14: static-account line with branch 'map' = branch of the doc's bank map
BANK_BRANCH_SOURCES = ('supplier_payments', 'customer_collections', 'cheque_maturity',
                       'treasury_other', 'expenses')
MAP_KINDS = ('bank', 'expense', 'card_clearing')
MAP_KEYS = ('bankcode', 'expcode', 'branch_code')
PLACEHOLDERS = ('branch', 'date', 'docnumber', 'cheqno', 'party')
BRANCH_MODES = ('source', 'hq', 'map', 'none')
PARTY_MODES = ('source', 'none')

_MISS_MESSAGES = {
    'no_rule': 'لا توجد قاعدة ترحيل مطابقة لهذا المستند',
    'ambiguous_rule': 'أكثر من قاعدة بنفس الأولوية تنطبق على هذا المستند',
    'unmapped_account': 'حساب أو فرع غير مربوط لهذا المستند',
    'unmapped_party': 'طرف غير مربوط أو غير مؤكد لهذا المستند',
    'unbalanced_rule': 'أسطر القاعدة غير متوازنة لهذا المستند',
}


class RuleMiss(Exception):
    def __init__(self, kind, detail=None):
        self.kind = kind
        self.detail = detail or {}
        self.message = _MISS_MESSAGES.get(kind, kind)
        super().__init__(f'{kind}: {self.detail}')


class RuleError(Exception):
    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__('; '.join(self.errors))


def _q2(v):
    return Decimal(v).quantize(Decimal('0.01'))


# ── validation ────────────────────────────────────────────────────────────────

def validate_rule(source_type, conditions, lines, action) -> list:
    errs = []
    if source_type not in SOURCE_FIELDS:
        return [f'نوع المصدر غير معروف: {source_type}']
    if action not in ('post', 'skip'):
        errs.append(f'إجراء غير معروف: {action}')
    for key, vals in (conditions or {}).items():
        if key not in CONDITION_KEYS:
            errs.append(f'شرط غير معروف: {key}')
        elif source_type not in CONDITION_KEYS[key]:
            errs.append(f'الشرط {key} لا ينطبق على {source_type}')
        elif not isinstance(vals, (list, tuple)) or not all(isinstance(x, str) for x in vals):
            errs.append(f'قيم الشرط {key} يجب أن تكون قائمة نصوص')
    lines = lines or []
    if action == 'skip':
        if lines:
            errs.append('قاعدة التجاهل لا تحتوي أسطراً')
        return errs
    sides = set()
    for i, ln in enumerate(lines, start=1):
        p = f'السطر {i}: '
        if not isinstance(ln, dict):
            errs.append(p + 'صيغة غير صحيحة')
            continue
        side = ln.get('side')
        if side not in ('debit', 'credit'):
            errs.append(p + 'الجهة يجب أن تكون debit أو credit')
        else:
            sides.add(side)
        if ln.get('amount') not in SOURCE_FIELDS[source_type]:
            errs.append(p + f'حقل المبلغ غير معروف: {ln.get("amount")}')
        static_acc = None
        if ln.get('account_map'):
            if ln['account_map'] not in MAP_KINDS:
                errs.append(p + f'نوع الربط غير معروف: {ln["account_map"]}')
            if ln.get('map_key') not in MAP_KEYS:
                errs.append(p + f'مفتاح الربط غير معروف: {ln.get("map_key")}')
            if ln.get('account'):
                errs.append(p + 'حدد حساباً ثابتاً أو ربطاً وليس كليهما')
        elif ln.get('account'):
            static_acc = GLAccount.objects.filter(code=str(ln['account'])).first()
            if static_acc is None:
                errs.append(p + f'الحساب {ln["account"]} غير موجود')
            elif not static_acc.is_active:
                errs.append(p + f'الحساب {ln["account"]} غير نشط')
            elif not static_acc.is_posting:
                errs.append(p + f'الحساب {ln["account"]} لا يقبل الترحيل')
        else:
            errs.append(p + 'الحساب مطلوب')
        if ln.get('branch', 'source') not in BRANCH_MODES:
            errs.append(p + f'قيمة الفرع غير معروفة: {ln.get("branch")}')
        elif (ln.get('branch') == 'map' and not ln.get('account_map')
              and source_type not in BANK_BRANCH_SOURCES):
            errs.append(p + 'الفرع map على حساب ثابت غير متاح لهذا المصدر')
        if ln.get('party', 'none') not in PARTY_MODES:
            errs.append(p + f'قيمة الطرف غير معروفة: {ln.get("party")}')
        elif ln.get('party') == 'source' and static_acc is not None and static_acc.party_type == 'none':
            errs.append(p + f'الحساب {static_acc.code} ليس حساب طرف')
        try:
            names = [n for _, n, _, _ in Formatter().parse(ln.get('description') or '') if n is not None]
        except ValueError:
            names = ['?']
        for name in names:
            if name not in PLACEHOLDERS:
                errs.append(p + f'متغير غير مسموح في البيان: {{{name}}}')
    if not ('debit' in sides and 'credit' in sides):
        errs.append('قاعدة الترحيل تحتاج سطر مدين وسطر دائن على الأقل')
    return errs


# ── versioned save ────────────────────────────────────────────────────────────

def save_rule(*, user, code, source_type, effective_from, conditions, lines, action='post',
              granularity='document', book='general', priority=100, description='') -> PostingRule:
    errs = validate_rule(source_type, conditions, lines, action)
    if granularity not in dict(PostingRule.GRANULARITY_CHOICES):
        errs.append(f'تجميع غير معروف: {granularity}')
    if book not in dict(PostingRule.BOOK_CHOICES):
        errs.append(f'دفتر غير معروف: {book}')
    if errs:
        raise RuleError(errs)
    with transaction.atomic():
        current = (PostingRule.objects.select_for_update().filter(code=code)
                   .order_by('-version').first())
        version, old = 1, None
        if current:
            if effective_from <= current.effective_from:
                raise RuleError(['تاريخ السريان يجب أن يكون بعد تاريخ سريان الإصدار الحالي'])
            old = {'version': current.version,
                   'effective_to': current.effective_to.isoformat() if current.effective_to else None}
            last_day = effective_from - timedelta(days=1)
            if current.effective_to is None or current.effective_to > last_day:
                current.effective_to = last_day
                current.save(update_fields=['effective_to'])
            version = current.version + 1
        rule = PostingRule.objects.create(
            code=code, version=version, source_type=source_type, description=description,
            conditions=conditions or {}, action=action, granularity=granularity,
            lines=lines or [], book=book, priority=priority, effective_from=effective_from,
            created_by=user)
        _audit('gl_rule_saved', user=user, obj=rule, old_data=old,
               new_data={'code': code, 'version': version, 'source_type': source_type,
                         'effective_from': effective_from.isoformat(), 'action': action,
                         'conditions': conditions or {}, 'lines': lines or []})
    return rule


# ── selection ─────────────────────────────────────────────────────────────────

def rule_matches(rule, doc: SourceDoc) -> bool:
    if rule.source_type != doc.source_type:
        return False
    if doc.doc_date < rule.effective_from:
        return False
    if rule.effective_to and doc.doc_date > rule.effective_to:
        return False
    for key, vals in (rule.conditions or {}).items():
        where, name = _COND_SOURCE[key]
        v = getattr(doc, name) if where == 'attr' else doc.attrs.get(name)
        v = '' if v is None else str(v)
        inside = v in [str(x) for x in vals]
        if key.endswith('_not_in'):
            if inside:
                return False
        elif not inside:
            return False
    return True


def select_rule(doc: SourceDoc, rules) -> PostingRule:
    hits = [r for r in rules if r.is_active and rule_matches(r, doc)]
    if not hits:
        raise RuleMiss('no_rule', {'source_type': doc.source_type})
    top = max(r.priority for r in hits)
    best = [r for r in hits if r.priority == top]
    if len(best) > 1:
        raise RuleMiss('ambiguous_rule', {'rules': sorted(str(r) for r in best), 'priority': top})
    return best[0]


# ── line building ─────────────────────────────────────────────────────────────

def _as_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str) and v:
        return date.fromisoformat(v[:10])
    return v or None


def build_lines(rule, docs, *, hq_branch_id) -> list:
    branches, maps, accounts = {}, {}, {}

    def branch_for(code):
        if code not in branches:
            branches[code] = Branch.objects.filter(softech_branch_id=str(code)).first()
        if branches[code] is None:
            raise RuleMiss('unmapped_account', {'branch_code': str(code)})
        return branches[code]

    names = {}

    def branch_name(code):   # Ruling P18: display name, never the bare SOFTECH code
        if code not in names:
            b = branches.get(code) or Branch.objects.filter(softech_branch_id=str(code)).first()
            names[code] = ((b.name_ar or b.name) if b else '') or str(code)
        return names[code]

    def account(code):
        if code not in accounts:
            accounts[code] = GLAccount.objects.filter(code=str(code)).first()
        a = accounts[code]
        if a is None or not a.is_active or not a.is_posting:
            raise RuleMiss('unmapped_account', {'account': str(code)})
        return a

    def mapped(kind, value):
        if (kind, value) not in maps:
            maps[(kind, value)] = (GLSourceMap.objects.select_related('account')
                                   .filter(kind=kind, source_value=value).first())
        m = maps[(kind, value)]
        if m is None:
            raise RuleMiss('unmapped_account', {'kind': kind, 'key': value, 'value': value})
        return m

    sums = OrderedDict()   # key -> [amount, description]
    for doc in docs:
        for ln in rule.lines:
            m = None
            if ln.get('account_map'):
                mk = ln.get('map_key')
                value = doc.branch_code if mk == 'branch_code' else doc.attrs.get(mk)
                m = mapped(ln['account_map'], '' if value is None else str(value))
                acc = account(m.account.code)
            else:
                acc = account(ln['account'])
            mode = ln.get('branch', 'source')
            if mode == 'source':
                branch_id = branch_for(doc.branch_code).pk
            elif mode == 'hq':
                branch_id = hq_branch_id
            elif mode == 'map':
                if m is not None:
                    src, branch_id = m, m.branch_id
                else:   # static account: the paying/receiving box's branch (Ruling P14)
                    bank = doc.attrs.get('bankcode')
                    src = mapped('bank', '' if bank is None else str(bank))
                    branch_id = src.branch_id
                if branch_id is None:   # Ruling P15: never a NULL branch through a map
                    raise RuleMiss('unmapped_account', {'kind': src.kind, 'value': src.source_value,
                                                        'reason': 'map has no branch'})
            else:
                branch_id = None
            party_code = ''
            if ln.get('party') == 'source':
                party = resolve_party(acc.party_type, doc.personcode) if acc.party_type != 'none' else None
                if party is None:
                    raise RuleMiss('unmapped_party', {'personcode': doc.personcode,
                                                      'party_type': acc.party_type})
                party_code = party.code
            cheque_no, due = '', None
            if ln.get('cheque'):
                cheque_no = str(doc.attrs.get('cheqno') or '')
                due = _as_date(doc.attrs.get('due_date'))
            amount = Decimal(doc.amounts.get(ln['amount'], 0) or 0)
            key = (ln['side'], acc.code, branch_id, party_code, cheque_no, due)
            desc = (ln.get('description') or '').format(
                branch=branch_name(doc.branch_code), date=doc.doc_date.isoformat(),
                docnumber=doc.attrs.get('docnumber', ''), cheqno=doc.attrs.get('cheqno', ''),
                party=party_code or doc.personcode)
            if key in sums:
                sums[key][0] += amount
            else:
                sums[key] = [amount, desc]
    out = []
    for (side, code, branch_id, party_code, cheque_no, due), (amount, desc) in sums.items():
        amount = _q2(amount)
        if amount == 0:
            continue
        if amount < 0:
            side, amount = ('credit' if side == 'debit' else 'debit'), -amount
        out.append({'account_code': code, 'debit': amount if side == 'debit' else Decimal('0'),
                    'credit': amount if side == 'credit' else Decimal('0'),
                    'branch_id': branch_id, 'party_code': party_code, 'description': desc,
                    'cheque_no': cheque_no, 'due_date': due})
    td, tc = sum(l['debit'] for l in out), sum(l['credit'] for l in out)
    if td != tc:
        raise RuleMiss('unbalanced_rule', {'debit': str(td), 'credit': str(tc)})
    return out


# ── preview ───────────────────────────────────────────────────────────────────

def _group_key(rule, doc):
    if rule.granularity == 'branch_day':
        return (doc.branch_code, doc.doc_date)
    if rule.granularity == 'party_day':
        return (doc.personcode, doc.doc_date)
    return (doc.source_key,)


def preview_rule(rule_or_draft, date_from, date_to, *, fetch=None, readers=None, hq_branch_id=None) -> dict:
    """Dry run for the «تجربة» button: reader + build_lines, nothing saved."""
    if isinstance(rule_or_draft, PostingRule):
        rule = rule_or_draft
    else:
        d = dict(rule_or_draft)
        d.setdefault('effective_from', date_from)
        errs = validate_rule(d.get('source_type'), d.get('conditions'), d.get('lines'),
                             d.get('action', 'post'))
        if errs:
            raise RuleError(errs)
        d.setdefault('code', 'preview')
        rule = PostingRule(**d)
    readers = READERS if readers is None else readers
    reader = readers.get(rule.source_type)
    if reader is None:
        raise RuleError([f'لا يوجد قارئ لنوع المصدر {rule.source_type}'])
    if hq_branch_id is None:
        hq = Branch.objects.filter(softech_branch_id='100').first()
        hq_branch_id = hq.pk if hq else None
    with ExitStack() as stack:
        if fetch is None:   # real path: one SOFTECH connection, opened only if the reader fetches
            holder = {}

            def fetch(sql):
                if 'f' not in holder:
                    from apps.finance.queries.sybase_gl import open_fetch   # lazy: gl/ never imports config.sybase at load
                    holder['f'] = stack.enter_context(open_fetch())
                return holder['f'](sql)
        docs = [d for d in reader(date_from, date_to, fetch) if rule_matches(rule, d)]
    groups = OrderedDict()
    for d in docs:
        groups.setdefault(_group_key(rule, d), []).append(d)
    entries, exceptions = [], []
    skipped = len(docs) if rule.action == 'skip' else 0
    if rule.action == 'post':
        for key, group in groups.items():
            try:
                lines = build_lines(rule, group, hq_branch_id=hq_branch_id)
            except RuleMiss as miss:
                for d in group:
                    exceptions.append({'source_key': d.source_key, 'kind': miss.kind,
                                       'detail': miss.detail, 'message': miss.message})
                continue
            if lines:
                entries.append({'key': [str(k) for k in key], 'entry_date': group[0].doc_date,
                                'source_keys': [d.source_key for d in group], 'lines': lines})
    td = sum((l['debit'] for e in entries for l in e['lines']), Decimal('0'))
    tc = sum((l['credit'] for e in entries for l in e['lines']), Decimal('0'))
    return {'entries': entries, 'exceptions': exceptions,
            'totals': {'docs': len(docs), 'entries': len(entries), 'skipped': skipped,
                       'exceptions': len(exceptions), 'debit': td, 'credit': tc}}


# ── source maps ───────────────────────────────────────────────────────────────

def save_map(*, user, kind, source_value, account_code, branch_id=None, note='') -> GLSourceMap:
    if kind not in MAP_KINDS:
        raise RuleError([f'نوع الربط غير معروف: {kind}'])
    acc = GLAccount.objects.filter(code=str(account_code)).first()
    if acc is None or not acc.is_active or not acc.is_posting:
        raise RuleError([f'الحساب {account_code} غير موجود أو لا يقبل الترحيل'])
    if branch_id and not Branch.objects.filter(pk=branch_id).exists():
        raise RuleError([f'الفرع {branch_id} غير موجود'])

    def snap(m):
        return {'kind': m.kind, 'source_value': m.source_value, 'account': m.account.code,
                'branch_id': m.branch_id, 'note': m.note}
    with transaction.atomic():
        existing = (GLSourceMap.objects.select_for_update().select_related('account')
                    .filter(kind=kind, source_value=str(source_value)).first())
        before = snap(existing) if existing else None
        m = existing or GLSourceMap(kind=kind, source_value=str(source_value))
        m.account, m.branch_id, m.note, m.updated_by = acc, branch_id or None, note, user
        m.save()
        m.refresh_from_db()
        _audit('gl_map_saved', user=user, obj=m, old_data=before, new_data=snap(m))
    return m
