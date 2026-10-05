"""
apps/tests/test_coupon_archive.py

Gift-coupon archive + serial generator (apps/vouchers/coupons.py) — no SOFTECH contact.
Fixtures mirror real SOFTECH rows from the 2026-10-06 probe (docs 63944/63945,
serial 27101-ZWU704, expiry 2029-08-23).
"""
import datetime as dt

from django.test import TestCase

from apps.vouchers import coupons
from apps.vouchers.models import CouponBatch, CouponSerial

D = dt.date


def line(item, serial, expiry, doc, docdate='2026-07-15 00:00:00'):
    return {'itemcode': item, 'item_partno': serial, 'itemexpirydate': f'{expiry} 00:00:00',
            'docnumber': f'{doc}.0', 'docdate': docdate}


class _SeqRng:
    """Deterministic rng: yields the given codes in order (3 letters + 3 digits)."""

    def __init__(self, codes):
        self._chars = [ch for c in codes for ch in c[:3]]
        self._nums = [int(c[3:]) for c in codes]

    def choice(self, _seq):
        return self._chars.pop(0)

    def randint(self, _a, _b):
        return self._nums.pop(0)


class PureHelperTests(TestCase):
    def test_parse_serial(self):
        self.assertEqual(coupons.parse_serial(' 27101-zwu704 '), (27101, 'ZWU704', '27101-ZWU704'))
        for bad in ('102230', '20000-ABCFED', '', None, '27101ZWU704'):
            self.assertIsNone(coupons.parse_serial(bad), bad)

    def test_collated_order_matches_excel_printing_sheet(self):
        # Excel: F1=D2, F11=D27, F21=D52, F31=D77, F41=D3 … for a 100-coupon run.
        self.assertEqual(coupons.collated_order(100)[:8], [0, 25, 50, 75, 1, 26, 51, 76])
        for n in (1, 7, 200):
            self.assertEqual(sorted(coupons.collated_order(n)), list(range(n)))

    def test_next_free_dates_skips_blocked(self):
        got = coupons.next_free_dates(3, D(2030, 3, 11), {D(2030, 3, 12)})
        self.assertEqual(got, [D(2030, 3, 11), D(2030, 3, 13), D(2030, 3, 14)])

    def test_random_code_shape(self):
        for _ in range(50):
            self.assertRegex(coupons.random_code(), r'^[A-Z]{3}[1-9]\d{2}$')


class ImportTests(TestCase):
    def test_both_legs_make_a_stocked_serial(self):
        rep = coupons.import_purchase_lines([
            line('102230', '27101-ZWU704', '2029-08-23', 63944),
            line('118639', '27101-ZWU704', '2029-08-23', 63945),
        ])
        self.assertEqual(rep['created'], 1)
        c = CouponSerial.objects.get(serial='27101-ZWU704')
        self.assertEqual((c.number, c.code, c.source, c.status), (27101, 'ZWU704', 'softech', 'stocked'))
        self.assertEqual((c.points_docnumber, c.served_docnumber), (63944, 63945))
        self.assertEqual(c.points_expiry, D(2029, 8, 23))
        self.assertEqual(c.conflict_note, '')

    def test_reimport_is_idempotent(self):
        rows = [line('102230', '27101-ZWU704', '2029-08-23', 63944),
                line('118639', '27101-ZWU704', '2029-08-23', 63945)]
        coupons.import_purchase_lines(rows)
        rep = coupons.import_purchase_lines(rows)
        self.assertEqual(rep['created'], 0)
        self.assertEqual(CouponSerial.objects.count(), 1)
        self.assertEqual(CouponSerial.objects.get().conflict_note, '')

    def test_non_coupon_lines_are_skipped(self):
        rep = coupons.import_purchase_lines([
            line('102230', '102230', '2021-12-01', 34074),
            line('102230', '20000-ABCFED', '2021-12-01', 34074),
            line('404', '27101-ZWU704', '2029-08-23', 1),
        ])
        self.assertEqual((rep['skipped_serial'], rep['skipped_item']), (2, 1))
        self.assertFalse(CouponSerial.objects.exists())

    def test_single_leg_is_partial(self):
        coupons.import_purchase_lines([line('118639', '26901-LBS116', '2029-02-04', 63943)])
        self.assertEqual(CouponSerial.objects.get().status, 'partial')

    def test_leg_bought_twice_is_flagged_and_earliest_kept(self):
        coupons.import_purchase_lines([
            line('102230', '25300-TOV143', '2030-03-10', 61000, '2026-03-01 00:00:00'),
            line('102230', '25300-TOV143', '2029-01-01', 60000, '2026-01-01 00:00:00'),
        ])
        c = CouponSerial.objects.get()
        self.assertEqual(c.points_docnumber, 60000)
        self.assertIn('two docs', c.conflict_note)

    def test_excel_adds_unknown_serials_and_flags_reissued_numbers(self):
        coupons.import_purchase_lines([line('102230', '22504-SMS307', '2027-01-01', 50000)])
        rep = coupons.import_excel_serials(['22504-SMS307', '22504-ABC123', (17001, 'OGB905'), 'junk'])
        self.assertEqual((rep['created'], rep['already'], rep['invalid']), (2, 1, 1))
        self.assertEqual(CouponSerial.objects.get(serial='17001-OGB905').status, 'unstocked')
        self.assertIn('22504-ABC123', CouponSerial.objects.get(serial='22504-SMS307').conflict_note)
        # SOFTECH data later wins over an Excel-only row.
        coupons.import_purchase_lines([line('118639', '17001-OGB905', '2026-01-01', 40000)])
        self.assertEqual(CouponSerial.objects.get(serial='17001-OGB905').source, 'softech')


class GeneratorTests(TestCase):
    def setUp(self):
        coupons.import_purchase_lines([
            line('102230', '27300-KNQ777', '2030-03-10', 63944),
            line('118639', '27300-KNQ777', '2030-03-10', 63945),
        ])

    def test_batch_continues_numbers_and_never_reuses_dates(self):
        batch = coupons.generate_batch(size=5, blocked_dates={D(2030, 3, 12)})
        serials = list(batch.serials.order_by('number'))
        self.assertEqual([s.number for s in serials], [27301, 27302, 27303, 27304, 27305])
        self.assertEqual([s.points_expiry for s in serials],
                         [D(2030, 3, 11), D(2030, 3, 13), D(2030, 3, 14), D(2030, 3, 15), D(2030, 3, 16)])
        self.assertTrue(all(s.served_expiry == s.points_expiry for s in serials))
        self.assertTrue(all(s.status == 'generated' and s.source == 'generated' for s in serials))
        self.assertEqual((batch.serial_from, batch.serial_to, batch.size), (27301, 27305, 5))
        self.assertEqual(len({s.code for s in serials}), 5)

        nxt = coupons.generate_batch(size=2)
        self.assertEqual(nxt.serial_from, 27306)
        self.assertEqual(nxt.expiry_from, D(2030, 3, 17))

    def test_codes_never_repeat_an_issued_code(self):
        batch = coupons.generate_batch(size=1, rng=_SeqRng(['KNQ777', 'ABC123']))
        self.assertEqual(batch.serials.get().serial, '27301-ABC123')

    def test_overlapping_start_number_is_refused(self):
        with self.assertRaises(ValueError):
            coupons.generate_batch(size=3, start_number=27299)
        self.assertFalse(CouponBatch.objects.exists())

    def test_default_size_is_two_hundred(self):
        self.assertEqual(coupons.generate_batch().serials.count(), 200)


class ExportTests(TestCase):
    def setUp(self):
        coupons.import_purchase_lines([line('102230', '27300-KNQ777', '2030-03-10', 63944)])
        self.batch = coupons.generate_batch(size=6)

    def test_dataload_rows_match_the_rpa_layout(self):
        rows = coupons.dataload_rows(self.batch)
        self.assertEqual(rows[0], coupons.DATALOAD_HEADER)
        self.assertEqual(len(rows), 1 + 2 * 6)
        first = self.batch.serials.order_by('number').first()
        self.assertEqual(rows[1], ['', '', '', '102230', r'\{ENTER}', r'\{TAB}', '1', r'\{TAB}',
                                   '11/03/2030', r'\{TAB}', first.serial, r'\{F2}'])
        self.assertEqual(rows[7][3], '118639')
        self.assertEqual(rows[7][10], first.serial)

    def test_print_sheet_is_collated(self):
        ws = coupons.print_workbook(self.batch).active
        serials = [s.serial for s in self.batch.serials.order_by('number')]
        order = coupons.collated_order(6)
        self.assertEqual(ws['F1'].value, serials[order[0]])
        self.assertEqual(ws['F11'].value, serials[order[1]])
        self.assertEqual(ws['D9'].value, 'قسيمة مشتروات من صيدليات الرزيقى بقيمة 50ج.م')


class SoftechReadTests(TestCase):
    def test_blocked_expiries_reads_both_items(self):
        class Cur:
            def execute(self, sql, params):
                self.params = params

            def fetchall(self):
                return [('2030-03-10 00:00:00',), (None,)]

        cur = Cur()

        class Conn:
            def cursor(self):
                return cur

        self.assertEqual(coupons.read_blocked_expiries(Conn()), {D(2030, 3, 10)})
        self.assertEqual(cur.params, ['102230', '118639'])
