"""
apps/tests/new_value_registry.py

Every per-branch export / report, run by apps/tests/test_new_values.py against planted data:
HQ + the five retail branches + a 7th retail branch '230', a pending '240', a closed branch and
the call center. Each must run without error, show '230', and never show the branches its entry
lists as absent (branch classification spec §8; CLAUDE.md "Security definition of done").

A new module with a per-branch export or report adds an entry here:
    (name, zero-arg callable, absent) — the callable returns bytes (a saved workbook) or
    dict / list (JSON); absent = the frozenset of tags (PENDING / CLOSED / CALL_CENTER) whose
    planted branch must never appear. Default ABSENT_ALL; narrow it only with a written reason.
The callable may read anything test_new_values plants (Branch rows, BranchSettings, one Item,
a successful DemandCalculationRun with metrics per branch, one in-transit transfer into '230').
Never connect to SOFTECH: stub its reads (mock config.sybase / the module's reader).
"""
import io
from unittest import mock

from django.test import override_settings


def _xlsx(wb) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _admin_client():
    from apps.tests.factories import make_admin
    _, _, client = make_admin('new_value_admin')
    return client


def _get(path):
    r = _admin_client().get(path)
    if r.status_code != 200:
        raise AssertionError(f'{path} answered {r.status_code}: {getattr(r, "data", r.content[:300])}')
    return r.content if r.get('Content-Type', '').startswith('application/vnd') else r.json()


# tags for the branches an entry must never show (test_new_values maps them to the planted codes)
PENDING, CLOSED, CALL_CENTER = 'pending', 'closed', 'call_center'
ABSENT_ALL = frozenset({PENDING, CLOSED, CALL_CENTER})


# ── entries ─────────────────────────────────────────────────────────────────────

def kpi_export():
    """KPI target board workbook (apps/forecasting/kpi_export.py)."""
    from apps.forecasting.kpi_export import build_target_workbook
    return _xlsx(build_target_workbook(2026, 10, models=('a', 'b', 'avg'), days_elapsed=8))


def purchasing_pivot_v2():
    """Purchasing engine pivot v2 (/purchasing → export, view=pivot)."""
    return _get('/api/purchasing/export/?view=pivot')


def isr_fulfillment_export():
    """ISR fulfilment workbook (apps/purchasing/isr_fulfillment.py). Live stock and the ISR
    are stubbed (SOFTECH reads): every eligible branch and HQ hold plenty of the item."""
    from apps.branches.models import Branch, hq_code
    from apps.catalog.models import Item
    from apps.purchasing import isr_fulfillment as F

    code = str(Item.objects.order_by('id').first().softech_id).strip()
    requester = Branch.objects.retail().order_by('softech_branch_id').first().softech_branch_id

    def fake_stock(branches, codes):
        out = {b.softech_branch_id: {c: 50.0 for c in codes} for b in branches}
        out[requester] = {c: 0.0 for c in codes}
        out[hq_code()] = {c: 50.0 for c in codes}
        return out, [], {}

    isr = {'isr': '999001', 'branch': requester, 'for_branch': hq_code(), 'date': '2026-10-01',
           'approved': 1, 'value': 100.0, 'user': '', 'lines': [
               {'code': code, 'qty': 30.0, 'nowqty_at_request': 0, 'cost': 5.0, 'price': 7}]}
    with mock.patch.object(F, '_live_stock', side_effect=fake_stock):
        snap = F.collect_requests([isr])
    return _xlsx(F.build_workbook(snap, 1.0, 3.0))


def transits_picking_sheet():
    """Transits ورقة التجميع over every in-transit transfer (apps/transits/export.py)."""
    from apps.transits.export import generate_picking_workbook
    from apps.transits.models import InTransitTransfer
    content, _name, _type = generate_picking_workbook(
        list(InTransitTransfer.objects.filter(transit_status='in_transit')), mode='picking')
    return content


def stock_count_board():
    """Daily stock count board — the pilot-branch list management hands lists out for."""
    with override_settings(DAILY_COUNT_ENABLED=True):
        return _get('/api/stockcount/daily/board/')['pilot_branches']


def analytics_branch_contribution():
    """Analytics branch contribution report (/api/analytics/branch-contribution/)."""
    return _get('/api/analytics/branch-contribution/')


def eta_recon_export():
    """SOFTECH ↔ ETA receipts reconciliation workbook (/tax-invoicing → سجل المصلحة → المطابقة → تصدير).
    One ETA device per planted branch; the SOFTECH read is stubbed with one sale per branch-day."""
    import datetime as dt
    from decimal import Decimal

    from apps.branches.models import Branch
    from apps.tax_invoicing import eta_recon
    from apps.tax_invoicing.models import EtaDeviceBranch

    day = dt.date(2026, 11, 5)
    for code in Branch.objects.values_list('softech_branch_id', flat=True):
        EtaDeviceBranch.objects.get_or_create(system='production', pos_serial=f'NV-{code}', defaults={
            'softech_branchcode': code, 'first_day': day})
    sale = [{'doccode': '115', 'docnumber': '1', 'total': Decimal('10'), 'channel': ''}]
    with mock.patch.object(eta_recon, '_softech_rows', return_value=sale):
        eta_recon.reconcile_range('production', day, day)
    return _get('/api/tax-invoicing/history/recon/export/?system=production')


def crew_cc_comparison():
    """Call-center old-vs-crew comparison workbook (apps/crews/cc_comparison.py, piece 2b). The
    crew is seeded in a rolled-back transaction; no CDR configured and no returns (no SOFTECH)."""
    from apps.crews import cc_comparison as C
    with mock.patch.object(C, 'cdr_configured', return_value=False):
        res = C.compare_seeded_in_transaction((2026, 8), (2026, 10), returns=False)
    return _xlsx(C.build_workbook(res))


EXPORTS = [
    # the KPI board has a call-center block by design: only pending / closed must be absent
    ('kpi_export', kpi_export, frozenset({PENDING, CLOSED})),
    ('purchasing_pivot_v2', purchasing_pivot_v2, ABSENT_ALL),
    ('isr_fulfillment_export', isr_fulfillment_export, ABSENT_ALL),
    # its branches come from the transfers passed in (only one, into '230'): presence only
    ('transits_picking_sheet', transits_picking_sheet, frozenset()),
    ('stock_count_board', stock_count_board, ABSENT_ALL),
    ('analytics_branch_contribution', analytics_branch_contribution, ABSENT_ALL),
    ('eta_recon_export', eta_recon_export, ABSENT_ALL),
    # the report exists to show the old CC figures: only pending / closed must be absent
    ('crew_cc_comparison', crew_cc_comparison, frozenset({PENDING, CLOSED})),
]
