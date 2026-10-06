"""
apps/tests/test_coupon_lifecycle.py

Gift-coupon lifecycle (apps/vouchers/coupon_lifecycle.py) — no SOFTECH contact.
Fixture rows mirror the real 2026-10-05 documents found by the --doctypes probe:
170 issue 100/170/108359 (PIC 05HD759), 125/25 transfer HQ→140, 115 sale at branch 170.
"""
import datetime as dt
from unittest import mock

from django.test import TestCase

from apps.customers.models import Customer
from apps.vouchers import coupon_lifecycle as lc
from apps.vouchers import coupons
from apps.vouchers.models import CouponEvent, CouponSerial

D = dt.date
NAMES = {'170': 'صرف أصناف مصروفات', '125': 'صرف - تبادل بين الفروع',
         '25': 'إستلام - تبادل بين الفروع', '115': 'مبيعات لعميل',
         '110': 'صرف - تبادل بين الفروع (قديم)', '15': 'إستلام - تبادل بين الفروع (قديم)'}


def mv(item, doccode, branch, docnumber, date, serial, *, party='', pic='', line=1, qty=1):
    return {'itemcode': item, 'branchcode': branch, 'doccode': doccode, 'docnumber': docnumber,
            'docdate': f'{date} 00:00:00', 'storecode': branch, 'dblitemflag': line, 'transqty': qty,
            'itemsaleprice': 400 if item == '102230' else -50, 'item_partno': serial,
            'usercode': '64', 'cust_branch_code': party, 'phcode': pic}


def stocked(serial, doc_p=65625, doc_s=65626):
    coupons.import_purchase_lines([
        {'itemcode': '102230', 'item_partno': serial, 'itemexpirydate': '2030-03-11', 'docnumber': doc_p,
         'docdate': '2026-07-15'},
        {'itemcode': '118639', 'item_partno': serial, 'itemexpirydate': '2030-03-11', 'docnumber': doc_s,
         'docdate': '2026-07-15'}])


W0, W1 = D(2026, 9, 1), D(2026, 11, 1)


class ClassifyTests(TestCase):
    def test_confirmed_codes(self):
        self.assertEqual(lc.classify('170', 'points'), ('issue', 'out'))
        self.assertEqual(lc.classify('125', 'served'), ('transfer_out', 'out'))
        self.assertEqual(lc.classify('25', 'served'), ('transfer_in', 'in'))
        self.assertEqual(lc.classify('115', 'served'), ('redeem', 'out'))
        self.assertEqual(lc.classify('30', 'served'), ('redeem_return', 'in'))

    def test_leg_guards_and_name_fallback(self):
        self.assertEqual(lc.classify('115', 'points')[0], 'other')
        self.assertEqual(lc.classify('170', 'served')[0], 'other')
        self.assertEqual(lc.classify('110', 'served', NAMES['110'])[0], 'transfer_out')
        self.assertEqual(lc.classify('15', 'served', NAMES['15'])[0], 'transfer_in')
        self.assertEqual(lc.classify('150', 'served', 'تسوية')[0], 'other')


class LifecycleTests(TestCase):
    def setUp(self):
        stocked('27286-MFW296')
        self.cust = Customer.objects.create(name='عميل', phone='01000000001', softech_pic='05HD759')

    def _sync(self, rows):
        stats = lc.store_events(rows, W0, W1, NAMES)
        lc.rebuild_summaries()
        return stats

    def test_happy_path_issue_transfer_redeem(self):
        s = '27286-MFW296'
        stats = self._sync([
            mv('102230', '170', '100', 108359, '2026-10-05', s, party='100', pic='05HD759'),
            mv('118639', '125', '100', 108354, '2026-10-05', s, party='140'),
            mv('118639', '25', '140', 22796, '2026-10-05', s, party='100'),
            mv('118639', '115', '140', 415797, '2026-10-06', s, party='1500', pic='05HD759'),
        ])
        self.assertEqual(stats, {'lines': 4, 'linked': 4, 'no_serial': 0, 'unknown_serial': 0})
        c = CouponSerial.objects.get(serial=s)
        self.assertEqual(c.stage, 'redeemed')
        self.assertEqual((c.issued_at, c.issued_pic, c.issued_doc), (D(2026, 10, 5), '05HD759', 108359))
        self.assertEqual((c.sent_branch, c.redeemed_branch, c.redeemed_doc), ('140', '140', 415797))
        self.assertEqual(c.anomalies, [])
        self.assertEqual(CouponEvent.objects.filter(customer=self.cust).count(), 2)

    def test_stages_before_redemption(self):
        s = '27286-MFW296'
        self._sync([])
        self.assertEqual(CouponSerial.objects.get(serial=s).stage, 'stocked')
        self._sync([mv('102230', '170', '100', 1, '2026-10-05', s, pic='05HD759')])
        self.assertEqual(CouponSerial.objects.get(serial=s).stage, 'issued')
        self._sync([mv('102230', '170', '100', 1, '2026-10-05', s, pic='05HD759'),
                    mv('118639', '25', '140', 2, '2026-10-05', s, party='100')])
        self.assertEqual(CouponSerial.objects.get(serial=s).stage, 'at_branch')

    def test_anomalies(self):
        s = '27286-MFW296'
        self._sync([
            mv('118639', '115', '130', 1, '2026-10-01', s, pic='99HD1'),
            mv('118639', '115', '150', 2, '2026-10-02', s, pic='99HD1'),
        ])
        c = CouponSerial.objects.get(serial=s)
        self.assertEqual(c.redeem_count, 2)
        self.assertEqual(sorted(c.anomalies),
                         ['redeemed_at_unsent_branch', 'redeemed_not_issued', 'redeemed_twice'])

    def test_customer_return_cancels_redemption(self):
        s = '27286-MFW296'
        self._sync([
            mv('102230', '170', '100', 1, '2026-10-01', s, pic='05HD759'),
            mv('118639', '115', '100', 2, '2026-10-02', s, pic='05HD759'),
            mv('118639', '30', '100', 3, '2026-10-03', s, pic='05HD759'),
        ])
        c = CouponSerial.objects.get(serial=s)
        self.assertEqual((c.redeem_count, c.stage, c.anomalies), (0, 'issued', []))

    def test_other_customer_flag(self):
        s = '27286-MFW296'
        self._sync([mv('102230', '170', '100', 1, '2026-10-01', s, pic='05HD759'),
                    mv('118639', '115', '100', 2, '2026-10-02', s, pic='77HD1')])
        self.assertEqual(CouponSerial.objects.get(serial=s).anomalies, ['redeemed_by_other_customer'])

    def test_blank_and_unknown_serials_are_kept_for_audit(self):
        stats = self._sync([
            mv('118639', '115', '130', 10, '2026-10-01', ''),
            mv('118639', '115', '130', 11, '2026-10-01', '24315'),
            mv('118639', '115', '130', 12, '2026-10-01', '99999-ZZZ999'),
        ])
        self.assertEqual((stats['no_serial'], stats['unknown_serial'], stats['linked']), (2, 1, 0))
        r = lc.report()
        self.assertEqual(r['redeemed_without_valid_serial_by_branch'], [('130', 3, 3.0)])

    def test_window_resync_is_idempotent(self):
        rows = [mv('102230', '170', '100', 1, '2026-10-01', '27286-MFW296', pic='05HD759')]
        self._sync(rows)
        self._sync(rows)
        self.assertEqual(CouponEvent.objects.count(), 1)
        # an event outside the window survives a re-sync of the window
        lc.store_events([mv('102230', '170', '100', 9, '2026-08-01', '27286-MFW296')],
                        D(2026, 8, 1), D(2026, 8, 2), NAMES)
        self._sync(rows)
        self.assertEqual(CouponEvent.objects.count(), 2)

    def test_sync_reads_windows_per_item(self):
        conn = mock.Mock()
        with mock.patch.object(lc, 'read_doc_names', return_value=NAMES), \
                mock.patch.object(lc, 'read_movements', return_value=[]) as rm:
            res = lc.sync(conn, since=D(2026, 9, 1), until=D(2026, 10, 15))
        self.assertEqual(rm.call_count, 4)          # 2 windows × 2 items
        self.assertEqual({c.args[1] for c in rm.call_args_list}, {'102230', '118639'})
        self.assertEqual(res['serials'], 1)
