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


class WhatsAppReceiptTests(TestCase):
    """Wave 7 inc2 — POS-order WhatsApp digital-receipt message (pure formatter)."""
    def test_message_lists_items_and_totals(self):
        from apps.pos_orders.views import build_order_whatsapp_message
        o = _order()  # 2 lines: 108 & 216, 15% disc each → gross 324, net 275.40
        msg = build_order_whatsapp_message(o)
        self.assertIn('صيدليات الرزيقي', msg)
        self.assertIn(f'POS-{o.pk}', msg)
        self.assertIn('ITM1', msg)
        self.assertIn('ITM2', msg)
        self.assertIn('الإجمالي: 324.00', msg)   # derived from lines when not yet priced
        self.assertIn('الصافي: 275.40', msg)
        self.assertIn('خصم 15%', msg)

    def test_message_prefers_stored_header_totals_when_priced(self):
        from apps.pos_orders.views import build_order_whatsapp_message
        o = _order()
        writer.prepare_order(o, tenders=[{'pay_type': 'cash', 'amount': '275.40'}])
        o.refresh_from_db()
        msg = build_order_whatsapp_message(o)
        self.assertIn('الصافي: 275.40', msg)
        self.assertIn('بانتظار إتمام الكاشير', msg)  # ready status hint


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

    def test_contract_copay_tender_split(self):
        # Deterministic co-pay split (native golden 7873, contract 4478 = 25% of GROSS pre-discount,
        # patient_paytype '1'): gross 2003.00 → patient 500.75 (cash) + company 1318.80 (credit),
        # summing to doc_value 1819.55. The payment mix then drives fatstatuscode 50 in _header_row.
        from unittest.mock import patch
        o = _order(channel='contract')
        with patch.object(writer, 'read_contract_copay',
                          return_value={'patient_paypercent': 25.0, 'patient_paytype': '1'}):
            tenders = writer._contract_copay_tenders(o, Decimal('1819.55'), Decimal('2003.00'))
        self.assertEqual(len(tenders), 2)
        d = {t['pay_type']: Decimal(t['amount']) for t in tenders}
        self.assertEqual(d['cash'], Decimal('500.75'))       # patient portion (type 30)
        self.assertEqual(d['credit'], Decimal('1318.80'))    # company portion (type 10)
        self.assertEqual(d['cash'] + d['credit'], Decimal('1819.55'))

    def test_contract_copay_paytype2_uses_net(self):
        # patient_paytype != '1' → % is taken from the NET doc_value, not the gross.
        from unittest.mock import patch
        o = _order(channel='contract')
        with patch.object(writer, 'read_contract_copay',
                          return_value={'patient_paypercent': 25.0, 'patient_paytype': '2'}):
            tenders = writer._contract_copay_tenders(o, Decimal('1000.00'), Decimal('2003.00'))
        d = {t['pay_type']: Decimal(t['amount']) for t in tenders}
        self.assertEqual(d['cash'], Decimal('250.00'))       # 25% of NET 1000
        self.assertEqual(d['credit'], Decimal('750.00'))

    def test_contract_copay_none_when_no_rule(self):
        # No co-pay rule (or 0%) → None → prepare_order keeps the 100%-credit posture (fatstatuscode 10).
        from unittest.mock import patch
        o = _order(channel='contract')
        with patch.object(writer, 'read_contract_copay', return_value={}):
            self.assertIsNone(writer._contract_copay_tenders(o, Decimal('100'), Decimal('120')))
        with patch.object(writer, 'read_contract_copay',
                          return_value={'patient_paypercent': 0.0, 'patient_paytype': '1'}):
            self.assertIsNone(writer._contract_copay_tenders(o, Decimal('100'), Decimal('120')))

    def test_contract_derives_line_discount_from_schedule(self):
        # (a) Contract line discount is DERIVED from custdiscounts[acct, item.itemcode_alt3], overriding
        # any fed cust_discp — verified vs golden 7873 (alt3 13→6% imported, 12→15% local).
        from unittest.mock import patch
        o = _order(channel='contract', cust_branch_code='4478')   # _order feeds cust_discp=15 on both
        live = {'107295': {'item_sale_price': 108, 'sale_tax_pct': 0, 'new_cost_price': 81, 'alt3': '13'},
                '94965':  {'item_sale_price': 216, 'sale_tax_pct': 0, 'new_cost_price': 162, 'alt3': '12'}}
        sched = {'13': {'discp': 6.0, 'blocked': False}, '12': {'discp': 15.0, 'blocked': False}}
        with patch.object(writer, 'read_live_pricing', return_value=live), \
             patch.object(writer, 'read_contract_discounts', return_value=sched), \
             patch.object(writer, 'read_contract_branch_blocked', return_value=False), \
             patch.object(writer, 'read_contract_copay', return_value={}):
            writer.prepare_order(o, live=True)
        by = {l.softech_itemcode: l for l in o.lines.all()}
        self.assertEqual(by['107295'].cust_discp, Decimal('6'))    # derived 6%, overrode fed 15
        self.assertEqual(by['94965'].cust_discp, Decimal('15'))

    def test_contract_blocks_ineligible_item(self):
        # (b) An item whose classification is Blocked (allow_sell=0 / custdiscp_nomore='1') is rejected
        # BEFORE any write — mirrors native «هذا الصنف غير مسموح صرفه لهذا التعاقد».
        from unittest.mock import patch
        o = _order(channel='contract', cust_branch_code='4478')
        live = {'107295': {'item_sale_price': 108, 'sale_tax_pct': 0, 'new_cost_price': 81, 'alt3': '13'},
                '94965':  {'item_sale_price': 216, 'sale_tax_pct': 0, 'new_cost_price': 162, 'alt3': '22'}}
        sched = {'13': {'discp': 6.0, 'blocked': False}, '22': {'discp': 0.0, 'blocked': True}}
        with patch.object(writer, 'read_live_pricing', return_value=live), \
             patch.object(writer, 'read_contract_discounts', return_value=sched), \
             patch.object(writer, 'read_contract_branch_blocked', return_value=False), \
             patch.object(writer, 'read_contract_copay', return_value={}):
            with self.assertRaises(ValueError) as cm:
                writer.prepare_order(o, live=True)
        self.assertIn('94965', str(cm.exception))

    def test_contract_branch_block_rejects(self):
        # «OUR Contracted Branches» Block: a named account blocked at this branch (personsdatabranches.
        # personbranchdel='1') can't dispense here — prepare_order rejects before any write.
        from unittest.mock import patch
        o = _order(channel='contract', cust_branch_code='4227')
        live = {'107295': {'item_sale_price': 108, 'sale_tax_pct': 0, 'new_cost_price': 81, 'alt3': '13'},
                '94965':  {'item_sale_price': 216, 'sale_tax_pct': 0, 'new_cost_price': 162, 'alt3': '12'}}
        with patch.object(writer, 'read_live_pricing', return_value=live), \
             patch.object(writer, 'read_contract_discounts', return_value={'13': {'discp': 6.0, 'blocked': False}, '12': {'discp': 15.0, 'blocked': False}}), \
             patch.object(writer, 'read_contract_branch_blocked', return_value=True), \
             patch.object(writer, 'read_contract_copay', return_value={}):
            with self.assertRaises(ValueError) as cm:
                writer.prepare_order(o, live=True)
        self.assertIn('الفرع', str(cm.exception))


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
        # Current _line_row semantics (pkg+unit decomposition + batch-slice allocation):
        #   bonusqty      = the per-UNIT price passed in (NOT bonus_qty)
        #   pharmacydiscp = loose_units_from_qty(alloc qty, packqty)  — the loose-strip count
        #   itemexpirydate = the DISPENSED slice's batch expiry (alloc['expiry']), s_doccode '000'
        from apps.pos_orders.writer import _line_row, _Raw, loose_units_from_qty
        o = _order(channel='cash')
        ln = type('L', (), {
            'softech_itemcode': '404', 'qty': 0.66667, 'trans_price': 9.5, 'new_cost_price': 7,
            'item_sale_price': 28.5, 'item_sale_tax': 0, 'item_sale_price_tax': 28.5, 'cust_discp': 0,
        })()
        # one dispensed FEFO slice (see _allocate_line): 2 loose strips of a 3-strip pack
        alloc = {'qty': 0.66667, 'expiry': '2028-02-28', 'batchno': 'B1',
                 's_doccode': '000', 'reservation': False}
        row = _line_row(o, ln, 999, '1509', alloc, packqty=3, unitprice=9.5)
        self.assertAlmostEqual(row['transqty'], 0.66667, places=5)
        self.assertEqual(row['bonusqty'], 9.5)                                    # per-UNIT price
        self.assertEqual(row['pharmacydiscp'], float(loose_units_from_qty(0.66667, 3)))
        self.assertEqual(row['pharmacydiscp'], 2.0)                               # 2 loose strips
        self.assertEqual(row['s_doccode'], '000')                                # dispensed slice
        self.assertIsInstance(row['itemexpirydate'], _Raw)
        self.assertIn('2028-02-28', row['itemexpirydate'].sql)

    def test_line_row_reservation_slice(self):
        # A shortfall (reservation) slice → item_partno 'Reservation', s_doccode '100', and — verified
        # against native cashier golden 7872 — NULL itemexpirydate and NULL r_docnumber (no placeholder).
        from apps.pos_orders.writer import _line_row
        o = _order(channel='cash')
        ln = type('L', (), {
            'softech_itemcode': '404', 'qty': 1, 'trans_price': 9.5, 'new_cost_price': 7,
            'item_sale_price': 28.5, 'item_sale_tax': 0, 'item_sale_price_tax': 28.5, 'cust_discp': 0,
        })()
        alloc = {'qty': 1, 'expiry': None, 'batchno': 'Reservation',
                 's_doccode': '100', 'reservation': True}
        row = _line_row(o, ln, 999, '1509', alloc, packqty=1, unitprice=9.5)
        self.assertEqual(row['item_partno'], 'Reservation')
        self.assertEqual(row['s_doccode'], '100')
        # FULLY-reserved item (no dispensed slice) → NULL expiry + NULL r_docnumber (golden 7872)
        self.assertIsNone(row.get('itemexpirydate'))
        self.assertIsNone(row.get('r_docnumber'))

    def test_line_row_claim_reservation_placeholder(self):
        # A CLAIM-channel reservation (alloc['placeholder'] set by _allocate_line for contract/employee/…)
        # → native stamps the 2012-12-12 placeholder expiry, EVEN for a fully-reserved item (golden 7875
        # employee 113275/120049; also 7873 contract). cash/delivery leave it NULL (test above).
        from apps.pos_orders.writer import _line_row, _Raw
        o = _order(channel='contract')
        ln = type('L', (), {
            'softech_itemcode': '3476', 'qty': 1, 'trans_price': 9.5, 'new_cost_price': 7,
            'item_sale_price': 28.5, 'item_sale_tax': 0, 'item_sale_price_tax': 28.5, 'cust_discp': 0,
        })()
        alloc = {'qty': 1, 'expiry': None, 'batchno': 'Reservation',
                 's_doccode': '100', 'reservation': True, 'placeholder': True}
        row = _line_row(o, ln, 999, '1509', alloc, packqty=1, unitprice=9.5)
        self.assertEqual(row['s_doccode'], '100')
        self.assertEqual(row['item_partno'], 'Reservation')
        self.assertIsInstance(row['itemexpirydate'], _Raw)   # placeholder present
        self.assertIsNone(row.get('r_docnumber'))            # still NULL

    def test_line_row_service_no_batch_slice(self):
        # A non-stockable / no-batch dispensed slice → s_doccode '000' + EMPTY item_partno (not NULL),
        # NULL expiry / r_docnumber / r_docdate — verified vs native golden 7872 (items '1','2').
        from apps.pos_orders.writer import _line_row
        o = _order(channel='cash')
        ln = type('L', (), {
            'softech_itemcode': '2', 'qty': 1, 'trans_price': 13.0, 'new_cost_price': 0,
            'item_sale_price': 13.0, 'item_sale_tax': 0, 'item_sale_price_tax': 13.0, 'cust_discp': 0,
        })()
        alloc = {'qty': 1, 'expiry': None, 'batchno': None, 's_doccode': None, 'reservation': False}
        row = _line_row(o, ln, 999, '1509', alloc, packqty=1, unitprice=13.0)
        self.assertEqual(row['s_doccode'], '000')
        self.assertEqual(row['item_partno'], '')
        self.assertIsNone(row.get('itemexpirydate'))
        self.assertIsNone(row.get('r_docnumber'))
        self.assertIsNone(row.get('r_docdate'))

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


class ReturnTests(TestCase):
    """The مرتجع (return) writeback — mirror the original finalized sale as a pending doccode-30 doc.
    Verified end-to-end vs native return 534 ← finalized sale 7044."""

    def _return_order(self):
        o = _order(channel='cash', doc_kind='return', return_of_invoice=7044)
        o.source_header_raw = {'sale_docdate': '2026-09-05 00:00:00'}
        o.save()
        return o

    def test_line_row_from_raw_return_overrides(self):
        # A RETURN line mirrors the sale line but overrides r_docnumber→sale, r_docdate→sale date,
        # retqty→0, vf4→negated (native 534: sale 7044 vf4 +15 → return −15).
        from apps.pos_orders.writer import _line_row_from_raw, _Raw
        o = self._return_order()
        raw = {'itemcode': '404', 'transqty': 1.0, 'transprice': 38.0, 'transprice_total': 38.0,
               'itemsaleprice': 38.0, 'bonusqty': 38.0, 'dblitemflag': 1, 'custdiscp': 0.0, 's_doccode': '000',
               'itemexpirydate': {'__dt__': '2028-03-31 00:00:00'}, 'r_docnumber': 0.0, 'retqty': 1.0,
               'vf4': 15, 'personcode': '1510'}
        row = _line_row_from_raw(o, raw, 544, '1509')
        self.assertEqual(row['r_docnumber'], 7044)          # links to the original sale
        self.assertIsInstance(row['r_docdate'], _Raw)       # the sale's date (not 1900-01-01)
        self.assertEqual(row['retqty'], 0.0)                # reset on the return
        self.assertEqual(row['vf4'], -15)                   # points reversed
        self.assertEqual(row['s_doccode'], '000')
        self.assertEqual(row['transqty'], 1.0)              # positive (doccode 30 makes it a reversal)

    def test_line_row_from_raw_clone_unchanged(self):
        # A plain CLONE (doc_kind='sale') keeps the source values — return overrides must NOT leak.
        from apps.pos_orders.writer import _line_row_from_raw
        o = _order(channel='cash', doc_kind='sale')
        raw = {'itemcode': '404', 'transqty': 1.0, 'transprice': 38.0, 'transprice_total': 38.0,
               'itemsaleprice': 38.0, 'bonusqty': 38.0, 'dblitemflag': 1, 'r_docnumber': 0.0,
               'retqty': 1.0, 'vf4': 15, 'personcode': '1510'}
        row = _line_row_from_raw(o, raw, 900, '1509')
        self.assertEqual(row['r_docnumber'], 0)
        self.assertEqual(row['retqty'], 1.0)                # kept as-is
        self.assertNotIn('vf4', row)                        # clone sets no vf4

    def test_order_points_return_reverses_recorded(self):
        # A return's points = −(sale's RECORDED vf4), NOT a live recompute (native 534: −15).
        from apps.pos_orders import points
        o = self._return_order()
        lns = list(o.lines.all())
        lns[0].source_raw = {'vf4': 15}; lns[0].save()
        lns[1].source_raw = {'vf4': 8};  lns[1].save()
        total, _ = points.order_points(o)
        self.assertEqual(total, -23)                        # −(15+8), no branch DB touched

    def test_build_return_full_vs_partial(self):
        # FULL return mirrors the sale's payment rows exactly; PARTIAL (drop a line / reduce qty) keeps
        # only the chosen lines and RECOMPUTES the refund from them.
        from unittest.mock import patch
        o = _order(channel='delivery', doc_kind='return', return_of_invoice=7046, cust_branch_code='1500')
        # read_finalized_sale now annotates each line with returnable / blocked / returned_prev.
        fake = [{'itemcode': 'A', 'dblitemflag': 1, 'transqty': 1.0, 'transprice_total': 100.0,
                 'itemsaleprice': 100.0, 'custdiscp': 0, 'vf4': 10, 's_doccode': '000',
                 'returnable': 1.0, 'blocked': False, 'returned_prev': 0, 'is_reservation': False},
                {'itemcode': 'B', 'dblitemflag': 2, 'transqty': 1.0, 'transprice_total': 50.0,
                 'itemsaleprice': 50.0, 'custdiscp': 0, 'vf4': 5, 's_doccode': '000',
                 'returnable': 1.0, 'blocked': False, 'returned_prev': 0, 'is_reservation': False}]
        pays = [{'paymenttype': '30', 'paymentvalue': 150.0}]
        with patch.object(writer, 'read_finalized_sale', return_value=('2026-09-05 00:00:00', fake, pays)), \
             patch.object(writer, 'read_return_full_only', return_value=False):
            writer.build_return_from_sale(o)                                    # FULL (pristine) → mirror
            self.assertEqual(o.lines.count(), 2)
            self.assertEqual([(p.pay_type, str(p.amount)) for p in o.payments.all()], [('cash', '150.00')])
            writer.build_return_from_sale(o, selection=[{'dblitemflag': 1}])    # PARTIAL → drop line 2
            self.assertEqual(o.lines.count(), 1)
            self.assertEqual([(p.pay_type, float(p.amount)) for p in o.payments.all()], [('cash', 100.0)])
            writer.build_return_from_sale(o, selection=[{'dblitemflag': 1, 'qty': 0.5}])  # PARTIAL qty
            self.assertEqual(float(o.lines.first().qty), 0.5)
            self.assertEqual([float(p.amount) for p in o.payments.all()], [50.0])          # 100 × 0.5

    def test_build_return_contract_copay_partial_split(self):
        # A PARTIAL contract co-pay return splits patient-cash + company-credit proportional to the
        # RETURNED gross (contract 25% → cash 25%×gross, credit = net − that).
        from unittest.mock import patch
        o = _order(channel='contract', doc_kind='return', return_of_invoice=7047, cust_branch_code='4478')
        fake = [{'itemcode': 'X', 'dblitemflag': 1, 'transqty': 2.0, 'transprice_total': 176.0,
                 'itemsaleprice': 100.0, 'custdiscp': 12, 'vf4': None, 's_doccode': '000',
                 'returnable': 2.0, 'blocked': False, 'returned_prev': 0, 'is_reservation': False}]  # gross 200, net 176
        with patch.object(writer, 'read_finalized_sale', return_value=('2026-09-05 00:00:00', fake, [])), \
             patch.object(writer, 'read_return_full_only', return_value=False), \
             patch.object(writer, 'read_contract_copay', return_value={'patient_paypercent': 25.0, 'patient_paytype': '1'}):
            writer.build_return_from_sale(o, selection=[{'dblitemflag': 1}])
        d = {p.pay_type: float(p.amount) for p in o.payments.all()}
        self.assertEqual(d['cash'], 50.0)      # 25% × gross 200
        self.assertEqual(d['credit'], 126.0)   # net 176 − 50

    def test_build_return_excludes_blocked_and_already_returned(self):
        # Only dispensed, not-yet-returned lines are returnable: a delivered reservation (s_doccode 200,
        # blocked) and an already-fully-returned dispensed line (returnable 0) are both left out.
        from unittest.mock import patch
        o = _order(channel='contract', doc_kind='return', return_of_invoice=7052, cust_branch_code='4479')
        fake = [
            {'itemcode': 'A', 'dblitemflag': 1, 'transqty': 1.0, 'transprice_total': 100.0, 'itemsaleprice': 100.0,
             'custdiscp': 0, 'vf4': None, 's_doccode': '000', 'returnable': 1.0, 'blocked': False, 'returned_prev': 0, 'is_reservation': False},
            {'itemcode': 'B', 'dblitemflag': 2, 'transqty': 1.0, 'transprice_total': 50.0, 'itemsaleprice': 50.0,
             'custdiscp': 0, 'vf4': None, 's_doccode': '200', 'returnable': 0.0, 'blocked': True, 'block_reason': 'resv', 'returned_prev': 0, 'is_reservation': True},
            {'itemcode': 'C', 'dblitemflag': 3, 'transqty': 1.0, 'transprice_total': 30.0, 'itemsaleprice': 30.0,
             'custdiscp': 0, 'vf4': None, 's_doccode': '000', 'returnable': 0.0, 'blocked': False, 'returned_prev': 1.0, 'is_reservation': False},
        ]
        with patch.object(writer, 'read_finalized_sale', return_value=('2026-09-05 00:00:00', fake, [])), \
             patch.object(writer, 'read_return_full_only', return_value=False), \
             patch.object(writer, 'read_contract_copay', return_value={}):
            writer.build_return_from_sale(o)
        self.assertEqual([l.softech_itemcode for l in o.lines.all()], ['A'])   # B blocked, C already returned

    def test_build_return_full_only_rejects_partial(self):
        # A full-invoice-only account (empftime='1') rejects a partial return.
        from unittest.mock import patch
        o = _order(channel='contract', doc_kind='return', return_of_invoice=7052, cust_branch_code='4478')
        fake = [{'itemcode': 'A', 'dblitemflag': 1, 'transqty': 1.0, 'transprice_total': 100.0, 'itemsaleprice': 100.0,
                 'custdiscp': 0, 'vf4': None, 's_doccode': '000', 'returnable': 1.0, 'blocked': False, 'returned_prev': 0, 'is_reservation': False},
                {'itemcode': 'B', 'dblitemflag': 2, 'transqty': 1.0, 'transprice_total': 50.0, 'itemsaleprice': 50.0,
                 'custdiscp': 0, 'vf4': None, 's_doccode': '000', 'returnable': 1.0, 'blocked': False, 'returned_prev': 0, 'is_reservation': False}]
        with patch.object(writer, 'read_finalized_sale', return_value=('2026-09-05 00:00:00', fake, [])), \
             patch.object(writer, 'read_return_full_only', return_value=True), \
             patch.object(writer, 'read_contract_copay', return_value={}):
            with self.assertRaises(ValueError):
                writer.build_return_from_sale(o, selection=[{'dblitemflag': 1}])   # partial → rejected
