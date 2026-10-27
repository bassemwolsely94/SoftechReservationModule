"""
apps/stock_audit/engine.py

Doc 32 Phase 2 — run the enabled checks over StockLedgerLine and upsert StockAuditFinding.

  • Per rule, per branch: effective params = defaults ⊕ chain ⊕ branch override (params.py).
  • Idempotent: findings are keyed (rule_code, dedup_key); re-runs refresh value/evidence/last_seen.
  • Review status is never reset by a re-run — except a DISMISSED finding whose value grew by more
    than REOPEN_GROWTH is reopened with a note.
  • Reads our Postgres mirror only (never SOFTECH). Deterministic.
"""
import datetime as _dt
import logging
from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.db.models import Min
from django.utils import timezone

from .params import effective, ensure_rules
from .rules import RULES, RuleContext

logger = logging.getLogger('elrezeiky.stock_audit')

REOPEN_GROWTH = Decimal('1.5')
_UPDATE_FIELDS = ['severity', 'branch', 'item', 'doccode', 'docnumber', 'docdate', 'occurred_at',
                  'softech_user', 'staff', 'personcode', 'value_egp', 'metric', 'threshold', 'evidence',
                  'message_ar', 'message_en', 'last_run', 'last_seen', 'status', 'review_note']


def build_context(date_from, date_to, report_from=None):
    """Names, exclusions, sales channel per invoice, returned invoices, stock rates and counts.
    `date_from` = earliest line any rule needs; `report_from` = first day findings are reported for."""
    from apps.branches.models import Branch
    from apps.catalog.models import Item, ItemStock
    from apps.customers.models import PurchaseHistory
    from apps.forecasting.models import ChannelBucketMap
    from apps.insights.rules import analytics_excluded_items
    from .models import StockLedgerLine

    branch_names = {b.softech_branch_id: (b.name_ar or b.name, b.name or b.name_ar)
                    for b in Branch.objects.all()}
    codes = set(StockLedgerLine.objects.filter(docdate__gte=date_from, docdate__lt=date_to)
                .values_list('itemcode', flat=True).distinct())
    item_names = dict(Item.objects.filter(softech_id__in=codes).values_list('softech_id', 'name'))
    channel_bucket = dict(ChannelBucketMap.objects.filter(active=True).values_list('channel', 'bucket'))
    channel_of_invoice = {}
    for bc, dn, d, ch in (PurchaseHistory.objects
                          .filter(doc_code='115', invoice_date__date__gte=date_from, invoice_date__date__lt=date_to)
                          .values_list('branch__softech_branch_id', 'docnumber', 'invoice_date', 'sales_channel')):
        try:
            channel_of_invoice[(bc, int(float(dn)), timezone.localtime(d).date() if timezone.is_aware(d) else d.date())] = ch
        except (TypeError, ValueError):
            continue
    returned = set(StockLedgerLine.objects
                   .filter(doccode='30', docdate__gte=date_from, r_docnumber__isnull=False, r_docdate__isnull=False)
                   .values_list('branchcode', 'r_docnumber', 'r_docdate'))
    report_from = report_from or date_from
    medicine_items = set(Item.objects.filter(softech_id__in=codes, medicine_type='10')
                         .values_list('softech_id', flat=True))
    monthly_qty, on_hand = {}, {}
    for bc, ic, rate, qty in (ItemStock.objects.filter(item__softech_id__in=medicine_items)
                              .values_list('branch__softech_branch_id', 'item__softech_id', 'monthly_qty',
                                           'quantity_on_hand')):
        monthly_qty[(bc, ic)] = rate or Decimal('0')
        on_hand[(bc, ic)] = qty
    sales, returns_total = _return_references(report_from, date_to)
    return RuleContext(date_from, date_to, item_names=item_names, branch_names=branch_names,
                       excluded_item_codes=set(analytics_excluded_items().values_list('softech_id', flat=True)),
                       channel_of_invoice=channel_of_invoice, channel_bucket=channel_bucket,
                       returned_invoices=returned, report_from=report_from, medicine_items=medicine_items,
                       monthly_qty=monthly_qty, on_hand=on_hand, sales=sales, returns_total=returns_total,
                       ledger_from=StockLedgerLine.objects.aggregate(m=Min('docdate'))['m'],
                       counts=_counted_rows(date_from - _dt.timedelta(days=30)),
                       branch_hours=_branch_hours())


def _branch_hours():
    """Check 9: working hours per branch code from BranchSettings (our own setting)."""
    from apps.branches.models import BranchSettings
    return {s.branch.softech_branch_id: {'is_24h': s.is_24h, 'windows': s.working_hours or []}
            for s in BranchSettings.objects.select_related('branch')}


def _return_references(report_from, date_to):
    """Check 10: for the sale invoices referenced by returns in the window — the qty sold on each
    (branch, docnumber, docdate, item), and the qty returned against it over ALL returns in the mirror."""
    from .models import StockLedgerLine
    refs = set(StockLedgerLine.objects.filter(doccode='30', docdate__gte=report_from, docdate__lt=date_to,
                                              r_docnumber__isnull=False, r_docdate__isnull=False)
               .values_list('branchcode', 'r_docnumber', 'r_docdate', 'itemcode'))
    if not refs:
        return {}, {}
    numbers = {r[1] for r in refs}
    sales = defaultdict(Decimal)
    for bc, dn, dd, ic, q in (StockLedgerLine.objects.filter(doccode='115', docnumber__in=numbers)
                              .values_list('branchcode', 'docnumber', 'docdate', 'itemcode', 'transqty')):
        if (bc, dn, dd, ic) in refs:
            sales[(bc, dn, dd, ic)] += q
    returns_total = defaultdict(Decimal)
    for bc, dn, dd, ic, q in (StockLedgerLine.objects.filter(doccode='30', r_docnumber__in=numbers)
                              .values_list('branchcode', 'r_docnumber', 'r_docdate', 'itemcode', 'transqty')):
        if (bc, dn, dd, ic) in refs:
            returns_total[(bc, dn, dd, ic)] += abs(q)
    return dict(sales), dict(returns_total)


def _counted_rows(since):
    """Check 11: counted stock-count rows (not expiry audits) whose snapshot is recent enough."""
    from apps.stockcount.models import StockCountSnapshot
    out = defaultdict(list)
    for r in (StockCountSnapshot.objects.filter(counted_qty__isnull=False, session__snapshot_at__isnull=False,
                                                session__snapshot_at__date__gte=since)
              .exclude(session__mode='expiry_audit')
              .values('session_id', 'session__branch_code', 'session__snapshot_at', 'item_code',
                      'expected_qty', 'counted_qty')):
        out[(r['session__branch_code'], r['item_code'])].append({
            'session_id': r['session_id'], 'snapshot_at': r['session__snapshot_at'],
            'expected': r['expected_qty'], 'counted': r['counted_qty'],
            'difference': r['counted_qty'] - r['expected_qty']})
    return dict(out)


def _lines_by_branch(date_from, date_to, doccodes, branches=None):
    from .models import StockLedgerLine
    qs = StockLedgerLine.objects.filter(docdate__gte=date_from, docdate__lt=date_to)
    if doccodes:
        qs = qs.filter(doccode__in=doccodes)
    if branches:
        qs = qs.filter(branchcode__in=branches)
    out = defaultdict(list)
    for l in qs.order_by('trans_time', 'id').iterator(chunk_size=5000):
        out[l.branchcode].append(l)
    return out


_SEV_RANK = {'info': 0, 'warning': 1, 'critical': 2}


def _merge_same_key(cands):
    """Candidates sharing a dedup_key in one run (e.g. split-expiry lines of one invoice, same price
    and second) become ONE finding: values summed, highest severity kept, evidence listed."""
    merged = {}
    for c in cands:
        m = merged.get(c['dedup_key'])
        if m is None:
            merged[c['dedup_key']] = c
            continue
        m['value_egp'] = m['value_egp'] + c['value_egp']
        if _SEV_RANK[c['severity']] > _SEV_RANK[m['severity']]:
            m['severity'] = c['severity']
        m['evidence'] = {**m['evidence'], 'merged': m['evidence'].get('merged', []) + [c['evidence']]}
    return list(merged.values())


def _upsert(code, cands, run, maps, now):
    """Insert new findings, refresh existing ones. Returns counts."""
    from .models import StockAuditFinding
    cands = _merge_same_key(cands)
    existing = {f.dedup_key: f for f in StockAuditFinding.objects.filter(
        rule_code=code, dedup_key__in=[c['dedup_key'] for c in cands])}
    new, updated, reopened = [], [], 0
    for c in cands:
        fields = dict(c)
        fields['branch_id'] = maps['branch'].get(fields.get('branchcode'))
        fields['item_id'] = maps['item'].get(fields.get('itemcode'))
        fields['staff_id'] = maps['staff'].get(fields.get('softech_user') or '')
        f = existing.get(c['dedup_key'])
        if f is None:
            new.append(StockAuditFinding(rule_code=code, first_run=run, last_run=run, last_seen=now, **fields))
            continue
        old_value = f.value_egp or Decimal('0')
        for k, v in fields.items():
            setattr(f, k, v)
        f.last_run, f.last_seen = run, now
        if f.status == StockAuditFinding.ST_DISMISSED and old_value > 0 and f.value_egp > old_value * REOPEN_GROWTH:
            f.status = StockAuditFinding.ST_OPEN
            note = (f'أعيد فتحها تلقائياً {now:%Y-%m-%d}: زادت القيمة من {old_value:,.2f} إلى {f.value_egp:,.2f} ج.م')
            f.review_note = f'{f.review_note}\n{note}'.strip()
            reopened += 1
        updated.append(f)
    with transaction.atomic():
        StockAuditFinding.objects.bulk_create(new, batch_size=1000)
        if updated:
            StockAuditFinding.objects.bulk_update(updated, _UPDATE_FIELDS, batch_size=1000)
    return {'new': len(new), 'updated': len(updated), 'reopened': reopened}


def _lookback_start(spec, p, date_from, date_to):
    """First docdate a rule needs: `lookback_from` 'report_from' = N days before the report window
    (check 4: the previous purchase); default 'date_to' = the last N days (checks 5 and 6)."""
    days = _dt.timedelta(days=int(p[spec['lookback_param']]))
    start = date_from - days if spec.get('lookback_from') == 'report_from' else date_to - days
    return min(start, date_from)


def run_stock_audit(days=30, rules=None, branches=None, today=None, triggered_by='', run=None):
    """
    Run the enabled checks over the ledger for docdate in [today − days + 1, tomorrow).
    `rules` / `branches` restrict the run. Returns the StockAuditRun.
    """
    from apps.branches.models import Branch
    from apps.catalog.models import Item
    from apps.users.models import StaffProfile
    from .models import StockAuditRuleOverride, StockAuditRun

    today = today or timezone.localdate()
    date_to = today + _dt.timedelta(days=1)
    date_from = date_to - _dt.timedelta(days=int(days))
    run = run or StockAuditRun.objects.create(triggered_by=triggered_by[:50])
    run.date_from, run.date_to = date_from, date_to

    rule_rows = ensure_rules()
    overrides = defaultdict(dict)
    for o in StockAuditRuleOverride.objects.select_related('branch', 'rule'):
        overrides[o.rule.code][o.branch.softech_branch_id] = o
    wanted = [c for c in RULES if not rules or c in rules]

    # widest window any enabled rule needs (checks 5/6 count over their own `days`, check 4 compares
    # with purchases up to `lookback_days` before the report window)
    widest = date_from
    for code in wanted:
        lp = RULES[code].get('lookback_param')
        if lp:
            for o in [None, *overrides[code].values()]:
                en, p = effective(rule_rows[code], o)
                if en:
                    widest = min(widest, _lookback_start(RULES[code], p, date_from, date_to))
    ctx = build_context(widest, date_to, report_from=date_from)
    maps = {
        'branch': dict(Branch.objects.values_list('softech_branch_id', 'id')),
        'item': dict(Item.objects.filter(softech_id__in=ctx.item_names).values_list('softech_id', 'id')),
        'staff': dict(StaffProfile.objects.exclude(softech_user_id='').values_list('softech_user_id', 'id')),
    }
    now = timezone.now()
    params_used, counts, failed = {}, {}, 0

    for code in wanted:
        spec = RULES[code]
        try:
            per_branch = {}
            loads = set()
            for o in [None, *overrides[code].values()]:
                en, p = effective(rule_rows[code], o)
                if en:
                    loads.update(spec['doccodes'] or [])
                    if spec['doccodes'] is not None and 'doccodes' in p:
                        loads.update(p['doccodes'])
            lp = spec.get('lookback_param')
            start = widest if lp else date_from
            lines = _lines_by_branch(start, date_to, sorted(loads) if spec['doccodes'] is not None else None, branches)
            cands = []
            for bc, ls in lines.items():
                en, p = effective(rule_rows[code], overrides[code].get(bc))
                if not en:
                    continue
                per_branch[bc] = p
                if lp:
                    cutoff = _lookback_start(spec, p, date_from, date_to)
                    ls = [l for l in ls if l.docdate >= cutoff]
                for c in spec['fn'](ls, p, ctx):
                    c['branchcode'] = bc
                    cands.append(c)
            res = _upsert(code, cands, run, maps, now)
            res['seen'] = len(cands)
            counts[code] = res
            params_used[code] = per_branch
        except Exception as e:
            failed += 1
            counts[code] = {'error': str(e)[:300]}
            logger.exception('[StockAudit] rule %s failed', code)

    run.params_used, run.counts = params_used, counts
    run.status = 'success' if failed == 0 else ('partial' if failed < len(wanted) else 'failed')
    run.finished_at = timezone.now()
    run.save()
    logger.info('[StockAudit] run #%s %s %s→%s: %s', run.pk, run.status, date_from, date_to, counts)
    return run
