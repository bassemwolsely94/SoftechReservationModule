"""
apps/stock_audit/discount_policy.py — C07 (audit doc 08, P-36): the discount policy-breach PREVIEW.

Read-only. Computes check 12 (rules.check_discount_above_policy) live over a short window of the
ledger mirror for the branches the user may see, stores nothing, and labels every number
"unvalidated". It exists so finance can check samples against SOFTECH before the owner switches the
rule on (it ships disabled, so until then there are no findings, tasks or digest items). It never
changes a discount, a price or SOFTECH.
"""
import datetime as _dt
from collections import defaultdict
from decimal import Decimal

from django.utils import timezone

from .rules import RULES, RuleContext

CODE = 'discount_above_policy'
MAX_DAYS = 31
SAMPLE_SIZE = 20

# What finance checks before the rule may be switched on (also the PR's owner questions).
VALIDATION_STEPS = [
    {'ar': 'افتح 20 فاتورة من «عينات للمراجعة» في SOFTECH وقارن خصم العميل على السطر بالمعروض هنا.',
     'en': 'Open the 20 "samples to check" invoices in SOFTECH and compare the line customer discount with the one shown here.'},
    {'ar': 'لكل عينة: هل الخصم ده سياسة (فئة العميل / عقد / عرض) ولا خصم يدوي من الكاشير؟',
     'en': 'For each sample: is the discount policy (customer class / contract / offer) or a manual cashier discount?'},
    {'ar': 'سجّل نسبة خصم كل فئة عميل لكل قناة في «خصم الفئة لكل قناة» (مثال 30:12) في إعدادات الفحص.',
     'en': 'Enter each customer class discount per channel in "class discount per channel" (e.g. 30:12) in the check settings.'},
    {'ar': 'أكّد القنوات المستبعدة (10 تعاقد، 16 تبرعات، 17 تعويضات) وحد السماح.',
     'en': 'Confirm the excluded channels (10 contract, 16 donations, 17 compensations) and the tolerance.'},
    {'ar': 'بعد ما العينات تطابق، الإدارة تشغّل الفحص من الإعدادات فتظهر الملاحظات في «المبيعات والأسعار».',
     'en': 'Once the samples match, management switches the check on in settings and findings appear under "Sales & prices".'},
]


def _context(d_from, d_to, codes):
    from apps.branches.models import Branch
    from apps.catalog.models import Item
    from apps.customers.models import PurchaseHistory
    from apps.insights.rules import analytics_excluded_items

    channel, cust = {}, {}
    for bc, dn, d, ch, disc in (PurchaseHistory.objects
                                .filter(doc_code='115', invoice_date__date__gte=d_from, invoice_date__date__lt=d_to)
                                .values_list('branch__softech_branch_id', 'docnumber', 'invoice_date',
                                             'sales_channel', 'customer__discount_percent')):
        try:
            key = (bc, int(float(dn)), timezone.localtime(d).date() if timezone.is_aware(d) else d.date())
        except (TypeError, ValueError):
            continue
        channel[key] = ch
        if disc:
            cust[key] = disc
    return RuleContext(
        d_from, d_to,
        item_names=dict(Item.objects.filter(softech_id__in=codes).values_list('softech_id', 'name')),
        branch_names={b.softech_branch_id: (b.name_ar or b.name, b.name or b.name_ar) for b in Branch.objects.all()},
        excluded_item_codes=set(analytics_excluded_items().values_list('softech_id', flat=True)),
        channel_of_invoice=channel, customer_disc_of_invoice=cust,
        item_ceiling=dict(Item.objects.filter(softech_id__in=codes, pos_discp__gt=0)
                          .values_list('softech_id', 'pos_discp')))


def preview(acc, d_from, d_to, branches=None, user_names=None):
    """Live check-12 result for [d_from, d_to] (inclusive, ≤ MAX_DAYS) over the user's branches."""
    from .models import StockLedgerLine
    from .params import effective, ensure_rules

    rule = ensure_rules()[CODE]
    enabled, params = effective(rule)
    end = d_to + _dt.timedelta(days=1)
    qs = acc.scope(StockLedgerLine.objects.filter(doccode='115', docdate__gte=d_from, docdate__lt=end,
                                                  transqty__gt=0, custdiscp__gt=0))
    if branches:
        qs = qs.filter(branchcode__in=branches)
    lines = list(qs.order_by('docdate', 'docnumber', 'itemcode'))
    ctx = _context(d_from, end, {l.itemcode for l in lines})
    by_branch_lines = defaultdict(list)
    for l in lines:
        by_branch_lines[l.branchcode].append(l)
    cands = []
    for bc, ls in by_branch_lines.items():
        for c in RULES[CODE]['fn'](ls, params, ctx):
            c['branchcode'] = bc
            cands.append(c)

    def group(key_fn, label_fn):
        acc_ = defaultdict(lambda: {'lines': 0, 'excess_egp': Decimal('0')})
        for c in cands:
            k = key_fn(c)
            acc_[k]['lines'] += 1
            acc_[k]['excess_egp'] += c['value_egp']
        return sorted(({'key': k, 'label': label_fn(k), **v} for k, v in acc_.items()),
                      key=lambda r: -r['excess_egp'])

    names = user_names(c['softech_user'] for c in cands) if user_names else {}
    total = sum((c['value_egp'] for c in cands), Decimal('0'))
    step = max(1, len(cands) // SAMPLE_SIZE)
    samples = [_sample(c, ctx) for c in cands[::step][:SAMPLE_SIZE]]
    return {
        'unvalidated': True, 'rule_enabled': enabled, 'params': params,
        'from': d_from, 'to': d_to,
        'lines_with_discount': len(lines), 'breach_lines': len(cands), 'excess_egp': total,
        'by_branch': group(lambda c: c['branchcode'], lambda k: ctx.branch(k)),
        'by_user': group(lambda c: c['softech_user'] or '', lambda k: names.get(k, '') or k or '—')[:30],
        'by_item': group(lambda c: c['itemcode'], lambda k: ctx.item(k))[:30],
        'samples': samples,
        'validation_steps': VALIDATION_STEPS,
    }


def _sample(c, ctx):
    ev = c['evidence']
    return {'branchcode': c['branchcode'], 'branch_name': ctx.branch(c['branchcode']),
            'docnumber': c['docnumber'], 'docdate': c['docdate'], 'itemcode': c['itemcode'],
            'item_name': ctx.item(c['itemcode']), 'softech_user': c['softech_user'],
            'channel': ev.get('channel'), 'actual_pct': ev['actual_pct'], 'expected_pct': ev['expected_pct'],
            'item_ceiling_pct': ev['item_ceiling_pct'], 'class_pct': ev['class_pct'],
            'customer_pct': ev['customer_pct'], 'excess_egp': c['value_egp']}
