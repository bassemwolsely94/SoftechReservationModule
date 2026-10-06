"""
Tests for the Feature-2 Stage-A ISR writer (apps/purchasing/isr_writer.py).
Pure logic only — serial prefix, qty rounding, gate/guards, and the batch SQL
(serial alloc + inserts + verify). Live SOFTECH paths are exercised via the gated
dry-run / rollback probe in ops.
"""
import datetime

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.purchasing import isr_writer


class CoverageTests(TestCase):
    """Batch 2 — coverage re-scales order qty via calc_gap; None keeps the frozen gap."""

    def test_calc_gap_scales_throughput_keeps_floor(self):
        from apps.purchasing.engine import calc_gap
        # safety floor 10 (1-mo calibrated), monthly_avg 4, on-hand 0
        self.assertEqual(calc_gap(0, 10, 4, 0.5), 10)   # floor binds (4×0.5=2 < 10)
        self.assertEqual(calc_gap(0, 10, 4, 1.0), 10)   # floor still binds (4 < 10)
        self.assertEqual(calc_gap(0, 10, 4, 3.0), 12)   # throughput 4×3=12 overtakes floor
        # coverage never distorts an overstock (negative) signal
        self.assertEqual(calc_gap(100, -5, 4, 3.0), -88)  # max(-5, 12) − 100

    def test_persist_proposal_stores_coverage(self):
        lines = [{'itemcode': '1', 'item_name': 'X', 'itemqty': 2, 'itemqty_cfarma': 2.0,
                  'nowqty': 0, 'itemsaleprice': 10, 'itemcostprice': 5, 'suppcode': '9', 'gap': 2.0}]
        p = isr_writer._persist_proposal(source='130', dest='130',
                                         kind='self', lines=lines, coverage_months=1.5)
        self.assertEqual(p.coverage_months, 1.5)
        self.assertEqual(p.line_count, 1)

    def test_persist_proposal_default_coverage_none(self):
        lines = [{'itemcode': '1', 'item_name': 'X', 'itemqty': 2, 'itemqty_cfarma': 2.0,
                  'nowqty': 0, 'itemsaleprice': 10, 'itemcostprice': 5, 'suppcode': '9', 'gap': 2.0}]
        p = isr_writer._persist_proposal(source='130', dest='130', kind='self', lines=lines)
        self.assertIsNone(p.coverage_months)


class SerialAndQtyTests(TestCase):
    def test_prefix_is_year_plus_branch(self):
        d = datetime.date(2026, 9, 16)
        self.assertEqual(isr_writer.isr_prefix('150', on_date=d), '26150')   # 2615041 = 26|150|41
        self.assertEqual(isr_writer.isr_prefix('100', on_date=d), '26100')   # 26100574 = 26|100|574

    def test_int_qty_round_half_up(self):
        self.assertEqual(isr_writer._int_qty(2.5), 3)
        self.assertEqual(isr_writer._int_qty(2.4), 2)
        self.assertEqual(isr_writer._int_qty(0), 0)
        self.assertEqual(isr_writer._int_qty(None), 0)


class GateTests(TestCase):
    @override_settings(ISR_WRITER_ENABLED=False)
    def test_gate_off_by_default(self):
        self.assertFalse(isr_writer.writer_enabled())

    @override_settings(ISR_AUTO_APPROVE_ENABLED=False)
    def test_auto_approve_gate_off_by_default(self):
        self.assertFalse(isr_writer.auto_approve_enabled())

    def test_probe_requires_confirm(self):
        with self.assertRaises(ValueError):
            isr_writer.probe_isr_write('150', confirm=False)

    def test_probe_approve_requires_confirm(self):
        with self.assertRaises(ValueError):
            isr_writer.probe_approve_isr('130', 261305, confirm=False)


class GenerateCommandTests(TestCase):
    def test_requires_a_branch(self):
        with self.assertRaises(CommandError):
            call_command('generate_isr')

    @override_settings(ISR_AUTO_APPROVE_ENABLED=False, ISR_WRITER_ENABLED=False)
    def test_refuses_auto_approve_when_gated(self):
        # gate is checked before any generation → no SOFTECH/engine needed
        with self.assertRaises(CommandError):
            call_command('generate_isr', '--branch', '130', '--auto-approve')


class SerialAllocTests(TestCase):
    def test_next_serial_first_of_year(self):
        self.assertEqual(isr_writer._next_isrdocnumber(None, '26150'), 261501)

    def test_next_serial_increments(self):
        # 2615041 (serial 41) → 2615042
        self.assertEqual(isr_writer._next_isrdocnumber(2615041, '26150'), 2615042)

    def test_next_serial_width_rollover(self):
        # serial 999 → 1000 must NOT be mx+1 (26150999+1=26151000, wrong prefix)
        self.assertEqual(isr_writer._next_isrdocnumber(26150999, '26150'), 261501000)

    def test_next_serial_hq_prefix(self):
        # 26100574 → 26100575 (HQ)
        self.assertEqual(isr_writer._next_isrdocnumber(26100574, '26100'), 26100575)


class HeaderRowTests(TestCase):
    def test_header_row_self_request(self):
        h = isr_writer._header_row('130', '130', 261307, 14141.038, '1509')
        self.assertEqual(h['branchcode'], '130')          # source (preparer/node)
        self.assertEqual(h['forbranchcode'], '130')       # dest (receiver) — self here
        self.assertEqual(h['isrdocnumber'], 261307)
        self.assertEqual(h['docstatuscode'], 0)
        self.assertEqual(h['israpp'], 0)                  # unapproved → native review queue
        sql = isr_writer._insert_sql('stockisrm', h)
        self.assertIn('INSERT INTO stockisrm', sql)       # the header table is what makes it retrievable
        self.assertIn('getdate()', sql)

    def test_header_row_interbranch_source_dest_distinct(self):
        # L2 leg 1: surplus branch 160 prepares → HQ 100 receives
        h = isr_writer._header_row('160', '100', 2616099, 500.0, '1509', israpp=1)
        self.assertEqual(h['branchcode'], '160')          # SOURCE
        self.assertEqual(h['forbranchcode'], '100')       # DEST (HQ)
        self.assertEqual(h['israpp'], 1)                  # approved


class LineRowTests(TestCase):
    def test_line_row_maps_fields(self):
        ln = {'itemcode': '87602', 'itemqty': 3, 'itemqty_cfarma': -3.0, 'nowqty': 3.0,
              'itemsaleprice': 220.5, 'itemcostprice': 176.4, 'suppcode': '4691'}
        row = isr_writer._line_row(ln, 2615042, 1, '1509')
        self.assertEqual(row['isrdocnumber'], 2615042)
        self.assertEqual(row['isrdblitemflag'], 1)
        self.assertEqual(row['itemcode'], '87602')
        self.assertEqual(row['itemsource'], 4)                 # Report
        self.assertEqual(row['item_topo'], 0)
        self.assertEqual(row['suppcode'], '4691')
        self.assertEqual(row['posuppcode'], '4691')
        sql = isr_writer._insert_sql('stockisr', row)
        self.assertIn('INSERT INTO stockisr', sql)
        self.assertIn("'87602'", sql)
        self.assertIn('getdate()', sql)                        # trans_time inline
        self.assertIn('2615042', sql)
