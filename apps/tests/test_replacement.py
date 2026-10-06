"""
Doc 25 Phase 0 — replacement / buy-back case reconstruction.

The acceptance fixture is the REAL Samra case (PIC 130HD16564, branch 130), with the exact
documents found in the live mirrors on 2026-09-28:
  contract 453799 14,921.25 (12 items) − partial return 21531 (item 1463) ; 453805 10,956.96
  fully returned by 21532 (void pair) ; purchase 12095 from 4472 = LOKELMA 100186 8,027 → 5,700 ;
  vouchers 50830 2,023 / 50990 2,177 / 51297 1,500 (native chequestrans) ;
  delivery receipts 455365-7 (2,023.50) + 456071 (2,172) on the patient's PIC ;
  anonymous cash receipt 457751 (1,335.50) 5 min before voucher 51297.
Expected after confirming 457751: products 5,530.50 · cash 169.50 · absorbed 0.50 · balance 0.
"""
from datetime import date, datetime, timezone as dt_tz
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.lineage.models import DocumentEdge
from apps.replacement import matching as M
from apps.replacement import reconstruct as R
from apps.replacement.models import (CaseDocument as CD, CaseException as X,
                                     EntitlementLedgerEntry as E, ReplacementCase as RC,
                                     ReplacementItem)

from .factories import make_user

D = Decimal
PIC = '130HD16564'


def _utc(y, mo, d, h, mi, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=dt_tz.utc)


def _local_midnight(d):
    return timezone.make_aware(datetime(d.year, d.month, d.day))


class SamraFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.branches.models import Branch
        from apps.catalog.models import Item
        from apps.customers.models import Customer
        from apps.finance.recon_models import Allocation, APInvoice, Payment, ReconParty
        from apps.procurement.models import PurchaseLine

        cls.branch = Branch.objects.create(softech_branch_id='130', name='النزهة', name_ar='النزهة')
        cls.other_branch = Branch.objects.create(softech_branch_id='140', name='B140')
        cls.patient = Customer.objects.create(softech_pic=PIC, name='محمد صالح سمره dms', phone='01000600132')
        cls.walkin = Customer.objects.create(softech_pic='130HD1', name='عميل نقدي', phone='0100')
        items = {c: Item.objects.create(softech_id=c, name=n, is_active=True) for c, n in
                 [('100186', 'LOKELMA 5MG'), ('1422', 'ITEM 1422'), ('1463', 'ITEM 1463'), ('9', 'SHAMPOO')]}
        cls.items = items

        cls.party = ReconParty.objects.create(party_type='supplier', softech_personcode='4472',
                                              name='مورد 4472 — مورد شركات 25 - Contract Supplier 25%')
        cls.inv = APInvoice.objects.create(party=cls.party, party_type='supplier', branchcode='130', doccode='10',
                                           docnumber='12095', docdate=date(2026, 7, 21), docnumber2='21072026',
                                           doc_value=D('5700'), doc_value_pay=D('5700'), fat_status='90',
                                           usercode='1509')
        PurchaseLine.objects.create(branch_code='130', supplier_code='4472', doc_number='12095',
                                    doc_date=date(2026, 7, 21), item_code='100186', doccode='10',
                                    raw_qty=D('1'), raw_value=D('5699.997'), unit_price=D('5699.9968'),
                                    public_price=D('8027'), item=items['100186'], branch=cls.branch)
        vouchers = [(50830, date(2026, 7, 25), _utc(2026, 7, 25, 15, 18, 53), D('2023'), '1330'),
                    (50990, date(2026, 8, 2), _utc(2026, 8, 2, 11, 10, 36), D('2177'), '1309'),
                    (51297, date(2026, 8, 22), _utc(2026, 8, 22, 10, 40, 59), D('1500'), '1309')]
        cls.payments = {}
        for sno, vd, tt, amt, uc in vouchers:
            p = Payment.objects.create(party=cls.party, party_type='supplier', branchcode='130', cheqsno=sno,
                                       cheqtype='20', direction='out', voucher_date=vd, bankcode='40',
                                       amount=amt, usercode=uc, trans_time=tt, note=f'سداد {sno}')
            Allocation.objects.create(payment=p, invoice=cls.inv, amount=amt, origin='softech')
            cls.payments[sno] = p

        def sale(docno, doc_code, d, total, phcode, channel, lines, tt=None, cust=None):
            from apps.customers.models import PurchaseHistory, PurchaseHistoryLine
            ph = PurchaseHistory.objects.create(
                customer=cust or cls.patient, branch=cls.branch, doc_code=doc_code, total_amount=total,
                softech_invoice_id=f'130-{doc_code}-{docno}-{d:%Y%m%d}', invoice_date=_local_midnight(d),
                docnumber=str(docno), sales_channel=channel, softech_phcode=phcode, trans_time=tt,
                cust_branch_code='4479' if channel == '10' else '1500')
            for code, qty, unit, lst in lines:
                PurchaseHistoryLine.objects.create(purchase=ph, item=items[code], quantity=qty, unit_price=unit,
                                                   line_total=unit * qty, list_price=lst)
            return ph

        rx = [('100186', D('1'), D('7545.38'), D('8027')), ('1422', D('1'), D('112.8'), D('120'))]
        jul5 = date(2026, 7, 5)
        cls.s453799 = sale(453799, '115', jul5, D('14921.25'), PIC, '10',
                           rx + [('1463', D('1.333'), D('2973.22'), D('3163'))], _utc(2026, 7, 5, 9, 0))
        cls.r21531 = sale(21531, '30', jul5, D('3964.29'), PIC, '10',
                          [('1463', D('1.333'), D('2973.22'), D('3163'))], _utc(2026, 7, 5, 9, 5))
        cls.s453805 = sale(453805, '115', jul5, D('10956.96'), PIC, '10', rx, _utc(2026, 7, 5, 9, 10))
        cls.r21532 = sale(21532, '30', jul5, D('10956.96'), PIC, '10', rx, _utc(2026, 7, 5, 9, 15))
        shampoo = [('9', D('1'), D('100'), D('100'))]
        sale(455365, '115', date(2026, 7, 25), D('1176'), PIC, '90', shampoo, _utc(2026, 7, 25, 14, 37, 16))
        sale(455366, '115', date(2026, 7, 25), D('541.5'), PIC, '90', shampoo, _utc(2026, 7, 25, 14, 37, 21))
        sale(455367, '115', date(2026, 7, 25), D('306'), PIC, '90', shampoo, _utc(2026, 7, 25, 14, 37, 26))
        sale(456071, '115', date(2026, 8, 2), D('2172'), PIC, '90', shampoo, _utc(2026, 8, 2, 11, 1, 27))
        cls.s457751 = sale(457751, '115', date(2026, 8, 22), D('1335.5'), '', '91', shampoo,
                           _utc(2026, 8, 22, 10, 36, 5), cust=cls.walkin)
        sale(457752, '115', date(2026, 8, 22), D('43.33'), '', '91', shampoo,
             _utc(2026, 8, 22, 10, 36, 7), cust=cls.walkin)
        sale(457799, '115', date(2026, 8, 22), D('900'), '', '91', shampoo,       # far in time → ignored
             _utc(2026, 8, 22, 15, 0, 0), cust=cls.walkin)

    def build(self):
        return R.reconstruct_invoice(self.inv, tabdeel=R.tabdeel_pics())['case']

    def docs(self, case, role):
        return list(case.documents.filter(role=role).select_related('document'))


# ═══════════════════════════════════════════════════════════════════════════════
class SamraAcceptanceTests(SamraFixture):

    def test_patient_contract_chain_and_items(self):
        c = self.build()
        self.assertTrue(c.number.startswith('IRC-2026-'))
        self.assertEqual(c.source_type, RC.SOURCE_INSURANCE_RX)
        self.assertEqual(c.softech_pic, PIC)
        self.assertEqual(c.customer, self.patient)
        self.assertEqual(c.contract_personcode, '4479')
        sale = self.docs(c, CD.ROLE_CONTRACT_SALE)
        self.assertEqual([d.document.docnumber for d in sale], ['453799'])
        self.assertEqual([d.document.docnumber for d in self.docs(c, CD.ROLE_CONTRACT_RETURN)], ['21531'])
        self.assertEqual(sorted(d.document.docnumber for d in self.docs(c, CD.ROLE_CONTRACT_VOID)),
                         ['21532', '453805'])
        rep = c.items.get(disposition=ReplacementItem.DISP_REPLACED)
        self.assertEqual((rep.itemcode, rep.qty_replaced, rep.public_unit_price, rep.contract_unit_price),
                         ('100186', D('1'), D('8027'), D('7545.38')))
        dispensed = set(c.items.filter(disposition=ReplacementItem.DISP_DISPENSED).values_list('itemcode', flat=True))
        self.assertEqual(dispensed, {'1422'})           # 1463 was returned by 21531
        self.assertEqual(c.entitlement, D('5700.00'))
        self.assertEqual(c.contract_value, D('7545.38'))
        self.assertEqual(c.applied_deduction_pct, D('28.99'))
        self.assertEqual(c.supplier_tier_pct, D('25'))

    def test_unique_anonymous_receipt_is_auto_confirmed_owner_rule(self):
        """Owner rule 2026-10-02: 457751 is the ONLY no-PIC receipt within 10 min before voucher
        51297 at 80–100 % of it (89 %; the 43.33 receipt is outside the band) → auto-confirmed,
        and the case reaches the acceptance totals with no human step."""
        c = self.build()
        cd = c.documents.get(role=CD.ROLE_PRODUCT_SALE, document__docnumber='457751')
        self.assertEqual(cd.status, CD.STATUS_CONFIRMED)
        self.assertIn('unique_anonymous', [e['signal'] for e in cd.evidence])
        self.assertEqual(c.redeemed_products, D('5530.50'))
        self.assertEqual(c.redeemed_cash, D('169.50'))
        self.assertEqual(c.redeemed_unclassified, D('0.00'))
        self.assertEqual(c.absorbed, D('0.50'))
        self.assertEqual(c.outstanding, D('0.00'))
        self.assertEqual(c.status, RC.STATUS_RECONCILED)
        self.assertFalse(c.exceptions.filter(exception_type='anonymous_receipt', status='open').exists())

    @override_settings(REPLACEMENT_ANON_AUTO_MIN_RATIO=D('2'))      # rule off → manual path
    def test_funding_and_ledger_before_human_confirmation(self):
        c = self.build()
        vouchers = {d.document.docnumber: d for d in self.docs(c, CD.ROLE_VOUCHER)}
        self.assertEqual(set(vouchers), {'50830', '50990', '51297'})
        self.assertTrue(all(v.status == CD.STATUS_CONFIRMED and v.origin == 'native' for v in vouchers.values()))
        funded = lambda sno: sorted((d.document.docnumber, d.status) for d in
                                    c.documents.filter(role=CD.ROLE_PRODUCT_SALE, parent=vouchers[sno]))
        self.assertEqual(funded('50830'), [('455365', 'confirmed'), ('455366', 'confirmed'), ('455367', 'confirmed')])
        self.assertEqual(funded('50990'), [('456071', 'confirmed')])
        self.assertEqual(funded('51297'), [('457751', 'proposed')])      # anonymous → never auto-confirmed
        self.assertEqual(c.redeemed_products, D('4195.00'))            # 2023 + 2172
        self.assertEqual(c.redeemed_cash, D('5.00'))                   # 2177 − 2172 handed out
        self.assertEqual(c.redeemed_unclassified, D('1500.00'))
        self.assertEqual(c.absorbed, D('0.50'))
        self.assertEqual(c.outstanding, D('0.00'))
        self.assertEqual(c.native_outstanding, D('0.00'))
        self.assertEqual(c.status, RC.STATUS_SETTLED)                  # not reconciled: a link is unproven
        self.assertTrue(c.exceptions.filter(exception_type='anonymous_receipt', status='open').exists())
        self.assertFalse(c.exceptions.filter(exception_type='ledger_native_mismatch').exists())

    @override_settings(REPLACEMENT_ANON_AUTO_MIN_RATIO=D('2'))
    def test_confirming_anonymous_receipt_reaches_acceptance_totals(self):
        _, staff, _ = make_user('sup_r', role='supervisor', access_all=True)
        c = self.build()
        n_before = c.ledger.count()
        cd = c.documents.get(role=CD.ROLE_PRODUCT_SALE, document__docnumber='457751')
        from apps.replacement import actions as A
        c = A.decide_link(c, cd.pk, confirm=True, user=staff, note='مؤكد من الكاشير')
        self.assertEqual(c.redeemed_products, D('5530.50'))
        self.assertEqual(c.redeemed_cash, D('169.50'))
        self.assertEqual(c.redeemed_unclassified, D('0.00'))
        self.assertEqual(c.absorbed, D('0.50'))
        self.assertEqual(c.outstanding, D('0.00'))
        self.assertEqual(c.status, RC.STATUS_RECONCILED)
        # append-only: the unclassified debit was REVERSED, not edited
        self.assertEqual(c.ledger.filter(entry_type=E.TYPE_REVERSAL).count(), 1)
        self.assertEqual(c.ledger.count(), n_before + 3)               # reversal + product + cash
        self.assertTrue(AuditLog.objects.filter(action='replacement_link_confirmed', object_id=str(c.pk)).exists())
        edge = DocumentEdge.objects.get(to_ref__docnumber='457751', relation='funded_by')
        self.assertEqual(edge.decided_by, staff)

    @override_settings(REPLACEMENT_ANON_AUTO_MIN_RATIO=D('2'))
    def test_rejecting_anonymous_receipt_is_respected_on_rerun(self):
        _, staff, _ = make_user('sup_r2', role='supervisor', access_all=True)
        c = self.build()
        cd = c.documents.get(role=CD.ROLE_PRODUCT_SALE, document__docnumber='457751')
        from apps.replacement import actions as A
        c = A.decide_link(c, cd.pk, confirm=False, user=staff, note='ليست فاتورة المريض')
        c = self.build()
        active = c.documents.filter(role=CD.ROLE_PRODUCT_SALE, status__in=['proposed', 'confirmed'],
                                    document__docnumber='457751')
        self.assertFalse(active.exists())
        self.assertEqual(c.documents.get(document__docnumber='457751').status, CD.STATUS_REJECTED)

    def test_reconstruction_is_idempotent(self):
        c = self.build()
        n, docs, exc = c.ledger.count(), c.documents.count(), c.exceptions.count()
        c2 = self.build()
        self.assertEqual(c2.pk, c.pk)
        self.assertEqual((c2.ledger.count(), c2.documents.count(), c2.exceptions.count()), (n, docs, exc))
        self.assertEqual(RC.objects.count(), 1)

    def test_native_unlink_reverses_our_debit_and_keeps_invariant(self):
        from apps.finance.recon_models import Allocation
        c = self.build()
        Allocation.objects.filter(payment=self.payments[50990]).delete()   # SOFTECH no longer links it
        c = self.build()
        self.assertEqual(c.outstanding, D('2177.00'))
        self.assertEqual(c.native_outstanding, D('2177.00'))
        self.assertEqual(c.status, RC.STATUS_ENTITLEMENT_ACTIVE)
        self.assertFalse(c.exceptions.filter(exception_type='ledger_native_mismatch', status='open').exists())

    def test_duplicate_purchase_of_same_sale_item_is_flagged_high(self):
        from apps.finance.recon_models import APInvoice, ReconParty
        from apps.procurement.models import PurchaseLine
        self.build()
        p2 = ReconParty.objects.create(party_type='supplier', softech_personcode='4471', name='مورد شركات 30')
        inv2 = APInvoice.objects.create(party=p2, party_type='supplier', branchcode='130', doccode='10',
                                        docnumber='12101', docdate=date(2026, 7, 22), doc_value=D('5600'))
        PurchaseLine.objects.create(branch_code='130', supplier_code='4471', doc_number='12101',
                                    doc_date=date(2026, 7, 22), item_code='100186', doccode='10',
                                    raw_qty=D('1'), raw_value=D('5600'), unit_price=D('5600'),
                                    public_price=D('8027'), item=self.items['100186'], branch=self.branch)
        c2 = R.reconstruct_invoice(inv2)['case']
        dup = c2.exceptions.get(exception_type='duplicate_purchase')
        self.assertEqual(dup.severity, X.SEV_HIGH)
        self.assertEqual(c2.outstanding, D('5600.00'))           # nothing paid on the duplicate

    def test_lineage_tree_shape(self):
        from apps.replacement.graph import build_tree
        t = build_tree(self.build())
        kinds = [n['kind'] for n in t['children']]
        self.assertEqual(kinds[0], 'prescription')
        purchase = next(n for n in t['children'] if n['kind'] == 'purchase')
        self.assertEqual(len(purchase['children']), 3)
        self.assertEqual(sum(len(v['children']) for v in purchase['children']), 5)
        self.assertEqual(t['children'][-1]['kind'], 'balance')


# ═══════════════════════════════════════════════════════════════════════════════
class LedgerImmutabilityTests(SamraFixture):

    def test_entries_cannot_be_edited_or_deleted(self):
        c = self.build()
        e = c.ledger.first()
        e.amount = D('1')
        with self.assertRaises(ValidationError):
            e.save()
        with self.assertRaises(ValidationError):
            e.delete()
        with self.assertRaises(ValidationError):
            c.ledger.all().update(amount=1)
        with self.assertRaises(ValidationError):
            c.ledger.all().delete()

    def test_sign_rules_enforced(self):
        c = self.build()
        with self.assertRaises(ValidationError):
            E.objects.create(case=c, entry_type=E.TYPE_PRODUCT, amount=D('10'))   # debit must be negative
        with self.assertRaises(ValidationError):
            E.objects.create(case=c, entry_type=E.TYPE_CREATED, amount=D('-10'))

    def test_entry_can_be_reversed_only_once(self):
        from django.db import IntegrityError, transaction
        from apps.replacement import ledger as L
        c = self.build()
        e = c.ledger.get(entry_type=E.TYPE_CREATED)
        L.reverse(e)
        with self.assertRaises((IntegrityError, ValidationError)):
            with transaction.atomic():
                L.reverse(e)


# ═══════════════════════════════════════════════════════════════════════════════
class MatchingUnitTests(TestCase):
    def test_pair_returns_full_vs_partial(self):
        d = date(2026, 7, 5)
        a = {'key': 1, 'phcode': 'P', 'date': d, 'total': D('100'), 'lines': {'x': {}, 'y': {}}}
        b = {'key': 2, 'phcode': 'P', 'date': d, 'total': D('60'), 'lines': {'x': {}}}
        full = {'key': 9, 'phcode': 'P', 'date': d, 'total': D('60'), 'lines': {'x': {}}}
        part = {'key': 8, 'phcode': 'P', 'date': d, 'total': D('10'), 'lines': {'y': {}}}
        void, partial = M.pair_returns([a, b], [full, part])
        self.assertEqual(set(void), {2})
        self.assertEqual([r['key'] for r in partial[1]], [8])

    def test_unique_qualifying_anonymous_receipt_auto_confirms(self):
        v = {'amount': D('1000'), 'trans_time': _utc(2026, 1, 1, 10, 0)}
        r = [{'key': 1, 'amount': D('900'), 'phcode': '', 'trans_time': _utc(2026, 1, 1, 9, 55)},
             {'key': 2, 'amount': D('40'), 'phcode': '', 'trans_time': _utc(2026, 1, 1, 9, 56)}]   # below 80 %
        f = M.select_funding(v, r, 'PIC')
        self.assertEqual((f['status'], f['conf'], f['cash_remainder']), ('confirmed', 'high', D('100')))

    def test_two_qualifying_anonymous_receipts_stay_proposed(self):
        v = {'amount': D('1000'), 'trans_time': _utc(2026, 1, 1, 10, 0)}
        r = [{'key': 1, 'amount': D('900'), 'phcode': '', 'trans_time': _utc(2026, 1, 1, 9, 55)},
             {'key': 2, 'amount': D('950'), 'phcode': '', 'trans_time': _utc(2026, 1, 1, 9, 58)}]
        f = M.select_funding(v, r, 'PIC')
        self.assertEqual(f['status'], 'proposed')
        self.assertNotEqual(f['conf'], 'high')

    def test_anonymous_receipt_outside_window_or_band_stays_proposed(self):
        v = {'amount': D('1000'), 'trans_time': _utc(2026, 1, 1, 10, 0)}
        far = [{'key': 1, 'amount': D('950'), 'phcode': '', 'trans_time': _utc(2026, 1, 1, 9, 40)}]   # 20 min before
        self.assertEqual(M.select_funding(v, far, 'PIC')['status'], 'proposed')
        low = [{'key': 1, 'amount': D('600'), 'phcode': '', 'trans_time': _utc(2026, 1, 1, 9, 58)}]   # 60 %
        self.assertEqual(M.select_funding(v, low, 'PIC')['status'], 'proposed')

    def test_topup_vs_absorbed(self):
        v = {'amount': D('1000'), 'trans_time': _utc(2026, 1, 1, 10, 0)}
        small = [{'key': 1, 'amount': D('1004'), 'phcode': 'PIC', 'trans_time': _utc(2026, 1, 1, 9, 40)}]
        self.assertEqual(M.select_funding(v, small, 'PIC')['excess_kind'], 'absorbed')
        big = [{'key': 1, 'amount': D('600'), 'phcode': 'PIC', 'trans_time': _utc(2026, 1, 1, 9, 40)},
               {'key': 2, 'amount': D('500'), 'phcode': 'PIC', 'trans_time': _utc(2026, 1, 1, 9, 41)}]
        f = M.select_funding(v, big, 'PIC')
        self.assertLessEqual(f['total'], D('1010'))      # best subset under voucher + tolerance
        self.assertEqual(f['total'], D('600'))

    def test_tabdeel_account_counts_as_patient_side(self):
        v = {'amount': D('300'), 'trans_time': _utc(2026, 1, 1, 10, 0)}
        r = [{'key': 1, 'amount': D('300'), 'phcode': 'TAB1', 'trans_time': _utc(2026, 1, 1, 9, 50)}]
        f = M.select_funding(v, r, 'PIC', frozenset({'TAB1'}))
        self.assertEqual(f['status'], 'confirmed')

    def test_clock_breaks_same_day_tie_and_coverage_is_proportional(self):
        d = date(2026, 1, 1)
        purchase = {'date': d, 'trans_time': _utc(2026, 1, 1, 12, 0),
                    'lines': {'x': {'qty': D('1'), 'public': D('100')}, 'y': {'qty': D('1'), 'public': D('50')}}}
        line = lambda: {'qty': D('1'), 'unit': D('90'), 'list': D('100')}
        near = {'key': 1, 'phcode': 'A', 'date': d, 'total': D('90'), 'channel': '10',
                'trans_time': _utc(2026, 1, 1, 11, 50), 'lines': {'x': line()}}
        far = {'key': 2, 'phcode': 'B', 'date': d, 'total': D('90'), 'channel': '10',
               'trans_time': _utc(2026, 1, 1, 8, 0), 'lines': {'x': line()}}
        both = {'key': 3, 'phcode': 'C', 'date': d, 'total': D('140'), 'channel': '10',
                'trans_time': _utc(2026, 1, 1, 8, 0), 'lines': {'x': line(), 'y': {**line(), 'list': D('50')}}}
        r = M.resolve_contract_sale(purchase, [near, far], [])
        self.assertEqual(r['sale']['phcode'], 'A')
        self.assertEqual(r['ambiguous_patients'], [])
        r = M.resolve_contract_sale(purchase, [near, far, both], [])
        self.assertEqual(r['sale']['phcode'], 'C')          # covers 2/2 items beats 1/2 + clock

    def test_applied_deduction(self):
        self.assertEqual(M.applied_deduction_pct([{'qty': 1, 'public': 8027, 'value': D('5699.997')}]),
                         D('28.99'))


# ═══════════════════════════════════════════════════════════════════════════════
@override_settings(REPLACEMENT_ANON_AUTO_MIN_RATIO=D('2'))       # keep 457751 proposed for decision tests
class ReplacementApiTests(SamraFixture):

    def setUp(self):
        self.case = self.build()

    def test_supervisor_can_list_search_and_read_detail(self):
        _, _, client = make_user('sup_api', role='supervisor', access_all=True)
        r = client.get('/api/replacement/cases/', {'q': '457751'})       # any document number
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['count'], 1)
        r = client.get(f'/api/replacement/cases/{self.case.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['softech_pic'], PIC)
        self.assertIn('tree', r.data)
        self.assertEqual(len(r.data['ledger']), self.case.ledger.count())
        s = client.get('/api/replacement/cases/summary/')
        self.assertEqual(s.status_code, 200)
        self.assertEqual(s.data['totals']['n'], '1')

    def test_branch_scope(self):
        from apps.branches.models import Branch
        other = Branch.objects.get(softech_branch_id='140')
        _, _, client = make_user('sup_140', role='supervisor', branch=other)
        r = client.get('/api/replacement/cases/')
        self.assertEqual(r.data['count'], 0)
        self.assertEqual(client.get(f'/api/replacement/cases/{self.case.pk}/').status_code, 404)

    def test_roles_without_access_are_denied(self):
        _, _, sales = make_user('sales_r', role='salesperson')
        self.assertEqual(sales.get('/api/replacement/cases/').status_code, 403)
        _, _, purch = make_user('purch_r', role='purchasing', access_all=True)
        self.assertEqual(purch.get('/api/replacement/cases/').status_code, 200)
        cd = self.case.documents.get(role=CD.ROLE_PRODUCT_SALE, document__docnumber='457751')
        r = purch.post(f'/api/replacement/cases/{self.case.pk}/links/{cd.pk}/decide/', {'confirm': True},
                       format='json')
        self.assertEqual(r.status_code, 403)                            # view-only role

    def test_decide_link_endpoint(self):
        _, _, client = make_user('sup_dec', role='supervisor', access_all=True)
        cd = self.case.documents.get(role=CD.ROLE_PRODUCT_SALE, document__docnumber='457751')
        r = client.post(f'/api/replacement/cases/{self.case.pk}/links/{cd.pk}/decide/',
                        {'confirm': True, 'note': 'ok'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['redeemed_products'], '5530.50')
        self.assertEqual(r.data['status'], RC.STATUS_RECONCILED)

    def test_resolve_exception_requires_reason(self):
        _, _, client = make_user('sup_exc', role='supervisor', access_all=True)
        exc = self.case.exceptions.filter(status='open').first()
        url = f'/api/replacement/cases/{self.case.pk}/exceptions/{exc.pk}/decide/'
        self.assertEqual(client.post(url, {'status': 'resolved'}, format='json').status_code, 400)
        r = client.post(url, {'status': 'resolved', 'note': 'تم التحقق'}, format='json')
        self.assertEqual(r.status_code, 200)
        exc.refresh_from_db()
        self.assertEqual(exc.status, X.STATUS_RESOLVED)
