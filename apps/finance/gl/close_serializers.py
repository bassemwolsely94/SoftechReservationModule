"""JSON shapes for the close and reconcile API (Plan 3 / Task 10). Decimals leave as strings, dates as ISO."""
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.finance.models import FinancialPeriod
from apps.finance.recon_labels import branch_label

from . import close, ledger, softech_stock
from .views import _branch_label, _j

GENERIC_CLOSE_FAILURE = 'الإقفال وقف بسبب خطأ غير متوقع، جرّب تاني أو بلّغ الدعم (مرجع: {ref}).'
# every step of a close leaves one of these; only the last one says where the month stands
CLOSE_EVENTS = ('gl_period_closing', 'gl_period_close_takeover', 'gl_period_close_failed', 'gl_period_closed',
                'gl_period_reopened')
REFRESH_FAILED = 'gl_comparison_refresh_failed'
REFRESH_EVENTS = ('gl_comparison_computed', REFRESH_FAILED)
REFRESH_MESSAGES = {'compare_running': 'فيه تحديث تاني للمقارنة كان شغال، فالتحديث ده ماتنفذش.',
                    'softech_unavailable': 'تعذرت القراءة من سوفتيك، جرّب تاني.'}


def reopen_info() -> dict:
    """{period id: labels of the later closed months that reopen with it}, for the months inside the window."""
    closed = list(FinancialPeriod.objects.filter(period_type='month', status='closed')
                  .order_by('-period_start').values_list('pk', 'label')[:close._reopen_window()])
    return {pk: [label for _, label in reversed(closed[:i])] for i, (pk, _) in enumerate(closed)}


def period_json(p, reopen=None) -> dict:
    snapshot = p.closing_stock
    info = reopen_info() if reopen is None else reopen
    return _j({
        'id': p.pk, 'year': p.year, 'month': p.month, 'label': p.label or str(p), 'status': p.status,
        'period_start': p.period_start, 'period_end': p.period_end,
        'closed_by_name': p.closed_by.full_name if p.closed_by_id else '', 'closed_at': p.closed_at,
        'closing_started_at': p.closing_started_at,
        'closing_stock_total': snapshot.total if snapshot else None,
        'closes_year': p.month == 12,
        'can_reopen': p.pk in info, 'reopens_with': info.get(p.pk, []),
        'gl_reopen_window_months': close._reopen_window(),
    })


def close_failure_json(p) -> dict | None:
    """Why the month's last close failed: a code and our own Arabic message, never the exception's text (that stays
    in the audit row, whose id is the reference). None unless the failure is still where the month stands."""
    if p.status != 'open':
        return None
    row = (AuditLog.objects.filter(model_name='FinancialPeriod', object_id=str(p.pk), action__in=CLOSE_EVENTS)
           .order_by('-created_at', '-id').first())
    if row is None or row.action != 'gl_period_close_failed':
        return None
    extra = row.extra or {}
    code, detail = extra.get('code'), extra.get('detail') or {}
    out = {'at': row.created_at.isoformat(), 'by': row.user_name, 'account_code': None}
    if code in close.MESSAGES:
        message = close.MESSAGES[code]
    elif code in ledger.MESSAGES:
        message = ledger.MESSAGES[code]
    else:
        code, message = 'close_failed', GENERIC_CLOSE_FAILURE.format(ref=row.pk)
    if code == 'year_end_account' and detail.get('account_code'):
        out['account_code'] = str(detail['account_code'])
        message = f'{message} (حساب {out["account_code"]})'
    if code == 'bad_stock_row' and detail.get('store_code'):
        message = f'{message} (مخزن {softech_stock.store_label(detail["store_code"])})'
    return {**out, 'code': code, 'detail': message}


def period_detail_json(p) -> dict:
    """What a screen polls while a close runs; no SOFTECH read."""
    return {**period_json(p), 'last_close_failure': close_failure_json(p),
            'close_stuck': bool(p.status == 'closing' and p.closing_started_at
                                and timezone.now() - p.closing_started_at > close.CLOSING_TAKEOVER)}


def _missing_stores_json(codes) -> list:
    """Each missing store with its branch's label (an HQ store's own code is no branch)."""
    rules = softech_stock.store_map(codes) if codes else {}
    return [{'store_code': c, 'branch_label': branch_label(rules[c].branch_code)} for c in codes]


def store_json(s) -> dict:
    """A ClosingStockStore row."""
    return _j({'store_code': s.store_code, 'store_name': s.store_name, 'branch_id': s.branch_id,
               'branch_label': _branch_label(s.branch), 'included': s.included, 'rows': s.rows, 'value': s.value,
               'snapshot_date': s.snapshot_date, 'carried': s.carried})


def snapshot_json(s) -> dict:
    return _j({'id': s.pk, 'as_of': s.as_of, 'read_at': s.read_at,
               'read_by_name': s.read_by.full_name if s.read_by_id else '', 'total': s.total,
               'excluded_total': s.excluded_total, 'missing_stores': _missing_stores_json(s.missing_stores),
               'entry_id': s.entry_id, 'reversal_id': s.reversal_id})


def valuation_json(v) -> dict:
    """A live preview of `softech_stock.valuation`: same store row as a saved snapshot."""
    return _j({'as_of': v.as_of, 'total': v.total, 'excluded_total': v.excluded_total,
               'missing_stores': _missing_stores_json(v.missing_stores),
               'carried_stores': v.carried_stores,
               'stores': [{'store_code': s['store_code'], 'store_name': s['store_name'],
                           'branch_label': branch_label(s['branch_code']), 'included': s['included'],
                           'rows': s['rows'], 'value': s['value'], 'snapshot_date': s['snapshot_date'],
                           'carried': s['carried']} for s in v.stores]})


def check_json(c) -> dict:
    return _j({'id': c.pk, 'key': c.key, 'label': c.label, 'kind': c.kind, 'source': c.source, 'sign': c.sign,
               'per_party': c.per_party, 'account_codes': c.account_codes, 'group_names': c.group_names,
               'tolerance': c.tolerance, 'blocks_close': c.blocks_close, 'is_active': c.is_active,
               'order': c.order})


def line_json(ln, party_names=None) -> dict:
    check = ln.softech_check
    party = (party_names or {}).get(ln.party_code, ln.party_code)
    return _j({
        'id': ln.pk, 'period_id': ln.period_id, 'check_key': check.key, 'check_label': check.label,
        'kind': check.kind, 'per_party': check.per_party, 'tolerance': check.tolerance,
        'branch_id': ln.branch_id, 'branch_name': _branch_label(ln.branch) or ('' if check.per_party else 'بدون فرع'),
        'party_code': ln.party_code, 'party_name': party,
        'ledger_amount': ln.ledger_amount, 'softech_amount': ln.softech_amount, 'difference': ln.difference,
        'needs_explanation': ln.needs_explanation, 'explanation': ln.explanation,
        'explained_by_name': ln.explained_by.full_name if ln.explained_by_id else '',
        'explained_at': ln.explained_at, 'explained_difference': ln.explained_difference,
        'computed_at': ln.computed_at,
    })


def refresh_state_json(period, running: bool) -> dict:
    """Whether a refresh is running and how this month's last one ended. Runs (a screen's or the nightly job's) leave
    their audit row, so this reads the same for both."""
    row = (AuditLog.objects.filter(model_name='FinancialPeriod', object_id=str(period.pk), action__in=REFRESH_EVENTS)
           .order_by('-created_at', '-id').first())
    last = None
    if row is not None:
        failed = row.action == REFRESH_FAILED
        code = (row.extra or {}).get('code', '') if failed else ''
        last = {'at': row.created_at.isoformat(), 'by': row.user_name, 'ok': not failed, 'code': code,
                'detail': REFRESH_MESSAGES.get(code, '')}
    return {'running': running, 'last_run': last}
