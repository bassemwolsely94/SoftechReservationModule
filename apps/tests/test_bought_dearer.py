"""
C17 «اشترينا أغلى» (apps/supply/bought_dearer.py): monthly lines bought above the cheapest RECENT
accredited supplier for the same item, with the EGP difference, per buyer and per supplier.

Rules under test: pure free lines are never a purchase nor the price to beat; cost is VAT-inclusive
for every line and the free units lower it; only a cheaper price available BEFORE the line counts;
warehouses / virtual accounts and sister accounts of one company are never "cheaper"; company-level
access; Excel neutralises formulas.
"""
import datetime
import io
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase

from apps.supply import bought_dearer as BD
from apps.tests.factories import make_branch, make_user

OCT = datetime.date(2026, 10, 1)
URL = '/api/supply/bought-dearer/'


def _line(item, supplier, day, *, qty=10, disc=0.20, bonus=0, public=100, vat=0.0, value=None, buyer='B7', n=[0]):
    """`qty` paid packs at public × (1 − disc) (+ `vat` on top), dated `day`."""
    from apps.procurement.models import PurchaseLine
    n[0] += 1
    value = value if value is not None else qty * public * (1 - disc)
    return PurchaseLine.objects.create(
        branch_code='100', supplier_code=supplier, doc_number=f'C17-{n[0]}', doccode='10', doc_date=day,
        item_code=item.softech_id, item=item, net_qty=Decimal(str(qty)), raw_qty=Decimal(str(qty)),
        net_value=Decimal(str(round(value, 3))), raw_value=Decimal(str(round(value, 3))),
        bonus_qty=Decimal(str(bonus)), vat_value=Decimal(str(vat)), public_price=Decimal(str(public)),
        buyer_code=buyer)


def _setup_suppliers():
    from apps.procurement.models import SupplierProfile
    for code, name, cl in (('D1', 'RAMCO', '60'), ('D2', 'IBN SINA', '60'), ('786', 'EGY-SHERIF', '60'),
                           ('4327', 'EGY-ZAYTOUN', '60'), ('W1', 'مخزن', '50'), ('V1', 'virtual', '80')):
        SupplierProfile.objects.create(supplier_code=code, supplier_name=name, classif_code=cl)


def _d(m, d):
    return datetime.date(2026, m, d)


class ReportTests(TestCase):
    def setUp(self):
        from apps.catalog.models import Item
        _setup_suppliers()
        self.a = Item.objects.create(softech_id='A17', name='ITEM A', pack_price=100)

    def lines(self):
        return BD.build(OCT)['lines']

    def test_dearer_line_with_egp_above_the_cheaper_recent_supplier(self):
        _line(self.a, 'D2', _d(9, 20), disc=0.26)                 # IBN SINA 26 % three weeks before
        _line(self.a, 'D1', _d(10, 10), qty=10, disc=0.20)        # we paid RAMCO 20 %
        rep = BD.build(OCT)
        self.assertEqual(len(rep['lines']), 1)
        r = rep['lines'][0]
        self.assertEqual((r['supplier_name'], r['cheaper_supplier'], r['gap_pct']), ('RAMCO', 'IBN SINA', 6.0))
        self.assertEqual(r['egp_above'], 60.0)                    # 6 % × 100 × 10 packs
        self.assertEqual(rep['totals'], {'lines_checked': 1, 'lines': 1, 'egp_above': 60.0})
        self.assertEqual(rep['by_buyer'][0]['code'], 'B7')
        self.assertEqual(rep['by_supplier'][0]['name'], 'RAMCO')

    def test_only_a_price_available_before_the_line_counts(self):
        _line(self.a, 'D1', _d(10, 10), disc=0.20)
        _line(self.a, 'D2', _d(10, 20), disc=0.30)                # cheaper, but only later
        _line(self.a, 'D2', _d(6, 1), disc=0.40)                  # cheaper, but older than STALE_DAYS
        self.assertEqual(self.lines(), [])

    def test_within_one_point_is_not_dearer(self):
        _line(self.a, 'D2', _d(10, 1), disc=0.205)
        _line(self.a, 'D1', _d(10, 10), disc=0.20)
        self.assertEqual(self.lines(), [])

    def test_free_lines_excluded_and_bonus_lowers_cost(self):
        _line(self.a, 'D2', _d(10, 1), qty=0, bonus=5, value=0)    # pure free line: never a price
        _line(self.a, 'D2', _d(10, 2), qty=10, value=800, bonus=0)  # 20 %
        _line(self.a, 'D1', _d(10, 10), qty=10, value=800, bonus=2)  # 800 / 12 = 33.3 % after the bonus
        self.assertEqual(self.lines(), [])                        # the bonus buy is the cheaper one
        _line(self.a, 'D2', _d(10, 15), qty=10, value=800, bonus=0)  # now IBN SINA 20 % is dearer
        r = self.lines()
        self.assertEqual([(x['supplier_name'], x['date']) for x in r], [('IBN SINA', '2026-10-15')])
        self.assertEqual((r[0]['cheaper_supplier'], r[0]['gap_pct']), ('RAMCO', 13.33))

    def test_vat_is_in_every_cost(self):
        _line(self.a, 'D2', _d(10, 1), disc=0.20, vat=0)          # 80 / pack
        _line(self.a, 'D1', _d(10, 10), disc=0.20, vat=140)       # 80 + 14 VAT = 94 / pack = 6 % off
        r = self.lines()
        self.assertEqual(len(r), 1)
        self.assertEqual((r[0]['supplier_name'], r[0]['gap_pct'], r[0]['egp_above']), ('RAMCO', 14.0, 140.0))

    def test_warehouse_virtual_and_sister_accounts_are_never_the_cheaper_price(self):
        _line(self.a, 'W1', _d(10, 1), disc=0.40)
        _line(self.a, 'V1', _d(10, 2), disc=0.60)
        _line(self.a, '4327', _d(10, 3), disc=0.30)               # same company as 786
        _line(self.a, '786', _d(10, 10), disc=0.20)
        self.assertEqual(self.lines(), [])

    def test_excel_neutralises_formulas(self):
        from openpyxl import load_workbook
        _line(self.a, 'D2', _d(10, 1), disc=0.30, buyer='=HYPERLINK("x")')
        _line(self.a, 'D1', _d(10, 10), disc=0.20, buyer='=HYPERLINK("x")')
        wb = load_workbook(io.BytesIO(BD.to_excel(BD.build(OCT))))
        cells = [c for row in wb['السطور'].iter_rows() for c in row]
        self.assertIn('=HYPERLINK("x")', [c.value for c in cells])          # kept as text …
        self.assertEqual([c.coordinate for c in cells if c.data_type == 'f'], [])   # … never a live formula
        self.assertEqual(wb.sheetnames, ['السطور', 'حسب المورد', 'حسب المشتري'])


class ApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_admin_reads_json_and_excel(self):
        _, _, c = make_user('c17_admin', role='admin', access_all=True)
        r = c.get(URL, {'month': '2026-10'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['month'], '2026-10')
        self.assertIn('spreadsheetml', c.get(URL, {'month': '2026-10', 'format': 'xlsx'})['Content-Type'])
        self.assertEqual(c.get(URL, {'month': '10-2026'}).status_code, 400)

    def test_without_the_purchasing_grant_refused(self):
        _, _, c = make_user('c17_sales', role='salesperson')
        self.assertEqual(c.get(URL).status_code, 403)

    def test_branch_bound_user_refused_even_with_the_grant(self):
        from apps.users.models import RoleModuleAccess
        from core.middleware import module_access
        for a in ('view', 'edit'):
            RoleModuleAccess.objects.create(role='pharmacist', module='purchasing', action=a, is_allowed=True)
        module_access.clear_cache()
        self.addCleanup(module_access.clear_cache)
        _, _, c = make_user('c17_pharm', role='pharmacist', branch=make_branch('فرع', '130'))
        self.assertEqual(c.get(URL).status_code, 403)

    def test_anonymous_refused(self):
        from rest_framework.test import APIClient
        self.assertIn(APIClient().get(URL).status_code, (401, 403))
