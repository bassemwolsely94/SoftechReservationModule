"""
apps/tests/new_value_registry.py

Every per-branch export / report, run by apps/tests/test_new_values.py against planted data:
HQ + the five retail branches + a 7th retail branch '230', a pending '240', a closed branch and
the call center. Each must run without error, show '230', and never show the pending, closed
or call-center branch (branch classification spec §8; CLAUDE.md "Security definition of done").

A new module with a per-branch export or report adds an entry here:
    (name, zero-arg callable) -> bytes (a saved workbook) or dict / list (JSON)
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


EXPORTS = [
    ('kpi_export', kpi_export),
    ('purchasing_pivot_v2', purchasing_pivot_v2),
    ('isr_fulfillment_export', isr_fulfillment_export),
    ('transits_picking_sheet', transits_picking_sheet),
    ('stock_count_board', stock_count_board),
    ('analytics_branch_contribution', analytics_branch_contribution),
]
