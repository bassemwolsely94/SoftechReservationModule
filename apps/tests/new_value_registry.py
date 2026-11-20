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


def cover_tiers_export():
    """C25 / P-34 tiered-cover workbook (/cash-optimization → 🎯 التغطية حسب الفئة → تصدير): retail branches
    of the latest engine run only — HQ is not a cover target, pending / closed / call center never show."""
    return _get('/api/purchasing/cover-tiers/lines/?format=xlsx')


def delivery_small_orders_export():
    """C20 delivery small-order / fee-less invoice workbook (/delivery/analytics → 💸 طلبات صغيرة): one small
    channel-90 sale planted per branch; live branches only, so pending / closed / call center never show."""
    import datetime as dt
    from decimal import Decimal

    from django.utils import timezone

    from apps.branches.models import Branch
    from apps.customers.models import PurchaseHistory, PurchaseHistoryLine
    from apps.tests.factories import make_customer, make_item

    day = dt.date(2026, 11, 10)
    item, customer = make_item(softech_id='NVC20'), make_customer()
    for b in Branch.objects.all():
        inv = PurchaseHistory.objects.create(
            customer=customer, softech_invoice_id=f'NV-C20-{b.softech_branch_id}', branch=b, doc_code='115',
            docnumber='1', sales_channel='90', total_amount=Decimal('50'),
            invoice_date=timezone.make_aware(dt.datetime.combine(day, dt.time(12, 0))))
        PurchaseHistoryLine.objects.create(purchase=inv, item=item, quantity=Decimal('1'), unit_price=Decimal('50'),
                                           line_total=Decimal('50'), cost_at_sale=Decimal('40'))
    return _get(f'/api/delivery/small-orders/export/?date_from={day}&date_to={day}')


def out_here_export():
    """C06 /supply «ناقص هنا · موجود هناك» workbook: its summary lists every live retail branch in view (HQ is a
    source, never a destination); pending / closed / call center never show."""
    return _get('/api/supply/out-here/export/')

# Not registered by design: the call-center old-vs-crew comparison (apps/crews/cc_comparison.py,
# crews piece 2b) is a single-scope report (the call-center crew) with no per-branch rows, so it
# has no branch to show or hide (spec 2026-11-13 §6.8: a crew shows as its own block).

EXPORTS = [
    # the KPI board has a call-center block by design: only pending / closed must be absent
    # the call-center block comes from the call-center crew now, never from a branch
    ('kpi_export', kpi_export, ABSENT_ALL),
    ('purchasing_pivot_v2', purchasing_pivot_v2, ABSENT_ALL),
    ('isr_fulfillment_export', isr_fulfillment_export, ABSENT_ALL),
    # its branches come from the transfers passed in (only one, into '230'): presence only
    ('transits_picking_sheet', transits_picking_sheet, frozenset()),
    ('stock_count_board', stock_count_board, ABSENT_ALL),
    ('analytics_branch_contribution', analytics_branch_contribution, ABSENT_ALL),
    ('eta_recon_export', eta_recon_export, ABSENT_ALL),
    ('cover_tiers_export', cover_tiers_export, ABSENT_ALL),
    ('delivery_small_orders_export', delivery_small_orders_export, ABSENT_ALL),
    ('out_here_export', out_here_export, ABSENT_ALL),
]
