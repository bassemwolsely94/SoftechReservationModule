"""
apps/tests/test_coupon_push.py

Gift-coupon SOFTECH push (apps/vouchers/coupon_push.py) + the purchase-writer extensions it
relies on — WITHOUT any SOFTECH contact (a fake jConnect statement records the SQL batch).
Reference values: real docs 100/10/63944 (points 102230) and 63945 (served 118639).
"""
import datetime as dt
from unittest import mock

from django.test import TestCase, override_settings

from apps.invoices import validations, writer
from apps.invoices.models import InvoiceLine, SupplierInvoice
from apps.vouchers import coupon_push, coupons
from apps.vouchers.models import CouponSerial
from .factories import make_branch, make_item


def _line(item, serial, expiry, doc):
    return {'itemcode': item, 'item_partno': serial, 'itemexpirydate': f'{expiry} 00:00:00',
            'docnumber': doc, 'docdate': '2026-07-15 00:00:00'}


class _RS:
    def __init__(self, cols, rows):
        self.cols, self.rows, self.i = cols, rows, -1

    def getMetaData(self):
        rs = self

        class M:
            def getColumnCount(self):
                return len(rs.cols)

            def getColumnName(self, i):
                return rs.cols[i - 1]
        return M()

    def next(self):
        self.i += 1
        return self.i < len(self.rows)

    def getString(self, i):
        return self.rows[self.i][i - 1]

    def getObject(self, i):
        return self.rows[self.i][i - 1]

    def close(self):
        pass


class _Stmt:
    """Fake java.sql.Statement: records the batch, replays canned result sets."""

    def __init__(self, sets):
        self.sets, self.batch, self.k = sets, None, 0

    def execute(self, batch):
        self.batch = batch
        return bool(self.sets)

    def getResultSet(self):
        return _RS(*self.sets[self.k])

    def getMoreResults(self):
        self.k += 1
        return self.k < len(self.sets)

    def getUpdateCount(self):
        return -1

    def close(self):
        pass


class _Conn:
    def __init__(self, sets):
        self.stmt = _Stmt(sets)

        class J:
            def createStatement(inner):
                return self.stmt
        self._conn = J()


class _Base(TestCase):
    def setUp(self):
        self.hq = make_branch('المركز الرئيسي', '100')
        self.points = make_item('COUPON FOR POINTS', '102230')
        self.served = make_item('COUPON SERVED TO CUSTOMER', '118639')
        coupons.import_purchase_lines([_line('102230', '27300-KNQ777', '2030-03-10', 63944),
                                       _line('118639', '27300-KNQ777', '2030-03-10', 63945)])
        self.batch = coupons.generate_batch(size=3)


class EnsureInvoicesTests(_Base):
    def test_two_invoices_one_line_per_serial(self):
        b = coupon_push.ensure_invoices(self.batch)
        p, s = b.points_invoice, b.served_invoice
        self.assertEqual((p.vendor.softech_personcode, p.softech_branchcode, p.status),
                         ('1268', '100', 'confirmed'))
        serials = list(b.serials.order_by('number'))
        pl = list(p.lines.order_by('order'))
        self.assertEqual([l.batch_number for l in pl], [c.serial for c in serials])
        self.assertEqual([l.expiry_date for l in pl], [c.points_expiry.isoformat() for c in serials])
        self.assertEqual((float(pl[0].public_price), float(pl[0].unit_price), float(pl[0].quantity)),
                         (400.0, 400.0, 1.0))
        sl = s.lines.order_by('order').first()
        self.assertEqual((float(sl.public_price), float(sl.unit_price), sl.item.softech_id),
                         (-50.0, 0.0, '118639'))

    def test_idempotent(self):
        coupon_push.ensure_invoices(self.batch)
        coupon_push.ensure_invoices(self.batch)
        self.assertEqual(SupplierInvoice.objects.count(), 2)
        self.assertEqual(InvoiceLine.objects.count(), 6)


class PlanTests(_Base):
    def test_plan_matches_reference_docs(self):
        b = coupon_push.ensure_invoices(self.batch)
        h, l = coupon_push.leg_extras('points', 3)
        plan = writer.build_plan(b.points_invoice, usercode='1509', header_extra=h, line_extra=l)
        self.assertEqual(plan['doc_value'], 1200.0)
        self.assertEqual(plan['header']['usercode'], '1509')
        first = plan['lines'][0]
        self.assertEqual(first['item_partno'], b.serials.order_by('number').first().serial)
        self.assertEqual((first['transprice'], first['itemsaleprice'], first['pharmacydiscp'],
                          first['custdiscp'], first['dblitemflag']), (400.0, 400.0, 0.0, 1.0, 1))

        h, l = coupon_push.leg_extras('served', 3)
        plan = writer.build_plan(b.served_invoice, usercode='1509', header_extra=h, line_extra=l)
        self.assertEqual(plan['doc_value'], 0.0)
        self.assertEqual((plan['header']['fatstatuscode'], plan['header']['fatcurrentstatus'],
                          plan['header']['docvalue1']), ('30', '90', -150.0))
        first = plan['lines'][0]
        self.assertEqual((first['transprice'], first['itemsaleprice'], first['itemsaleprice_tax'],
                          first['pharmacydiscp'], first['bonusqty'], first['custdiscp']),
                         (0.0, -50.0, -50.0, 100.0, -50.0, 1.0))


class WriteBatchSqlTests(_Base):
    def test_capture_sql_and_readback(self):
        b = coupon_push.ensure_invoices(self.batch)
        inv = b.served_invoice
        computed, header = writer.compute(inv)
        h, l = coupon_push.leg_extras('served', 3)
        conn = _Conn([
            (['branchcode', 'fatstatuscode'], [['100', '30']]),
            (['itemcode', 'item_partno'], [['118639', c.batch_number] for c in inv.lines.order_by('order')]),
            (['docnumber', 'hdr', 'lines', 'err', 'verified'], [['65625', '1', '3', '0', '1']]),
        ])
        res = writer._run_write_batch(conn, inv, computed, header, '10', '1509', {'118639': 0.0},
                                      do_commit=False, header_extra=h, line_extra=l, capture=True)
        sql = conn.stmt.batch
        self.assertIn('rollback tran', sql)
        self.assertNotIn('commit tran', sql)
        self.assertEqual(sql.count('INSERT INTO stktrans '), 3)
        self.assertIn('item_partno', sql)
        self.assertIn("'27301-", sql)
        self.assertIn("'1509'", sql)
        self.assertIn('select * from stktrans where', sql)
        self.assertIn("'30'", sql)
        # running newqty 1, 2, 3 on the three lines
        self.assertIn('1.0, 0.0, ', sql)
        self.assertTrue(res['ok'])
        self.assertEqual(res['docnumber'], 65625)
        self.assertEqual(res['full_header']['fatstatuscode'], '30')
        self.assertEqual(len(res['full_lines']), 3)


class ValidationExceptionTests(_Base):
    def test_zero_cost_allowed_only_for_served_item(self):
        b = coupon_push.ensure_invoices(self.batch)
        v = validations.validate_invoice(b.served_invoice, live=False)
        self.assertEqual(v['errors'], [])
        other = make_item('صنف عادي', '404')
        InvoiceLine.objects.create(invoice=b.served_invoice, item=other, quantity=1,
                                   public_price=0, unit_price=0)
        codes = [e['code'] for e in validations.validate_invoice(b.served_invoice, live=False)['errors']]
        self.assertEqual(codes, ['price_invalid'])

    def test_allow_lists_default_to_coupon_items(self):
        self.assertEqual(validations.allowed_discontinued_items(), {'102230'})
        self.assertEqual(validations.zero_cost_items(), {'118639'})
        with override_settings(INVOICE_ALLOW_DISCONTINUED_ITEMS='1,2'):
            self.assertEqual(validations.allowed_discontinued_items(), {'1', '2'})


class Docnumber2Tests(_Base):
    def _conn(self, top):
        cur = mock.Mock()
        cur.fetchone.return_value = (top,)
        return mock.Mock(cursor=mock.Mock(return_value=cur))

    def test_two_unique_numbers_per_batch(self):
        b = coupon_push.ensure_invoices(self.batch)
        got = coupon_push.assign_docnumber2(b, self._conn(None), day=dt.date(2026, 10, 5))
        self.assertEqual(got, {'points': '510202601', 'served': '510202602'})
        # a retry never re-numbers
        got2 = coupon_push.assign_docnumber2(b, self._conn(510202699), day=dt.date(2026, 10, 5))
        self.assertEqual(got2, got)

    def test_continues_after_softech_and_pending_numbers(self):
        b = coupon_push.ensure_invoices(self.batch)
        got = coupon_push.assign_docnumber2(b, self._conn(2703202602.0), day=dt.date(2026, 3, 27))
        self.assertEqual(got, {'points': '2703202603', 'served': '2703202604'})
        nxt = coupons.generate_batch(size=1)
        nb = coupon_push.ensure_invoices(nxt)
        got = coupon_push.assign_docnumber2(nb, self._conn(2703202602.0), day=dt.date(2026, 3, 27))
        self.assertEqual(got, {'points': '2703202605', 'served': '2703202606'})


class PushTests(_Base):
    def test_commit_refused_while_writer_gate_off(self):
        with self.assertRaises(ValueError):
            coupon_push.push_batch(self.batch, commit=True)

    def test_dry_run_writes_nothing(self):
        res = coupon_push.push_batch(self.batch)
        self.assertEqual({r['mode'] for r in res.values()}, {'dry_run'})
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, 'generated')

    @override_settings(INVOICE_WRITER_ENABLED=True)
    def test_partial_failure_resumes_without_double_post(self):
        docs = iter([70001, None, 70002])
        calls = []

        def fake_push(inv, **kw):
            calls.append((inv.pk, kw['usercode'], kw['line_extra'].get('bonusqty')))
            dn = next(docs)
            if dn is None:
                return {'mode': 'commit', 'wrote_to_softech': False, 'ok': False}
            inv.status, inv.softech_docnumber, inv.softech_docdate = 'finalized', dn, dt.date(2026, 10, 6)
            inv.save()
            return {'mode': 'commit', 'wrote_to_softech': True, 'ok': True, 'docnumber': dn}

        fake_conn = mock.Mock()
        fake_conn.cursor.return_value.fetchone.return_value = (None,)
        with mock.patch('config.sybase.get_sybase_connection', return_value=fake_conn), \
                mock.patch.object(writer, 'push_final', side_effect=fake_push):
            # 1st run: points lands, served fails
            coupon_push.push_batch(self.batch, commit=True)
            self.batch.refresh_from_db()
            self.assertEqual(self.batch.status, 'generated')
            c = self.batch.serials.order_by('number').first()
            self.assertEqual((c.points_docnumber, c.served_docnumber, c.status), (70001, None, 'partial'))
            # 2nd run: points is skipped (already finalized), served lands
            res = coupon_push.push_batch(self.batch, commit=True)
        self.assertEqual(res['points']['mode'], 'already_finalized')
        self.assertEqual([x[2] for x in calls], [None, -50.0, -50.0])
        self.assertEqual(len([x for x in calls if x[2] is None]), 1)   # points pushed exactly once
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, 'stocked')
        self.assertEqual(set(self.batch.serials.values_list('status', flat=True)), {'stocked'})
        self.assertEqual(CouponSerial.objects.filter(served_docnumber=70002).count(), 3)


class DiffTests(TestCase):
    def test_normalised_compare(self):
        ref = {'transprice': 400.0, 'itemexpirydate': dt.datetime(2029, 8, 23), 'usercode': '1509',
               'custdiscp': 1.0, 'docnumber': 63944.0}
        ours = {'transprice': '400.0000', 'itemexpirydate': '2029-08-23 00:00:00.0', 'usercode': '1509',
                'custdiscp': '0.00', 'docnumber': '65625'}
        self.assertEqual(coupon_push.diff_rows(ours, ref, {'docnumber'}),
                         [('custdiscp', '0.00', 1.0)])
