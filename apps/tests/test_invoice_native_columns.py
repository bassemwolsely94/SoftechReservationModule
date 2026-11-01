"""The OCR purchase writer sends what the native «مشتريات من الموردين» screen sends.
custdiscp = 1.0 on purchase lines (owner-approved 2026-10-31; 862/871 native lines on
branch 130; rollback probe 2026-10-26 showed no trigger sets it). Returns stay 0."""
from types import SimpleNamespace as NS

from django.test import SimpleTestCase

from apps.invoices import writer as IW


def _invoice(kind):
    return NS(softech_branchcode='130', store_code='130', softech_doccode='10' if kind == 'purchase' else '120',
              doc_kind=kind, return_of_docnumber=0, vendor=NS(softech_personcode='565'))


def _entry():
    line = NS(expiry_date='2028-06-06', quantity=2, batch_number='', item=NS(softech_id='1356'))
    return {'_line': line, 'qty': 2, 'itemsalestax': 0.0, 'itemsaleprice_tax': 338.0,
            'pharmacydiscp': 18.947, 'additionaldiscp': 0.0, 'specialdiscp': 0.0,
            'transprice': 273.96, 'transprice_total': 547.92, 'origintaxp': 0.0, 'itemsaleprice': 338.0}


class NativeCustdiscpTests(SimpleTestCase):
    def test_purchase_line_sends_native_custdiscp(self):
        row = IW._line_row(_invoice('purchase'), _entry(), 1, '1', 2)
        self.assertEqual(row['custdiscp'], 1.0)

    def test_return_line_keeps_zero(self):
        row = IW._line_row(_invoice('return'), _entry(), 1, '1', 0)
        self.assertEqual(row['custdiscp'], 0.0)


class _Lines(list):
    def select_related(self, *a):
        return self

    def all(self):
        return self


def _vinvoice(kind, *lines):
    return NS(doc_kind=kind, vendor=NS(softech_personcode='565'), lines=_Lines(lines),
              invoice_number='8823747321', invoice_date='2026-10-29')


def _vline(lid, batch, required):
    return NS(id=lid, item_id=lid, quantity=2, unit_price=273.96, public_price=338,
              discount_pct=0, extra_discount_pct=0, batch_number=batch, manual_name='', raw_text='',
              item=NS(name='ENTRESTO 100MG', softech_id='120468', batch_required=required))


class BatchRequiredValidationTests(SimpleTestCase):
    """SOFTECH items.itempartno = 1 (Entresto, Kisqali…) → the batch must be entered
    before posting; it lands in stktrans.item_partno. Owner rule 2026-10-31."""
    def _codes(self, inv):
        from apps.invoices import validations
        return [e['code'] for e in validations.validate_invoice(inv, live=False)['errors']]

    def test_required_batch_missing_blocks(self):
        self.assertIn('batch_required', self._codes(_vinvoice('purchase', _vline(1, '', True))))

    def test_required_batch_present_ok(self):
        self.assertNotIn('batch_required', self._codes(_vinvoice('purchase', _vline(1, 'VR75C9G', True))))

    def test_optional_batch_may_be_empty(self):
        self.assertNotIn('batch_required', self._codes(_vinvoice('purchase', _vline(1, '', False))))

    def test_returns_not_checked(self):
        self.assertNotIn('batch_required', self._codes(_vinvoice('return', _vline(1, '', True))))


class BigSupplierNumberTests(SimpleTestCase):
    """PharmaOverseas prints 10-digit invoice numbers (8823747203 > 2^31). The push
    duplicate guard bound it as an int → «Cannot convert value to Java int» and the
    push failed (invoice 224, 2026-10-31). It must bind as Decimal."""
    def test_push_duplicate_guard_binds_decimal(self):
        from decimal import Decimal
        from unittest import mock
        inv = NS(pk=224, softech_docnumber=None, status='review', doc_kind='purchase',
                 invoice_number='8823747203', softech_doccode='10', softech_branchcode='100',
                 store_code='100', client_token='t', vendor=NS(softech_personcode='565'),
                 branch=NS(db_port=5000, db_name='SOFTECHDB9'), save=lambda **k: None)
        seen = []

        def q1(conn, sql, params):
            seen.append(params)
            return (70001,)                         # pretend SofTech already has it
        with mock.patch.object(IW, 'build_plan', return_value={}), \
             mock.patch.object(IW, 'writer_enabled', return_value=True), \
             mock.patch('apps.invoices.validations.validate_invoice',
                        return_value={'errors': [], 'warnings': []}), \
             mock.patch.object(IW, 'branch_host', return_value='h'), \
             mock.patch.object(IW, 'compute', return_value=([], {})), \
             mock.patch('config.sybase.get_branch_connection', return_value=mock.Mock()), \
             mock.patch.object(IW, '_q1', side_effect=q1):
            res = IW.push_final(inv, dry_run=False)
        self.assertEqual(res['mode'], 'idempotent')
        self.assertIsInstance(seen[0][2], Decimal)
        self.assertEqual(seen[0][2], Decimal('8823747203'))


class NativeTaxAndBonusTotalsTests(SimpleTestCase):
    """Decoded 2026-10-31 from hand-entered PharmaOverseas docs 66176 / 66173 (box
    «الضريبة من التكلفة» unticked): taxed line saleprice_extrap = VAT %, header
    docvalue3 = Σ tax, docvalue = Σ line totals + tax, docvalue1 = Σ bonusqty."""
    def test_header_totals_match_doc_66176(self):
        rows = [
            {'transprice_total': 266.68, 'itemsalestax': 9.3338, 'transqty': 4},
            {'transprice_total': 399.999, 'itemsalestax': 18.6666, 'transqty': 3},
            {'transprice_total': 626.50, 'itemsalestax': 0, 'transqty': 1},
        ]
        t = IW._native_purchase_totals(rows)
        self.assertEqual(t['docvalue3'], 93.33)
        self.assertEqual(t['docvalue'], round(266.68 + 399.999 + 626.50 + 93.3352, 2))
        self.assertEqual(t['docvaluebc'], t['docvalue'])
        self.assertEqual(t['docvalue1'], 0)

    def test_bonus_value_goes_to_docvalue1_not_docvalue(self):
        rows = [{'transprice_total': 562.0, 'itemsalestax': 0, 'transqty': 10, 'bonusqty': 0},
                {'transprice_total': 0.0, 'itemsalestax': 0, 'transqty': 1, 'bonusqty': 56.2}]
        t = IW._native_purchase_totals(rows)
        self.assertEqual((t['docvalue'], t['docvalue1']), (562.0, 56.2))

    def _row(self, P, net, qty=2, Pb=None, tax=0.0):
        return {'itemsaleprice': P, 'itemsaleprice_tax': Pb or P, 'transprice': net, 'transqty': qty,
                'additionaldiscp': 0.0, 'specialdiscp': 0.0, 'itemsalestax': tax, 'storecode2': '0'}

    def test_taxed_line_matches_hand_entry_66178(self):
        # SWEETAL: our engine row → the exact values SofTech stored for the hand entry
        row = IW._finish_purchase_line(self._row(130.0, 91.23, Pb=114.035, tax=12.7723),
                                       {'vat_pct': 14.0001}, {})
        self.assertEqual(row['itemsaleprice_tax'], 114.0351)
        self.assertEqual(row['pharmacydiscp'], 19.9983)
        self.assertEqual(row['itemsalestax'], 12.7722)
        self.assertEqual(row['transprice'], 104.0022)          # VAT inside the cost (box ticked)
        self.assertEqual(row['transprice_total'], 208.0044)
        self.assertEqual((row['storecode2'], row['saleprice_extrap']), ('1', 14.0))

    def test_taxed_line_dozova_rounding(self):
        row = IW._finish_purchase_line(self._row(149.0, 104.561, Pb=130.702, tax=14.6385),
                                       {'vat_pct': 14}, {})
        self.assertEqual((row['transprice'], row['transprice_total']), (119.1996, 238.3992))

    def test_untaxed_margin_line_matches_66178(self):
        # ACTRAPID: cost to post 273.96 → SofTech derives it from the 4-place discount
        row = IW._finish_purchase_line(self._row(338.0, 273.96), {'vat_pct': 0}, {})
        self.assertEqual(row['pharmacydiscp'], 18.9467)
        self.assertEqual((row['transprice'], row['transprice_total']), (273.9602, 547.9204))
        self.assertEqual((row['storecode2'], row['saleprice_extrap'], row['itemsalestax']), ('0', 0.0, 0.0))

    def test_override_owns_money_columns(self):
        # replacement buy-back zeroes VAT through line_extra → nothing re-derived, no VAT %
        row = self._row(130.0, 91.23, tax=0.0)
        out = IW._finish_purchase_line(dict(row), {'vat_pct': 14},
                                       {'itemsalestax': 0.0, 'itemsaleprice_tax': 130.0, 'pharmacydiscp': 29.8})
        self.assertEqual((out['transprice'], out['saleprice_extrap']), (91.23, 0.0))

    def test_vat_in_cost_not_counted_twice_in_header(self):
        rows = [{'transprice_total': 208.0044, 'itemsalestax': 12.7722, 'transqty': 2, 'storecode2': '1'},
                {'transprice_total': 547.9204, 'itemsalestax': 0, 'transqty': 2, 'storecode2': '0'}]
        t = IW._native_purchase_totals(rows)
        self.assertEqual((t['docvalue'], t['docvalue3']), (755.92, 0.0))

    def test_free_line_carries_bonus_value(self):
        from apps.invoices import grid
        line = NS(item_id=1, item=NS(softech_id='3502', pack_price=71, pack_price_tax=0, sale_tax_pct=0),
                  public_price=71, unit_price=56.2, quantity=10, bonus_qty=1, vat_pct=0,
                  discount_pct=20.8451, extra_discount_pct=0, special_discount_pct=0, tax_from_cost=True,
                  distributor_margin_amt=0)
        paid, free = grid.computed_entries(line)
        self.assertAlmostEqual(free['bonus_value'], 56.2)
        self.assertNotIn('bonus_value', paid)


class ReturnMirrorsOriginalTests(SimpleTestCase):
    """A return copies the ORIGINAL SofTech purchase line (native «Select From Original
    Purchases», verified on hand-entered returns 11319–11323) — never the module's own
    lines, which can change after posting (return 11324 took the wrong expiry buckets and
    returned margin lines 30 EGP short because it didn't)."""
    from datetime import datetime as _dt
    ORIG = {'itemcode': '1213', 'transprice': 51.75, 'pharmacydiscp': 26.0714, 'additionaldiscp': 0.0,
            'specialdiscp': 0.0, 'itemsalestax': 0.0, 'itemsaleprice': 70.0, 'itemsaleprice_tax': 70.0,
            'origintaxp': 0.0, 'storecode2': '0', 'saleprice_extrap': 0.0, 'custdiscp': 1.0,
            'newcostprice': 51.75, 'bonusqty': 0.0, 'itemexpirydate': _dt(2029, 6, 1), 'item_partno': '610626'}

    def test_line_copies_original_with_returned_qty(self):
        row = {'transprice': 50.25, 'transprice_total': 100.5, 'itemexpirydate': None}
        IW._mirror_original(row, dict(self.ORIG), 1)
        self.assertEqual((row['transprice'], row['transprice_total']), (51.75, 51.75))
        self.assertEqual(row['item_partno'], '610626')
        self.assertIn('2029-06-01', row['itemexpirydate'].sql)
        self.assertEqual((row['newcostprice'], row['custdiscp'], row['storecode2']), (51.75, 1.0, '0'))

    def test_bonus_entry_reverses_the_free_line(self):
        paid = dict(self.ORIG); free = dict(self.ORIG, transprice=0.0, bonusqty=51.75)
        lines = {'1213': [paid, free]}
        self.assertIs(IW._take_original(lines, '1213', True), free)
        self.assertIs(IW._take_original(lines, '1213', False), paid)
        self.assertIsNone(IW._take_original(lines, '1213', False))      # each line used once
        self.assertIsNone(IW._take_original(lines, '9999', False))

    def test_duplicates_only_among_same_kind(self):
        self.assertEqual(IW.same_kind(NS(doc_kind='purchase')), {'doc_kind': 'purchase'})
        self.assertEqual(IW.same_kind(NS(doc_kind='return', return_of_docnumber=66177)),
                         {'doc_kind': 'return', 'return_of_docnumber': 66177})


class NativeAfterSaveTests(SimpleTestCase):
    """The native screen's own statements after a save (captured purchase 66179 / return
    11325): supplier balance ± docvalue, item↔supplier link, original marked returned."""
    def _inv(self, kind, orig=0):
        return NS(doc_kind=kind, return_of_docnumber=orig, vendor=NS(softech_personcode='565'))

    def test_purchase_moves_balance_and_links_items(self):
        rows = [{'itemcode': '113523', 'transprice': 231.5789, 'pharmacydiscp': 20.0, 'additionaldiscp': 0,
                 'specialdiscp': 0, 'itemsaleprice': 330.0, 'itemsalestax': 32.4211, 'saleprice_extrap': 14.0,
                 'storecode2': '0'},
                {'itemcode': '113523', 'transprice': 0.0}]                      # free line: no 2nd link
        sql, expected = IW._native_after_save(self._inv('purchase'), {'docvalue': 4172.02}, rows, [], '100')
        self.assertIn("personcredit = personcredit + 4172.02 where personcode = '565'", sql)
        self.assertEqual(sql.count('insert into itemssuppliers'), 1)
        self.assertIn("if not exists (select 1 from itemssuppliers where itemcode = '113523'", sql)
        self.assertIn('231.5789, 32.4211, 14.0)', sql)
        self.assertEqual(expected, 1)                   # only the balance update is row-counted

    def test_vat_in_cost_link_keeps_pre_tax_cost(self):
        rows = [{'itemcode': '114479', 'transprice': 104.0022, 'saleprice_extrap': 14.0, 'storecode2': '1',
                 'itemsaleprice': 130.0, 'itemsalestax': 12.7722, 'pharmacydiscp': 19.9983}]
        sql, _ = IW._native_after_save(self._inv('purchase'), {'docvalue': 208.0}, rows, [], '100')
        self.assertIn(', 91.23, 12.7722, 14.0)', sql)

    def test_return_reverses_balance_and_marks_original(self):
        sql, expected = IW._native_after_save(self._inv('return', 66179), {'docvalue': 264.0},
                                              [{'transprice_total': 231.578, 'itemsalestax': 16.2105, 'transqty': 2}],
                                              [(4, '129591', 2.0)], '100')
        self.assertIn('personcredit = personcredit - 264.0', sql)
        self.assertIn('docvaluereturn = docvaluereturn + 264.0', sql)
        self.assertIn("retqty = retqty + 2.0 where branchcode = '100' and doccode = '10' and docnumber = 66179 "
                      "and itemcode = '129591' and dblitemflag = 4", sql)
        self.assertEqual(expected, 3)
