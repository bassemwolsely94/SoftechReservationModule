"""
New-value flow test (branch classification piece 1, Task 7; spec §8).

Plants HQ + the five retail branches + a 7th retail branch '230' + a pending '240' + a closed
branch + the call center, then runs every export / report in apps/tests/new_value_registry.py:
each must run, show the new live branch, and never show the branches its entry lists as
absent (pending, closed, call center — each entry its own set). Presence / absence only — column order is each export's own business (owner: ISR and
pivot v2 keep code order).
"""
import io
import json
import re
from datetime import date
from decimal import Decimal

from django.test import TestCase, override_settings

from apps.branches.models import Branch, BranchSettings, _reset_hq_code_cache
from apps.tests import new_value_registry
from apps.tests.factories import make_admin, make_hq, make_item

NEW, PENDING, CLOSED, CC = '230', '240', '180', 'CC'
# registry tags (new_value_registry.PENDING / CLOSED / CALL_CENTER) → the planted branch code
ABSENT_CODE = {new_value_registry.PENDING: PENDING, new_value_registry.CLOSED: CLOSED,
               new_value_registry.CALL_CENTER: CC}
RETAIL = [('160', 1), ('170', 2), ('140', 3), ('150', 4), ('130', 5), (NEW, 6)]


def _name(code):
    return f'NV-{code}'


def _texts(output) -> list:
    """Every string (and whole number) an export shows: workbook cells or JSON leaves."""
    if isinstance(output, (bytes, bytearray)):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(output))
        out = []
        for ws in wb.worksheets:
            out.append(ws.title)
            for row in ws.iter_rows(values_only=True):
                out += [str(v) for v in row if isinstance(v, (str, int)) and not isinstance(v, bool)]
        return out
    out = []

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)
        elif isinstance(x, (str, int)) and not isinstance(x, bool):
            out.append(str(x))
    walk(json.loads(json.dumps(output, default=str)))
    return out


def _shows(texts, code) -> bool:
    """The branch's code as a whole token (alone or as a '230.' prefix) or its name."""
    rx = re.compile(rf'(?<![0-9A-Za-z]){re.escape(code)}(?![0-9A-Za-z])')
    name = _name(code)
    return any(t == code or name in t or (code.isdigit() and rx.search(t)) for t in texts)


@override_settings(RBAC_ENFORCEMENT='log')
class NewValueFlowTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from apps.forecasting.models import KpiActualRollup as K
        from apps.purchasing.models import DemandCalculationRun, ItemDemandMetrics
        from apps.transits.models import InTransitTransfer

        _reset_hq_code_cache()
        hq = make_hq('100')
        hq.name, hq.name_ar = _name('100'), _name('100')
        hq.save()
        item = make_item('NEW VALUE ITEM', 'NV001')
        run = DemandCalculationRun.objects.create(status='success')
        branches = [hq]
        for i, (code, order) in enumerate(RETAIL):
            branches.append(cls._branch(code, Branch.KIND_RETAIL, order, f'10.9.0.{i + 1}'))
        branches.append(cls._branch(PENDING, Branch.KIND_PENDING, 7, '10.9.0.20'))
        branches.append(cls._branch(CLOSED, Branch.KIND_CLOSED, 8, '10.9.0.21'))
        branches.append(cls._branch(CC, Branch.KIND_CALL_CENTER, 9, ''))
        for b in branches:
            ItemDemandMetrics.objects.create(run=run, item=item, branch=b, calc_date=date(2026, 10, 26),
                                             current_stock=5, monthly_avg=10, gap=4)
            bs = BranchSettings.for_branch(b)
            bs.daily_count_enabled = True
            bs.save()
            # last year / last two months / this month — every metric the KPI board reads
            for (y, m) in [(2025, 10), (2026, 8), (2026, 9), (2026, 10)]:
                for metric in (K.M_CASH, K.M_DELIVERY, K.M_REGULAR, K.M_CASH_DELIVERY, K.M_CREDIT,
                               K.M_GROSS_PROFIT, K.M_CUSTOMERS, K.M_BEAUTY, K.M_CALL_COUNT):
                    K.objects.create(branch=b, year=y, month=m, metric=metric, value=Decimal('1000'))
        new = Branch.objects.get(softech_branch_id=NEW)
        InTransitTransfer.objects.create(
            erp_doc_number='990230', erp_supplying_branch_code='100', erp_receiving_branch_code=NEW,
            supplying_branch=hq, receiving_branch=new, issue_date=date(2026, 10, 1), item_count=1,
            items_snapshot=[{'itemcode': 'NV001', 'itemname': 'NEW VALUE ITEM', 'qty': 3,
                             'unit_cost': 7, 'extended_cost': 21, 'batch': None, 'expiry': None,
                             'near_expiry': False}],
            transit_status='in_transit')
        make_admin('new_value_admin')
        # the factory's home branch B01 is a test branch, not part of this network
        Branch.objects.filter(softech_branch_id='B01').update(kind=Branch.KIND_CLOSED)

    @classmethod
    def _branch(cls, code, kind, order, host):
        return Branch.objects.create(softech_branch_id=code, code=code, name=_name(code),
                                     name_ar=_name(code), kind=kind, display_order=order,
                                     db_host=host, is_active=True, is_operational=True)

    def setUp(self):
        _reset_hq_code_cache()
        self.addCleanup(_reset_hq_code_cache)

    def test_registry_is_not_empty(self):
        self.assertGreaterEqual(len(new_value_registry.EXPORTS), 6)

    def test_every_export_shows_the_new_branch_only_where_live(self):
        for name, build, absent in new_value_registry.EXPORTS:
            with self.subTest(export=name):
                texts = _texts(build())
                self.assertTrue(_shows(texts, NEW), f'{name}: new live branch {NEW} missing')
                for tag in absent:
                    gone = ABSENT_CODE[tag]
                    self.assertFalse(_shows(texts, gone), f'{name}: shows {tag} branch {gone}')

    def test_every_entry_declares_its_absent_set(self):
        known = set(ABSENT_CODE)
        for name, _build, absent in new_value_registry.EXPORTS:
            with self.subTest(export=name):
                self.assertIsInstance(absent, frozenset)
                self.assertLessEqual(absent, known, f'{name}: unknown tag')
        by_name = {n: a for n, _b, a in new_value_registry.EXPORTS}
        # the KPI board has a call-center block by design; the picking sheet only checks presence
        self.assertNotIn(new_value_registry.CALL_CENTER, by_name['kpi_export'])
        self.assertEqual(by_name['transits_picking_sheet'], frozenset())

    def test_branch_list_default_scope(self):
        _, _, client = make_admin('new_value_admin')
        r = client.get('/api/branches/')
        self.assertEqual(r.status_code, 200)
        data = r.data.get('results', r.data) if hasattr(r.data, 'get') else r.data
        codes = {b['softech_branch_id'] for b in data}
        self.assertIn(NEW, codes)
        self.assertNotIn(PENDING, codes)
        self.assertNotIn(CLOSED, codes)
        self.assertNotIn(CC, codes)
