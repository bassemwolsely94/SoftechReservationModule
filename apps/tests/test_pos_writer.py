"""
apps/tests/test_pos_writer.py

Covers the Indirect-POS writer WITHOUT any SOFTECH contact:
  - prepare_order computes header/line money fields (spec §6d)
  - payment-imbalance is rejected
  - build_payload shape: 3 tables, correct doccode / ptclassifcode / counter column
  - SQL sequence (BEGIN TRAN → UPDATE counter → INSERT … → COMMIT)
  - idempotency token fits stktransm5.vf2 (varchar(15))
  - returns use the _in_cust counter + r_docnumber link
  - GATE: writer never writes when disabled; raises WriterDisabled when enabled-but-unimplemented
"""
from decimal import Decimal
from django.test import TestCase, override_settings

from apps.pos_orders import writer
from apps.pos_orders.models import (
    SoftechSalesOrder, SoftechSalesOrderLine, SoftechSalesOrderPayment,
)
from .factories import make_branch


def _order(channel='contract', doc_kind='sale', **kw):
    br = make_branch()
    o = SoftechSalesOrder.objects.create(
        branch=br, softech_branchcode=br.softech_branch_id, store_code=br.softech_branch_id[:3],
        channel=channel, doc_kind=doc_kind, softech_pic='130HD9668',
        customer_name='TEST', seller_usercode='2050', referral_doctor_code='REF1', **kw,
    )
    SoftechSalesOrderLine.objects.create(order=o, item=None, softech_itemcode='107295',
                                         item_name='ITM1', qty=1, item_sale_price=108,
                                         sale_tax_pct=0, cust_discp=15, new_cost_price='81.1306')
    SoftechSalesOrderLine.objects.create(order=o, item=None, softech_itemcode='94965',
                                         item_name='ITM2', qty=1, item_sale_price=216,
                                         sale_tax_pct=0, cust_discp=15, new_cost_price='162.0824')
    return o


class PrepareTests(TestCase):
    def test_prepare_computes_money_fields(self):
        o = _order()
        writer.prepare_order(o, tenders=[
            {'pay_type': 'cash', 'amount': '64.80'}, {'pay_type': 'credit', 'amount': '210.60'}])
        o.refresh_from_db()
        self.assertEqual(o.status, SoftechSalesOrder.STATUS_READY)
        self.assertEqual(o.doc_value, Decimal('275.40'))
        self.assertEqual(o.doc_value_gross, Decimal('324.00'))
        self.assertEqual(o.doc_value_cogs, Decimal('243.21'))
        self.assertEqual(o.doc_value_pay, Decimal('64.80'))
        self.assertEqual(o.patient_payment, Decimal('64.80'))
        self.assertEqual(o.payments.count(), 2)
        self.assertIsNotNone(o.client_token)

    def test_prepare_rejects_unbalanced_payment(self):
        o = _order()
        with self.assertRaises(ValueError):
            writer.prepare_order(o, tenders=[{'pay_type': 'cash', 'amount': '100.00'}])  # ≠ 275.40

    def test_prepare_derives_from_existing_payments_when_no_tenders(self):
        o = _order()
        SoftechSalesOrderPayment.objects.create(order=o, pay_type='cash', amount='64.80')
        SoftechSalesOrderPayment.objects.create(order=o, pay_type='credit', amount='210.60')
        writer.prepare_order(o)  # no tenders arg → reuse existing rows
        o.refresh_from_db()
        self.assertEqual(o.doc_value_pay, Decimal('64.80'))

    def test_prepare_requires_lines(self):
        br = make_branch()
        o = SoftechSalesOrder.objects.create(branch=br, softech_branchcode=br.softech_branch_id,
                                             store_code='130', channel='cash')
        with self.assertRaises(ValueError):
            writer.prepare_order(o)


class PayloadTests(TestCase):
    def test_payload_shape_and_mapping(self):
        o = _order(channel='contract', doc_kind='sale')
        writer.prepare_order(o, tenders=[
            {'pay_type': 'cash', 'amount': '64.80'}, {'pay_type': 'credit', 'amount': '210.60'}])
        plan = writer.build_payload(o)
        self.assertEqual(plan['header']['doccode'], '115')
        self.assertEqual(plan['header']['ptclassifcode'], '10')   # contract
        self.assertEqual(plan['header']['phcode'], '130HD9668')
        self.assertEqual(plan['header']['refdoctorcode'], 'REF1')
        self.assertEqual(len(plan['lines']), 2)
        self.assertEqual(len(plan['payments']), 2)
        # payment type mapping: credit→10, cash→30
        ptypes = sorted(p['paymenttype'] for p in plan['payments'])
        self.assertEqual(ptypes, ['10', '30'])

    def test_sql_sequence(self):
        o = _order(channel='cash')
        writer.prepare_order(o, tenders=[{'pay_type': 'cash', 'amount': '275.40'}])
        sql = writer.build_payload(o)['sql']
        self.assertEqual(sql[0], 'BEGIN TRAN')
        self.assertIn('lastdocnumberout_cust', sql[1])   # sale → _out_cust counter
        self.assertEqual(sql[-1], 'COMMIT')

    def test_cloned_line_keeps_expiry_and_native_fields(self):
        # The faithful-clone path must reproduce itemexpirydate (the batch) + native
        # fields (bonusqty/dblitemflag) verbatim — this is what makes a sale returnable.
        from apps.pos_orders.writer import _line_row_from_raw, _Raw
        o = _order(channel='contract')
        raw = {
            'itemcode': '107295', 'transqty': 1.0, 'transprice': 91.8, 'newqty': 2.66667,
            'newcostprice': 81.1306, 'itemexpirydate': {'__dt__': '2028-02-01 22:00:00'},
            'itemsaleprice': 108.0, 'itemsalestax': 0.0, 'itemsaleprice_tax': 108.0,
            'transprice_total': 91.8, 'custdiscp': 15.0, 'bonusqty': 36.0, 'dblitemflag': 1,
            'suppliercode': '0', 'personcode': '4474', 'r_docnumber': 0.0, 'retqty': 0.0,
        }
        row = _line_row_from_raw(o, raw, 999, '1509')
        self.assertIsInstance(row['itemexpirydate'], _Raw)
        self.assertIn('2028-02-01 22:00:00', row['itemexpirydate'].sql)   # exact batch, tz-safe
        self.assertEqual(row['bonusqty'], 36.0)         # native value, not recomputed
        self.assertEqual(row['dblitemflag'], 1)
        self.assertEqual(row['docnumber'], 999)         # new identity
        self.assertEqual(row['itemcode'], '107295')

    def test_push_recovers_existing_by_vf2(self):
        # SOFTECH committed but PG crashed before saving the number → next push must ADOPT
        # the existing docnumber (by vf2 tag), never insert a duplicate.
        from unittest import mock
        from django.test import override_settings
        from apps.pos_orders import writer
        from apps.pos_orders.models import SoftechSalesOrder
        o = _order(channel='cash')
        o.branch.db_host = '10.0.0.9'; o.branch.save()
        o.status = SoftechSalesOrder.STATUS_READY; o.save()
        with override_settings(POS_WRITER_ENABLED=True), \
             mock.patch('config.sybase.get_branch_connection', return_value=mock.MagicMock()), \
             mock.patch.object(writer, 'build_payload', return_value={}), \
             mock.patch.object(writer, '_pending_docnumber_by_vf2', return_value=468999):
            res = writer.push_order(o, dry_run=False)
        self.assertEqual(res['mode'], 'idempotent_recovered')
        self.assertEqual(res['docnumber'], 468999)
        o.refresh_from_db()
        self.assertEqual(int(o.softech_docnumber), 468999)
        self.assertEqual(o.status, SoftechSalesOrder.STATUS_PUSHED)

    def test_line_row_uses_bonus_and_expiry_fields(self):
        # bonus_qty → bonusqty; item_expiry → itemexpirydate (fresh picked-batch line)
        from apps.pos_orders.writer import _line_row, _Raw
        import datetime
        o = _order(channel='cash')
        ln = type('L', (), {
            'softech_itemcode': '404', 'qty': 2, 'trans_price': 38, 'new_cost_price': 30,
            'item_sale_price': 38, 'item_sale_tax': 0, 'item_sale_price_tax': 38,
            'trans_price_total': 76, 'cust_discp': 0, 'bonus_qty': 5,
            'item_expiry': datetime.date(2028, 2, 28),
        })()
        row = _line_row(o, ln, 999, '1509')
        self.assertEqual(row['bonusqty'], 5.0)               # not trans_price_total anymore
        self.assertIsInstance(row['itemexpirydate'], _Raw)
        self.assertIn('2028-02-28', row['itemexpirydate'].sql)

    def test_payment_row_maps_tender_extras(self):
        from apps.pos_orders.writer import _payment_row, _Raw
        import datetime
        o = _order(channel='cash')
        p = type('P', (), {
            'softech_paymenttype': '40', 'amount': 100, 'card_brand': 2,
            'cheque_date': datetime.date(2026, 7, 1), 'cheque_card_no': '1234',
            'internal_payserial': '77', 'currency': 'USD', 'exchange_rate': 50,
        })()
        row = _payment_row(o, p, 999, 497000, '1509')
        self.assertEqual(row['bcrate'], 50.0)
        self.assertEqual(row['bcurrency'], 0)                # non-local currency
        self.assertEqual(row['paymentvaluebc'], 2.0)        # 100 / 50
        self.assertEqual(row['creditcardtype'], 2)
        self.assertEqual(row['comment'], '1234')
        self.assertEqual(row['localpayment_sno'], 77)
        self.assertIsInstance(row['cheqdate'], _Raw)

    def test_contract_companions_built_from_source(self):
        # companiesitems5 (claim) + branchesalescc5 (cost-center) must be reproduced so a
        # contract duplicate settles into a RETURNABLE sale.
        from apps.pos_orders.writer import _companies_row, _cc_row, _Raw
        o = _order(channel='contract')
        o.source_companies_raw = {
            'patientname': 'ABC', 'patientno': '500145123261', 'membershipno': 'dms',
            'roshettano': '28700', 'relativedegree': '01206666004',
            'examdate': {'__dt__': '2026-06-21 00:00:00'}, 'cdate': {'__dt__': '2026-06-21 00:00:00'},
        }
        crow = _companies_row(o, o.source_companies_raw, 999)
        self.assertEqual(crow['docnumber'], 999)
        self.assertEqual(crow['patientno'], '500145123261')
        self.assertEqual(crow['membershipno'], 'dms')
        self.assertEqual(crow['roshettano'], '28700')
        self.assertIsInstance(crow['examdate'], _Raw)        # tz-safe datetime literal
        self.assertEqual(crow['doccode'], '115')

        ccrow = _cc_row(o, {'costcentercode': '00/000', 'moneyvalue': 32.19}, 999, 497044, '1509')
        self.assertEqual(ccrow['paymentsno'], 497044)        # ← links to the credit tender
        self.assertEqual(ccrow['moneyvalue'], 32.19)
        self.assertEqual(ccrow['costcentercode'], '00/000')
        self.assertEqual(ccrow['docnumber'], 999)

    def test_vf2_token_fits_varchar15(self):
        o = _order()
        writer.prepare_order(o, tenders=[{'pay_type': 'cash', 'amount': '275.40'}])
        token = writer.build_payload(o)['header']['vf2']
        self.assertLessEqual(len(token), 15)
        self.assertTrue(token.startswith('POS'))

    def test_return_uses_in_counter_and_links_invoice(self):
        o = _order(channel='contract', doc_kind='return', return_of_invoice=452724)
        writer.prepare_order(o, tenders=[
            {'pay_type': 'cash', 'amount': '64.80'}, {'pay_type': 'credit', 'amount': '210.60'}])
        plan = writer.build_payload(o)
        self.assertEqual(plan['header']['doccode'], '30')
        self.assertIn('lastdocnumberin_cust', plan['sql'][1])      # return → _in_cust counter
        self.assertEqual(plan['lines'][0]['r_docnumber'], '452724')


class GateTests(TestCase):
    def test_disabled_writer_dry_run_only(self):
        o = _order(channel='cash')
        res = writer.push_order(o, dry_run=True)
        self.assertEqual(res['mode'], 'dry_run')
        self.assertFalse(res['wrote_to_softech'])
        self.assertIn('plan', res)
        o.refresh_from_db()
        self.assertEqual(o.status, SoftechSalesOrder.STATUS_READY)

    def test_disabled_writer_blocks_real_write(self):
        # even asking for a non-dry-run while gate is OFF returns the dry-run plan, never writes
        o = _order(channel='cash')
        res = writer.push_order(o, dry_run=False)
        self.assertFalse(res['wrote_to_softech'])

    @override_settings(POS_WRITER_ENABLED=True)
    def test_enabled_commit_path_reached_but_no_branch_db(self):
        # Gate ON + dry_run=False → commit path (not dry-run). With no branch db_host
        # it can't connect, so it raises ValueError — proving it reached the live path
        # and did NOT silently fall back to dry-run.
        o = _order(channel='cash')  # make_branch() has no db_host
        writer.prepare_order(o, tenders=[{'pay_type': 'cash', 'amount': '275.40'}])
        with self.assertRaises(ValueError):
            writer.push_order(o, dry_run=False)

    @override_settings(POS_WRITER_ENABLED=True)
    def test_enabled_dry_run_still_no_write(self):
        # Even with the gate ON, an explicit dry_run=True returns the plan, never writes.
        o = _order(channel='cash')
        res = writer.push_order(o, dry_run=True)
        self.assertEqual(res['mode'], 'dry_run')
        self.assertFalse(res['wrote_to_softech'])

    def test_cancel_unsettled_ok(self):
        o = _order(channel='cash')
        writer.cancel_order(o)
        o.refresh_from_db()
        self.assertEqual(o.status, SoftechSalesOrder.STATUS_CANCELLED)

    def test_cancel_settled_rejected(self):
        o = _order(channel='cash')
        o.status = SoftechSalesOrder.STATUS_SETTLED
        o.save()
        with self.assertRaises(ValueError):
            writer.cancel_order(o)

    def test_cancel_pushed_order_requires_writer(self):
        # A pushed order lives in SOFTECH; cancelling must delete it there → needs the gate
        o = _order(channel='cash')
        o.status = SoftechSalesOrder.STATUS_PUSHED
        o.softech_docnumber = 468813
        o.save()
        with self.assertRaises(writer.WriterDisabled):
            writer.cancel_order(o)

    @override_settings(POS_WRITER_ENABLED=True)
    def test_cancel_pushed_gate_on_reaches_softech_delete(self):
        # Gate ON → reaches the live SOFTECH delete; no db_host → ValueError (proves it
        # didn't silently flip status without deleting the pending rows).
        o = _order(channel='cash')
        o.status = SoftechSalesOrder.STATUS_PUSHED
        o.softech_docnumber = 468813
        o.save()
        with self.assertRaises(ValueError):
            writer.cancel_order(o)
        o.refresh_from_db()
        self.assertEqual(o.status, SoftechSalesOrder.STATUS_PUSHED)  # NOT flipped to cancelled
