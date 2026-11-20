"""
apps/tests/test_c18_missing_bonus.py

C18 (docs/full-project-audit/08 §C18) — /supply «بونص ناقص»: a paid doc-10 receipt that came with fewer free units
(PurchaseLine.bonus_qty — the pharmacydiscp = 100 line) than the same supplier's last 3 deliveries of the item gave.
Read-only.
"""
import datetime as dt
import io
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.tests.factories import make_admin, make_item, make_user

TODAY = timezone.localdate()
URL = '/api/supply/missing-bonus/'
D = Decimal


class JudgeTests(SimpleTestCase):
    """The rule on plain numbers."""

    def judge(self, paid, free, refs, later=None):
        from apps.procurement.missing_bonus import judge
        return judge(D(paid), D(free), [(D(a), D(b)) for a, b in refs], later)

    REFS = [(10, 1), (20, 2), (10, 1)]           # a «10+1» deal, three times

    def test_no_bonus_at_all(self):
        v = self.judge(20, 0, self.REFS)
        self.assertEqual((v['kind'], v['expected'], v['missing']), ('none', D(2), D(2)))

    def test_short_bonus(self):
        v = self.judge(30, 1, self.REFS)
        self.assertEqual((v['kind'], v['expected'], v['missing']), ('short', D(3), D(2)))

    def test_full_bonus_is_fine(self):
        self.assertIsNone(self.judge(20, 2, self.REFS))
        self.assertIsNone(self.judge(25, 2, self.REFS))          # floor(2.5) = 2

    def test_small_order_below_the_deal(self):
        self.assertIsNone(self.judge(5, 0, self.REFS))           # 5 < the smallest order that earned a bonus

    def test_needs_three_references(self):
        self.assertIsNone(self.judge(20, 0, self.REFS[:2]))

    def test_a_reference_without_bonus_means_no_deal(self):
        self.assertIsNone(self.judge(20, 0, [(10, 1), (10, 0), (10, 1)]))
        self.assertIsNone(self.judge(100, 0, [(100, 1), (100, 1), (100, 1)]))   # 1% is not a bonus deal

    def test_deal_changing_is_not_judged(self):
        self.assertIsNone(self.judge(20, 0, [(10, 1), (10, 3), (10, 1)]))       # 30% vs 10%

    def test_lowest_reference_ratio_is_used(self):
        v = self.judge(40, 0, [(10, 2), (10, 1), (10, 1)])       # 20%, 10%, 10% → 10%
        self.assertEqual(v['expected'], D(4))

    def test_deal_changed_when_the_next_delivery_repeats_the_lower_ratio(self):
        self.assertTrue(self.judge(20, 0, self.REFS, later=(D(20), D(0)))['deal_changed'])
        self.assertFalse(self.judge(20, 0, self.REFS, later=(D(20), D(2)))['deal_changed'])
        self.assertFalse(self.judge(20, 0, self.REFS)['deal_changed'])


class _Lines(TestCase):

    def setUp(self):
        from apps.branches.models import Branch
        mk = lambda code, kind: Branch.objects.create(softech_branch_id=code, code=code, name=f'B{code}',
                                                     name_ar=f'B{code}', kind=kind, is_active=True)
        self.hq = mk('100', Branch.KIND_HQ)
        self.b130 = mk('130', Branch.KIND_RETAIL)
        self.closed = mk('180', Branch.KIND_CLOSED)
        self.item = make_item('BONUSY', 'BN1')
        self.doc = 0

    def line(self, days_ago, qty, free, branch='100', supplier='565', item='BN1', doccode='10', value=None):
        from apps.procurement.models import PurchaseLine
        self.doc += 1
        qty, free = D(qty), D(free)
        return PurchaseLine.objects.create(branch_code=branch, supplier_code=supplier, doc_number=str(self.doc),
                                           doc_date=TODAY - dt.timedelta(days=days_ago), item_code=item,
                                           doccode=doccode, is_return=doccode == '120', raw_qty=qty, net_qty=qty,
                                           raw_value=D(value) if value is not None else qty * 12, bonus_qty=free,
                                           is_foc=free > 0)

    def history(self, branch='100', supplier='565', item='BN1'):
        for days in (120, 90, 60):
            self.line(days, 10, 1, branch=branch, supplier=supplier, item=item)

    def build(self, **kw):
        from apps.procurement.missing_bonus import build
        return build(**kw)


class BuildTests(_Lines):

    def test_flags_a_receipt_without_its_usual_bonus(self):
        self.history()
        self.line(3, 20, 0, value=240)
        rows = self.build()['rows']
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r['item_code'], r['paid_qty'], r['free_qty'], r['expected_free'], r['missing_free']),
                         ('BN1', 20.0, 0.0, 2.0, 2.0))
        self.assertEqual((r['unit_cost'], r['missing_value'], r['deal_pct'], r['kind']), (12.0, 24.0, 10.0, 'none'))
        self.assertEqual(len(r['refs']), 3)
        self.assertEqual(r['refs'][0]['doc_date'], (TODAY - dt.timedelta(days=60)).isoformat())   # newest first

    def test_references_come_from_any_branch_receipt_judged_where_received(self):
        self.history(branch='100')
        self.line(3, 20, 0, branch='130')
        self.assertEqual([r['branch_code'] for r in self.build()['rows']], ['130'])

    def test_other_supplier_history_does_not_count(self):
        self.history(supplier='30')
        self.line(3, 20, 0, supplier='565')
        self.assertEqual(self.build()['rows'], [])

    def test_returns_are_ignored(self):
        self.history()
        self.line(3, 20, 0, doccode='120')
        self.assertEqual(self.build()['rows'], [])

    def test_outside_the_window_is_not_listed(self):
        self.history()
        self.line(45, 20, 0)
        self.assertEqual(self.build(days=30)['rows'], [])
        self.assertEqual(len(self.build(days=60)['rows']), 1)

    def test_deal_changed_is_hidden_by_default(self):
        self.history()
        self.line(10, 20, 0)
        self.line(3, 20, 0)               # the next one repeats it → new deal
        # the 10-day receipt is a «changed deal» (hidden); the 3-day one has a bonus-less reference → not judged
        self.assertEqual(self.build()['rows'], [])
        both = self.build(include_changed=True)['rows']
        self.assertEqual([(r['doc_date'], r['deal_changed']) for r in both],
                         [((TODAY - dt.timedelta(days=10)).isoformat(), True)])

    def test_closed_branch_not_in_view(self):
        self.history()
        self.line(3, 20, 0, branch='180')
        report = self.build()
        self.assertEqual(report['rows'], [])
        self.assertNotIn('180', [b['branch_code'] for b in report['branches']])

    def test_contract_accounts_never_count(self):
        from apps.procurement.models import SupplierProfile
        from apps.supply.comparison import EXCLUDED_CLASSES
        SupplierProfile.objects.create(supplier_code='565', supplier_name='Contract', classif_code=sorted(EXCLUDED_CLASSES)[0])
        self.history()
        self.line(3, 20, 0)
        self.assertEqual(self.build()['rows'], [])

    def test_nothing_is_written(self):
        from apps.procurement.models import PurchaseLine
        self.history()
        self.line(3, 20, 0)
        before = list(PurchaseLine.objects.order_by('pk').values_list('pk', 'bonus_qty', 'is_foc'))
        self.build()
        self.assertEqual(list(PurchaseLine.objects.order_by('pk').values_list('pk', 'bonus_qty', 'is_foc')), before)


class ApiTests(_Lines):

    def setUp(self):
        super().setUp()
        make_item('BONUSY 2', 'BN2')
        self.history(item='BN1')
        self.history(item='BN2')
        self.line(3, 20, 0, branch='100', item='BN1')
        self.line(2, 30, 1, branch='130', item='BN2')

    def test_admin(self):
        _u, _s, client = make_admin('c18_admin')
        r = client.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(sorted(x['branch_code'] for x in r.data['rows']), ['100', '130'])
        self.assertEqual(r.data['refs'], 3)

    def test_branch_user_sees_own_branch_only(self):
        _u, _s, client = make_user('c18_buyer', role='purchasing', branch=self.b130)
        r = client.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual([x['branch_code'] for x in r.data['rows']], ['130'])

    def test_without_purchasing_rights(self):
        from apps.tests.security.fixtures import seed_code_matrix
        from core.middleware import module_access
        seed_code_matrix()
        module_access.clear_cache()
        self.addCleanup(module_access.clear_cache)
        _u, _s, client = make_user('c18_pharm', role='pharmacist', branch=self.b130)
        self.assertEqual(client.get(URL).status_code, 403)

    def test_excel(self):
        from openpyxl import load_workbook
        _u, _s, client = make_admin('c18_admin2')
        r = client.get(URL, {'format': 'xlsx'})
        self.assertEqual(r.status_code, 200)
        wb = load_workbook(io.BytesIO(r.content))
        self.assertEqual(wb.sheetnames, ['ملخص الفروع', 'السطور'])
        lines = list(wb['السطور'].iter_rows(min_row=2, values_only=True))
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(' · ' in row[1] for row in lines))
