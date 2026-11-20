"""
C14 / P-08 — stock-count variance valued at cost, with sales between snapshot and count netted
(apps/stockcount/valuation.py, surfaced in /api/stockcount/sessions/<id>/variance-report/).

A pack sold after the snapshot is not a shortage; returns put packs back; sales before the snapshot or
after the count do not count; the basis is named; raw difference and the SOFTECH adjustment export are
unchanged; other branches' sessions stay out of reach.
"""
import datetime as dt
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.stockcount import valuation as V
from apps.stockcount.models import StockCountSession, StockCountSnapshot
from apps.tests.factories import make_admin, make_branch, make_branch2, make_customer, make_item, make_user

T0 = timezone.make_aware(dt.datetime(2026, 11, 10, 10, 0))      # snapshot
T1 = timezone.make_aware(dt.datetime(2026, 11, 10, 13, 0))      # last count entry
N = [0]


def _sale(branch, item, qty, at, doc='115'):
    from apps.customers.models import PurchaseHistory, PurchaseHistoryLine
    N[0] += 1
    inv = PurchaseHistory.objects.create(customer=make_customer(), softech_invoice_id=f'C14-{N[0]}', branch=branch,
                                         doc_code=doc, docnumber=str(N[0]), invoice_date=at, trans_time=at)
    PurchaseHistoryLine.objects.create(purchase=inv, item=item, quantity=Decimal(str(qty)), unit_price=Decimal('10'),
                                       line_total=Decimal('10') * Decimal(str(qty)))


def _session(branch, rows, status='uploaded'):
    s = StockCountSession.objects.create(name='جرد C14', branch_code=branch.softech_branch_id, status=status,
                                         snapshot_at=T0, variance_at=T1)
    for code, expected, counted in rows:
        diff = None if counted is None else Decimal(str(counted)) - Decimal(str(expected))
        StockCountSnapshot.objects.create(
            session=s, item_code=code, item_name=code, branch_code=branch.softech_branch_id,
            expected_qty=Decimal(str(expected)), counted_qty=None if counted is None else Decimal(str(counted)),
            difference=diff, variance_type='' if diff is None else ('ok' if diff == 0 else
                                                                   ('surplus' if diff > 0 else 'deficit')))
    return s


class PureTests(SimpleTestCase):
    def test_sold_during_count_is_not_a_shortage(self):
        v = V.net_variance(Decimal('10'), Decimal('7'), Decimal('3'), Decimal('20'))
        self.assertEqual((v['net_difference'], v['net_type']), (Decimal('0'), 'ok'))
        self.assertEqual((v['raw_value'], v['net_value']), (Decimal('-60.00'), Decimal('0.00')))

    def test_real_shortage_valued_at_cost(self):
        v = V.net_variance(Decimal('10'), Decimal('5'), Decimal('2'), Decimal('12.5'))
        self.assertEqual((v['net_difference'], v['net_type'], v['net_value']), (Decimal('-3'), 'deficit', Decimal('-37.50')))

    def test_not_counted(self):
        v = V.net_variance(Decimal('10'), None, Decimal('2'), Decimal('5'))
        self.assertIsNone(v['net_value'])
        self.assertEqual(v['net_expected'], Decimal('8'))


class NettingTests(TestCase):
    def setUp(self):
        self.b, self.other = make_branch(), make_branch2()
        self.a = make_item(name='A', softech_id='CA1')
        self.a.cost_price = Decimal('20')
        self.a.save()
        self.c = make_item(name='C', softech_id='CC1')

    def test_netting_on_a_fixture_ledger(self):
        _sale(self.b, self.a, 3, T0 + dt.timedelta(hours=1))                 # during the count: nets
        _sale(self.b, self.a, 1, T0 + dt.timedelta(hours=2), doc='30')       # a return: puts one back
        _sale(self.b, self.a, 5, T0 - dt.timedelta(hours=1))                 # before the snapshot: no
        _sale(self.b, self.a, 4, T1 + dt.timedelta(minutes=5))               # after the count: no
        _sale(self.other, self.a, 9, T0 + dt.timedelta(hours=1))             # another branch: no
        s = _session(self.b, [('CA1', 10, 8), ('CC1', 4, None)])
        per, summary = V.value_session(s, list(s.snapshots.all()))
        a = per['CA1']
        self.assertEqual(a['moved_qty'], Decimal('2'))                        # 3 sold − 1 returned
        self.assertEqual((a['net_difference'], a['net_type']), (Decimal('0'), 'ok'))
        self.assertEqual(a['raw_value'], Decimal('-40.00'))
        self.assertEqual(summary['raw_deficit_value'], 40.0)
        self.assertEqual(summary['net_deficit_value'], 0.0)
        self.assertEqual(summary['cleared_by_sales'], 1)
        self.assertEqual(summary['basis'], 'current_cost')
        self.assertIsNone(per['CC1']['net_value'])                            # not counted: no value


class ApiTests(TestCase):
    def setUp(self):
        self.b, self.other = make_branch(), make_branch2()
        it = make_item(name='A', softech_id='CA2')
        it.cost_price = Decimal('10')
        it.save()
        _sale(self.b, it, 2, T0 + dt.timedelta(hours=1))
        self.s = _session(self.b, [('CA2', 10, 6)])

    def test_report_carries_value_and_keeps_the_raw_difference(self):
        _, _, c = make_admin('c14_admin')
        r = c.get(f'/api/stockcount/sessions/{self.s.pk}/variance-report/')
        self.assertEqual(r.status_code, 200, r.content)
        row = r.json()['items'][0]
        self.assertEqual((row['difference'], row['erp_doccode']), (-4.0, '150'))     # raw + SOFTECH doc unchanged
        self.assertEqual((row['moved_qty'], row['net_difference'], row['net_value']), (2.0, -2.0, -20.0))
        self.assertEqual(r.json()['valuation']['basis_label']['en'], "at the item's current cost")

    def test_other_branch_session_not_reachable(self):
        s2 = _session(self.other, [('CA2', 1, 1)])
        _, _, c = make_user('c14_pharm', role='pharmacist', branch=self.b)
        self.assertIn(c.get(f'/api/stockcount/sessions/{s2.pk}/variance-report/').status_code, (403, 404))

    def test_anonymous_refused(self):
        from rest_framework.test import APIClient
        self.assertIn(APIClient().get(f'/api/stockcount/sessions/{self.s.pk}/variance-report/').status_code,
                      (401, 403))
