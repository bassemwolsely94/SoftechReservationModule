"""
apps/tests/test_supplier_terms.py

P-42 (docs/product-review/06_SPEC_P-42_supplier_terms.md): supplier credit terms per supplier × item category (local /
imported; "non-discounted" dropped by the owner 2026-10-31, a supplier-wide «any» term covers the rest), each open
invoice split into category slices that add up to its open amount exactly, a payment calendar in weeks starting
Saturday, early-pay opportunities ranked by annualised return, paid-on-time with its link coverage, and the residue
list. Read-only toward SOFTECH.
"""
import datetime as dt
import json
from decimal import Decimal

from django.test import TestCase

from apps.tests.factories import make_admin, make_user

D = dt.date
AS_OF = D(2026, 10, 31)          # a Saturday


def _party(code='565', name='Pharma Overseas'):
    from apps.finance.models import ReconParty
    return ReconParty.objects.get_or_create(softech_personcode=code, defaults={'party_type': 'supplier', 'name': name})[0]


def _inv(party, no, day, value, pay='0'):
    from apps.finance.models import APInvoice
    return APInvoice.objects.create(party=party, branchcode='100', doccode='10', docnumber=str(no), docdate=day,
                                    doc_value=Decimal(value), doc_value_pay=Decimal(pay), party_type='supplier')


def _line(party, no, day, item_code, value):
    from apps.procurement.models import PurchaseLine
    from apps.catalog.models import Item
    item = Item.objects.filter(softech_id=item_code).first()
    return PurchaseLine.objects.create(branch_code='100', supplier_code=party.softech_personcode, doc_number=str(no),
                                       doc_date=day, item_code=item_code, item=item, doccode='10',
                                       net_value=Decimal(value), raw_value=Decimal(value))


def _term(party, category, days, **kw):
    from apps.finance.models import SupplierTerm
    return SupplierTerm.objects.create(party=party, category=category, credit_days=days,
                                       effective_from=kw.pop('effective_from', D(2020, 1, 1)), **kw)


class Base(TestCase):

    def setUp(self):
        from apps.catalog.models import Item
        Item.objects.create(softech_id='LOC', name='local', is_imported=False)
        Item.objects.create(softech_id='LOC2', name='local 2', is_imported=False)
        Item.objects.create(softech_id='IMP', name='imported', is_imported=True)
        self.p = _party()
        # invoice 1: 300 local + 700 imported lines, 1000 open
        self.i1 = _inv(self.p, 1, D(2026, 10, 1), '1000')
        _line(self.p, 1, D(2026, 10, 1), 'LOC', '300')
        _line(self.p, 1, D(2026, 10, 1), 'IMP', '700')


class SliceTests(Base):

    def test_slices_add_up_exactly_even_with_rounding(self):
        from apps.finance.models import APInvoiceSlice
        from apps.finance.supplier_terms import recompute
        i2 = _inv(self.p, 2, D(2026, 10, 2), '100.00')
        for code, v in (('LOC', '1'), ('IMP', '1'), ('LOC2', '1')):          # thirds of 100 → 33.33 / 66.67
            _line(self.p, 2, D(2026, 10, 2), code, v)
        recompute()
        for inv in (self.i1, i2):
            total = sum(s.open_amount for s in APInvoiceSlice.objects.filter(invoice=inv))
            self.assertEqual(total, inv.doc_value)
        got = dict(APInvoiceSlice.objects.filter(invoice=i2).values_list('category', 'open_amount'))
        self.assertEqual(got, {'local': Decimal('66.67'), 'imported': Decimal('33.33')})

    def test_due_dates_by_category_and_the_any_default(self):
        from apps.finance.models import APInvoiceSlice
        from apps.finance.supplier_terms import recompute
        _term(self.p, 'imported', 60)
        _term(self.p, 'any', 30)
        recompute()
        due = dict(APInvoiceSlice.objects.filter(invoice=self.i1).values_list('category', 'due_date'))
        self.assertEqual(due, {'imported': D(2026, 11, 30), 'local': D(2026, 10, 31)})

    def test_effective_dating_and_month_end_basis(self):
        from apps.finance.models import APInvoiceSlice
        from apps.finance.supplier_terms import recompute
        _term(self.p, 'any', 30, effective_from=D(2020, 1, 1), effective_to=D(2026, 9, 30))
        _term(self.p, 'any', 45, effective_from=D(2026, 10, 1), days_from='month_end')
        old = _inv(self.p, 3, D(2026, 9, 15), '50')
        recompute()
        self.assertEqual(APInvoiceSlice.objects.get(invoice=old).due_date, D(2026, 10, 15))      # old 30 days
        self.assertEqual(APInvoiceSlice.objects.get(invoice=self.i1, category='local').due_date,
                         D(2026, 12, 15))                                                     # Oct end + 45

    def test_no_term_no_due_date_and_no_lines_unclassified(self):
        from apps.finance.models import APInvoiceSlice
        from apps.finance.supplier_terms import recompute
        bare = _inv(self.p, 4, D(2026, 10, 3), '80')
        recompute()
        self.assertTrue(all(s.due_date is None for s in APInvoiceSlice.objects.all()))
        self.assertEqual(list(APInvoiceSlice.objects.filter(invoice=bare).values_list('category', flat=True)),
                         ['unclassified'])

    def test_recompute_is_idempotent_and_drops_paid_invoices(self):
        from apps.finance.models import APInvoiceSlice
        from apps.finance.supplier_terms import recompute
        recompute()
        recompute()
        self.assertEqual(APInvoiceSlice.objects.count(), 2)
        self.i1.doc_value_pay = self.i1.doc_value
        self.i1.save()
        recompute()
        self.assertFalse(APInvoiceSlice.objects.exists())


class CalendarTests(Base):

    def test_weeks_start_saturday_overdue_no_terms_and_internal_apart(self):
        from apps.finance.supplier_terms import calendar, recompute
        _term(self.p, 'any', 20)                       # due 2026-10-21 → overdue on 31 Oct
        _term(self.p, 'imported', 35)                  # due 2026-11-05 → week of Sat 31 Oct
        internal = _party('1268', 'كوبونات')
        _inv(internal, 9, D(2026, 10, 10), '5000')
        nt = _party('30', 'Ramco')
        _inv(nt, 8, D(2026, 10, 10), '40')
        recompute()
        c = calendar(as_of=AS_OF, weeks=4)
        self.assertEqual(c['weeks'][0]['start'], D(2026, 10, 31))
        self.assertEqual(c['weeks'][0]['due'], Decimal('700'))
        self.assertEqual(c['overdue'], Decimal('300'))
        self.assertEqual(c['no_terms'], Decimal('40'))
        self.assertEqual(c['internal'], Decimal('5000'))
        self.assertNotIn('1268', {r['personcode'] for r in c['rows']})


class EarlyPayTests(Base):

    def test_hand_computed_return_and_foregone(self):
        from apps.finance.supplier_terms import early_pay, recompute
        _term(self.p, 'any', 60, early_pay_days=40, early_pay_discount_pct=Decimal('2'))
        recompute()
        # deadline 1 Oct + 40 = 10 Nov; due 30 Nov; 20 days gained; return = 2/98 × 365/20 = 37.24 %
        e = early_pay(as_of=AS_OF)
        row = e['open'][0]
        self.assertEqual(row['deadline'], D(2026, 11, 10))
        self.assertEqual(row['discount_value'], Decimal('20.00'))          # 2 % of the 1000 open (both slices)
        self.assertEqual(row['annualised_return_pct'], Decimal('37.24'))
        e = early_pay(as_of=D(2026, 11, 15))
        self.assertEqual((e['open'], e['foregone_value']), ([], Decimal('20.00')))


class P40InterfaceTests(Base):

    def test_outflows_and_early_pay_land_in_their_weeks(self):
        from apps.finance.supplier_terms import early_pay_by_week, recompute, supplier_outflows
        _term(self.p, 'any', 45, early_pay_days=10, early_pay_discount_pct=Decimal('1'))   # due 15 Nov · deadline 11 Oct
        _term(self.p, 'imported', 50, early_pay_days=38, early_pay_discount_pct=Decimal('1.5'))  # due 20 Nov · 8 Nov
        _inv(_party('4471', 'بدل'), 7, D(2026, 10, 1), '90')
        recompute()
        o = supplier_outflows(AS_OF, weeks=4)
        self.assertEqual([w['due_real'] for w in o['weeks']], [0, 0, Decimal('1000'), 0])     # week of Sat 14 Nov
        self.assertEqual(o['weeks'][2]['by_supplier'], {'565': Decimal('1000')})
        self.assertEqual((o['internal'], o['internal_by_supplier']), (Decimal('90'), {'4471': Decimal('90')}))
        e = early_pay_by_week(AS_OF, weeks=4)
        self.assertEqual(e['weeks'][1]['available_value'], Decimal('10.50'))   # 1.5 % of 700, deadline Sun 8 Nov
        self.assertEqual(e['weeks'][1]['pay_amount'], Decimal('700'))
        self.assertEqual(e['foregone_value'], Decimal('3.00'))                 # 1 % of local 300, deadline passed


class OnTimeTests(Base):

    def test_days_vs_terms_with_coverage(self):
        from apps.finance.models import Allocation, Payment
        from apps.finance.supplier_terms import on_time
        _term(self.p, 'any', 30)
        self.i1.doc_value_pay = Decimal('1000')
        self.i1.save()
        pay = Payment.objects.create(party=self.p, branchcode='100', cheqsno=1, cheqtype='20', direction='out',
                                     party_type='supplier', voucher_date=D(2026, 11, 5), amount=Decimal('1000'))
        Allocation.objects.create(payment=pay, invoice=self.i1, amount=Decimal('1000'), origin='softech')
        Payment.objects.create(party=self.p, branchcode='100', cheqsno=2, cheqtype='20', direction='out',
                               party_type='supplier', voucher_date=D(2026, 11, 6), amount=Decimal('1000'))   # unlinked
        r = {x['personcode']: x for x in on_time(as_of=D(2026, 11, 30))}['565']
        self.assertEqual(r['days_vs_terms'], Decimal('5.0'))       # paid 5 Nov, due 31 Oct
        self.assertEqual(r['coverage_pct'], Decimal('50.0'))       # 1000 of 2000 paid is linked


    def test_reversed_payment_counts_neither_side_of_coverage(self):
        from apps.finance.models import Allocation, Payment
        from apps.finance.supplier_terms import on_time
        _term(self.p, 'any', 30)
        good = Payment.objects.create(party=self.p, branchcode='100', cheqsno=1, cheqtype='20', direction='out',
                                      party_type='supplier', voucher_date=D(2026, 11, 5), amount=Decimal('1000'))
        bad = Payment.objects.create(party=self.p, branchcode='100', cheqsno=2, cheqtype='20', direction='out',
                                     party_type='supplier', voucher_date=D(2026, 11, 4), amount=Decimal('1000'),
                                     chain_role='reversed')
        Allocation.objects.create(payment=good, invoice=self.i1, amount=Decimal('1000'), origin='softech')
        i2 = _inv(self.p, 2, D(2026, 10, 2), '1000')
        Allocation.objects.create(payment=bad, invoice=i2, amount=Decimal('1000'), origin='softech')
        r = {x['personcode']: x for x in on_time(as_of=D(2026, 11, 30))}['565']
        self.assertEqual((r['paid_value'], r['linked_value'], r['coverage_pct']),
                         (Decimal('1000'), Decimal('1000'), Decimal('100.0')))


class ResidueTests(Base):

    def test_over_a_year_split_real_and_internal(self):
        from apps.finance.supplier_terms import residue
        _inv(self.p, 20, D(2025, 6, 1), '900')
        _inv(_party('3068', 'مورد عام'), 21, D(2024, 1, 1), '400')
        r = residue(as_of=AS_OF)
        self.assertEqual((r['real'], r['internal']), (Decimal('900'), Decimal('400')))


class ApiTests(Base):

    URL = '/api/finance/supplier-terms/'

    def setUp(self):
        super().setUp()
        from apps.tests.security.fixtures import seed_code_matrix
        from core.middleware import module_access
        seed_code_matrix()
        module_access.clear_cache()
        self.addCleanup(module_access.clear_cache)
        _, self.staff, self.admin = make_admin('st_admin')

    def test_terms_create_update_audit_and_views(self):
        from apps.finance.models import ReconAuditEvent, SupplierTerm
        r = self.admin.post(self.URL, {'personcode': '565', 'category': 'imported', 'credit_days': 60,
                                       'effective_from': '2026-01-01'}, format='json')
        self.assertEqual(r.status_code, 201)
        t = SupplierTerm.objects.get()
        r = self.admin.patch(self.URL, {'id': t.pk, 'credit_days': 75}, format='json')
        self.assertEqual(r.status_code, 200)
        t.refresh_from_db()
        self.assertEqual((t.credit_days, t.entered_by_id), (75, self.staff.pk))
        self.assertEqual(ReconAuditEvent.objects.filter(action='supplier_terms_changed').count(), 2)
        self.assertEqual(self.admin.post(self.URL, {'personcode': '565', 'category': 'bogus', 'credit_days': 1,
                                                    'effective_from': '2026-01-01'}, format='json').status_code, 400)
        for path in ('', 'calendar/', 'on-time/', 'early-pay/', 'residue/', 'export/?sheet=terms',
                     'export/?sheet=early_pay', 'export/?sheet=on_time', 'export/?sheet=residue'):
            self.assertEqual(self.admin.get(self.URL + path).status_code, 200, path)
        r = self.admin.get(self.URL + 'on-time/')
        self.assertIn('coverage_pct', json.dumps(r.data))
        r = self.admin.get(self.URL + 'export/?sheet=calendar')
        self.assertIn('spreadsheetml', r['Content-Type'])

    def test_branch_user_and_non_finance_refused(self):
        from apps.tests.factories import make_branch
        _, _, ph = make_user('st_ph', role='pharmacist', branch=make_branch('B', '130'))
        _, _, sales = make_user('st_sales', role='salesperson')
        for c in (ph, sales):
            self.assertEqual(c.get(self.URL + 'calendar/').status_code, 403)
            self.assertEqual(c.post(self.URL, {'personcode': '565', 'category': 'any', 'credit_days': 1,
                                               'effective_from': '2026-01-01'}, format='json').status_code, 403)
