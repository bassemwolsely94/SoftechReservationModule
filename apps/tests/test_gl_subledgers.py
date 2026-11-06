"""Sub-ledgers linked to A/P reconciliation and receivables (finance-gl Plan 3, Task 5)."""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from apps.finance.gl.ledger import approve, reverse, save_draft
from apps.finance.gl.subledgers import SUBLEDGERS, subledger, supplier_vs_ap
from apps.finance.models import GLAccount, GLAccountGroup, GLParty, ReconParty
from apps.finance.recon_models import APInvoice, Payment
from apps.users.models import StaffProfile

D = datetime.date
Z = Decimal('0')


def _d(v):
    return Decimal(str(v))


class SubledgerBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        u = User.objects.create_user(username='gl_sub_u', password='x')
        cls.staff, _ = StaffProfile.objects.get_or_create(user=u)
        g_bs = GLAccountGroup.objects.create(name='مجموعة اختبار', section='balance_sheet', order=1)
        g_partner = GLAccountGroup.objects.create(name='جارى الشركاء', section='balance_sheet', order=2)
        mk = GLAccount.objects.create
        mk(code='1101', name='الخزينة', group=g_bs, nature='debit', account_type='asset')
        mk(code='2341', name='الموردين', group=g_bs, nature='credit', account_type='liability')
        mk(code='2351', name='دائنون', group=g_bs, nature='credit', account_type='liability')
        mk(code='2354', name='مقاصة', group=g_bs, nature='credit', account_type='liability')
        mk(code='2343', name='أوراق دفع', group=g_bs, nature='credit', account_type='liability')
        mk(code='1341', name='العملاء', group=g_bs, nature='debit', account_type='asset')
        mk(code='1351', name='مدينون موظفون', group=g_bs, nature='debit', account_type='asset')
        mk(code='2501', name='جارى شريك أ', group=g_partner, nature='credit', account_type='equity')
        mk(code='2502', name='جارى شريك ب', group=g_partner, nature='credit', account_type='equity')

    def post(self, amount, day, debit, credit, party='', cheque='', due=None, party_on='credit'):
        """One two-line entry; party/cheque/due sit on the side named by `party_on`."""
        extra = {'party_code': party, 'cheque_no': cheque, 'due_date': due}
        dr = {'account_code': debit, 'debit': _d(amount), 'credit': Z}
        cr = {'account_code': credit, 'debit': Z, 'credit': _d(amount)}
        (cr if party_on == 'credit' else dr).update(extra)
        e = save_draft(user=self.staff, entry_date=day, description='x', lines=[dr, cr])
        return approve(e.id, user=self.staff)


class SubledgerTests(SubledgerBase):
    def setUp(self):
        GLParty.objects.create(party_type='supplier', code='S1', name='مورد أول')
        GLParty.objects.create(party_type='supplier', code='S2', name='مورد ثان')

    def test_supplier_rows_per_party_with_opening(self):
        self.post(300, D(2026, 2, 10), '1101', '2341', party='S1')   # opening for a March window
        self.post(100, D(2026, 3, 5), '1101', '2341', party='S1')
        self.post(40, D(2026, 3, 9), '2341', '1101', party='S1', party_on='debit')
        self.post(70, D(2026, 3, 12), '1101', '2341', party='S2')
        self.post(50, D(2026, 4, 1), '1101', '2341', party='S2')   # after date_to
        res = subledger('suppliers', D(2026, 3, 1), D(2026, 3, 31))
        rows = {r['key']: r for r in res['rows']}
        s1 = rows['S1']
        self.assertEqual(s1['name'], 'مورد أول')
        self.assertEqual((s1['opening'], s1['debit'], s1['credit'], s1['closing']),
                         (_d(300), _d(40), _d(100), _d(360)))
        self.assertEqual((rows['S2']['opening'], rows['S2']['closing']), (Z, _d(70)))
        self.assertEqual(res['totals']['closing'], _d(430))
        self.assertEqual(res['totals']['opening'], _d(300))
        self.assertIsNone(res['unassigned'])

    def test_settled_party_before_the_window_makes_no_row(self):
        self.post(80, D(2026, 2, 5), '1101', '2341', party='S2')
        self.post(80, D(2026, 2, 6), '2341', '1101', party='S2', party_on='debit')
        res = subledger('suppliers', D(2026, 3, 1), D(2026, 3, 31))
        self.assertEqual(res['rows'], [])
        self.assertEqual(res['totals']['closing'], Z)

    def test_reversed_entry_nets_out(self):
        e = self.post(100, D(2026, 3, 5), '1101', '2341', party='S1')
        reverse(e.id, user=self.staff, reason='r')
        res = subledger('suppliers', D(2026, 3, 1), D(2026, 3, 31))
        # the original and its mirror both count: movement shows, the balance is nil
        self.assertEqual([(r['debit'], r['credit'], r['closing']) for r in res['rows']],
                         [(_d(100), _d(100), Z)])

    def test_unassigned_lines_row(self):
        self.post(100, D(2026, 3, 5), '1101', '2341', party='S1')
        self.post(60, D(2026, 3, 6), '1101', '2341')
        res = subledger('suppliers', D(2026, 3, 1), D(2026, 3, 31))
        self.assertEqual([r['key'] for r in res['rows']], ['S1'])
        un = res['unassigned']
        self.assertEqual((un['key'], un['name'], un['closing']), ('', 'بدون طرف', _d(60)))
        self.assertEqual(res['totals']['closing'], _d(160))   # the total is the account's balance

    def test_creditors_are_2351_only(self):
        self.post(10, D(2026, 3, 5), '1101', '2351', party='S1')
        self.post(99, D(2026, 3, 5), '1101', '2354', party='S1')
        res = subledger('creditors', D(2026, 3, 1), D(2026, 3, 31))
        self.assertEqual(res['totals']['closing'], _d(10))
        self.assertEqual(SUBLEDGERS['creditors']['accounts'], ['2351'])

    def test_notes_payable_grouped_by_due_month_and_paid_cheques_drop_out(self):
        self.post(100, D(2026, 2, 1), '1101', '2343', party='S1', cheque='C1', due=D(2026, 4, 10))
        self.post(200, D(2026, 2, 2), '1101', '2343', party='S2', cheque='C2', due=D(2026, 4, 25))
        self.post(300, D(2026, 2, 3), '1101', '2343', party='S1', cheque='C3', due=D(2026, 5, 1))
        self.post(50, D(2026, 2, 4), '1101', '2343', cheque='C4')   # no due date
        self.post(100, D(2026, 3, 1), '2343', '1101', cheque='C1', party_on='debit')   # paid
        res = subledger('notes_payable', D(2026, 1, 1), D(2026, 3, 31))
        self.assertEqual([r['key'] for r in res['rows']], ['2026-04', '2026-05', ''])
        april, may, undated = res['rows']
        self.assertEqual([c['cheque_no'] for c in april['cheques']], ['C2'])
        self.assertEqual(april['cheques'][0]['party'], 'مورد ثان')
        self.assertEqual(april['cheques'][0]['due_date'], D(2026, 4, 25))
        self.assertEqual(april['cheques'][0]['amount'], _d(200))
        self.assertEqual(may['closing'], _d(300))
        self.assertEqual((undated['name'], undated['closing']), ('بدون تاريخ استحقاق', _d(50)))
        self.assertEqual(res['totals']['closing'], _d(550))
        # before the payment date the cheque is still open
        early = subledger('notes_payable', D(2026, 1, 1), D(2026, 2, 28))
        self.assertEqual(early['rows'][0]['cheques'][0]['cheque_no'], 'C1')

    def test_notes_payable_zero_net_cheque_is_not_open(self):
        # the ledger refuses a zero-amount line, so "zero" is a cheque whose lines net out
        self.post(40, D(2026, 2, 1), '1101', '2343', cheque='C0', due=D(2026, 4, 1))
        self.post(40, D(2026, 2, 2), '2343', '1101', cheque='C0', party_on='debit')
        res = subledger('notes_payable', D(2026, 1, 1), D(2026, 3, 31))
        self.assertEqual(res['rows'], [])

    def test_partners_by_account(self):
        self.post(500, D(2026, 2, 1), '1101', '2501')
        self.post(200, D(2026, 3, 1), '1101', '2502')
        self.post(120, D(2026, 3, 2), '2501', '1101', party_on='debit')
        res = subledger('partners', D(2026, 3, 1), D(2026, 3, 31))
        rows = {r['key']: r for r in res['rows']}
        self.assertEqual(set(rows), {'2501', '2502'})
        self.assertEqual(rows['2501']['name'], 'جارى شريك أ')
        self.assertEqual((rows['2501']['opening'], rows['2501']['closing']), (_d(500), _d(380)))
        self.assertEqual(rows['2502']['closing'], _d(200))
        self.assertEqual(res['totals']['closing'], _d(580))

    def test_customers_are_debit_nature_and_link_to_receivables(self):
        GLParty.objects.create(party_type='customer', code='S1', name='عميل', status='confirmed',
                               softech_personcode='4410')
        self.post(90, D(2026, 3, 5), '1341', '1101', party='S1', party_on='debit')
        res = subledger('customers', D(2026, 3, 1), D(2026, 3, 31))
        row = res['rows'][0]
        self.assertEqual((row['name'], row['closing']), ('عميل', _d(90)))   # not the supplier S1
        self.assertEqual(row['link'], {'to': '/finance/receivables', 'personcode': '4410'})

    def test_supplier_link_only_for_confirmed_party(self):
        GLParty.objects.filter(code='S1').update(status='confirmed', softech_personcode='77001')
        GLParty.objects.filter(code='S2').update(status='proposed', softech_personcode='77002')
        self.post(10, D(2026, 3, 5), '1101', '2341', party='S1')
        self.post(10, D(2026, 3, 5), '1101', '2341', party='S2')
        self.post(10, D(2026, 3, 5), '1101', '2341', party='S3')   # no GLParty at all
        rows = {r['key']: r for r in subledger('suppliers', D(2026, 3, 1), D(2026, 3, 31))['rows']}
        self.assertEqual(rows['S1']['link'], {'to': '/reconciliation', 'party': '77001'})
        self.assertIsNone(rows['S2']['link'])
        self.assertIsNone(rows['S3']['link'])
        self.assertEqual(rows['S3']['name'], 'S3')


class SupplierVsApTests(SubledgerBase):
    def setUp(self):
        self.rp = ReconParty.objects.create(party_type='supplier', softech_personcode='77001', name='s',
                                            opening_balance=_d(1000), opening_balance_date=D(2026, 1, 1))
        GLParty.objects.create(party_type='supplier', code='S1', name='مورد مربوط',
                               softech_personcode='77001', status='confirmed', recon_party=self.rp)
        GLParty.objects.create(party_type='supplier', code='S2', name='غير مربوط')
        rp3 = ReconParty.objects.create(party_type='supplier', softech_personcode='77003', name='late',
                                        opening_balance=_d(5), opening_balance_date=D(2026, 6, 1))
        GLParty.objects.create(party_type='supplier', code='S3', name='افتتاحي لاحق',
                               softech_personcode='77003', status='confirmed', recon_party=rp3)

    def test_supplier_vs_ap_difference(self):
        APInvoice.objects.create(party=self.rp, branchcode='100', doccode='10', docnumber='1',
                                 docdate=D(2026, 3, 10), doc_value=_d(500), party_type='supplier')
        Payment.objects.create(party=self.rp, branchcode='100', cheqsno=1, direction='out',
                               party_type='supplier', voucher_date=D(2026, 3, 20), amount=_d(200))
        APInvoice.objects.create(party=self.rp, branchcode='100', doccode='10', docnumber='2',
                                 docdate=D(2026, 4, 5), doc_value=_d(999), party_type='supplier')
        self.post(1200, D(2026, 3, 20), '1101', '2341', party='S1')
        self.post(70, D(2026, 3, 21), '1101', '2341', party='S2')
        self.post(5, D(2026, 3, 21), '1101', '2341', party='S3')
        rows = {r['party_code']: r for r in supplier_vs_ap(D(2026, 3, 31))}
        s1 = rows['S1']
        self.assertEqual((s1['gl_balance'], s1['ap_balance'], s1['difference'], s1['reason']),
                         (_d(1200), _d(1300), _d(-100), ''))
        self.assertEqual(s1['name'], 'مورد مربوط')
        s2 = rows['S2']
        self.assertEqual((s2['gl_balance'], s2['ap_balance'], s2['difference']), (_d(70), None, None))
        self.assertEqual(s2['reason'], 'لا يوجد ربط بسوفتيك')
        self.assertEqual(rows['S3']['reason'], 'رصيد افتتاحي بعد التاريخ')
        self.assertIsNone(rows['S3']['ap_balance'])

    def test_linked_party_with_ap_balance_and_empty_ledger_is_listed(self):
        rows = {r['party_code']: r for r in supplier_vs_ap(D(2026, 3, 31))}
        self.assertEqual((rows['S1']['gl_balance'], rows['S1']['ap_balance'], rows['S1']['difference']),
                         (Z, _d(1000), _d(-1000)))
        self.assertNotIn('S2', rows)   # unlinked and empty: nothing to compare
