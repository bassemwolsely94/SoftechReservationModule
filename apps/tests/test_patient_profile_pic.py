"""The patient profile + quick follow-up find a customer's SOFTECH records by their PIC
(Customer.softech_pic) and read sales from the synced PurchaseHistory. They used to compare
phcodes with Customer.softech_id (the per-branch serial — never equal) and read the
ERPTransaction mirror that stopped on 2026-04-30, so these sections were empty (2026-11-01)."""
import datetime as dt
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.customers.models import Customer, PurchaseHistory, PurchaseHistoryLine
from apps.tests.factories import make_branch, make_item


class PatientProfilePicTests(TestCase):

    def setUp(self):
        self.branch = make_branch('فرع ١٣٠', '130')
        self.item = make_item('CONCOR 5MG', 'IT501')
        # serial 14864 — the old lookup compared phcodes with this and never matched
        self.cust = Customer.objects.create(name='صيدلية دكتور باسم', softech_pic='130HD14864', softech_id='14864')
        walk_in = Customer.objects.create(name='Walk-In Customer', softech_pic='ACCT-1510', is_account_placeholder=True)
        self.sale_days_ago = 26
        when = timezone.now() - dt.timedelta(days=self.sale_days_ago)
        # a sale linked to the customer, and one still on the account placeholder but carrying their PIC
        for n, owner in ((1, self.cust), (2, walk_in)):
            ph = PurchaseHistory.objects.create(
                customer=owner, branch=self.branch, doc_code='115', docnumber=str(n), invoice_date=when,
                total_amount=Decimal('120'), softech_phcode='130HD14864', softech_personcode='1510',
                softech_invoice_id=f'130-115-{n}-{when:%Y%m%d}')
            PurchaseHistoryLine.objects.create(purchase=ph, item=self.item, quantity=1,
                                               unit_price=Decimal('120'), line_total=Decimal('120'))

    def test_timeline_shows_sales_by_pic(self):
        from apps.customers.patient_profile import build_timeline
        sales = [e for e in build_timeline(self.cust) if e['type'] == 'erp_sale']
        self.assertEqual(len(sales), 2)
        self.assertEqual(sales[0]['detail'], 'CONCOR 5MG')

    def test_profile_sales_and_identity_use_the_pic(self):
        from apps.customers.patient_profile import _erp_identity_section, _erp_sales
        from apps.erp.models import LocalCustomer
        self.assertEqual(len(_erp_sales(self.cust)), 2)
        LocalCustomer.objects.create(phcode='130HD14864', name='صيدلية دكتور باسم', phone='01000000000')
        ident = _erp_identity_section(self.cust)
        self.assertEqual((ident['found'], ident['phcode']), (True, '130HD14864'))

    def test_quick_followup_finds_the_last_sale_by_pic(self):
        from apps.followups.models import ChronicMedicationProfile, FollowUpTask
        from apps.followups.services import generate_followup_tasks_for_customer
        ChronicMedicationProfile.objects.create(item=self.item, is_chronic=True,
                                                expected_duration_days=30, followup_before_days=5)
        dry = generate_followup_tasks_for_customer(self.cust, dry_run=True)
        self.assertEqual([d['item'] for d in dry], ['CONCOR 5MG'])
        created = generate_followup_tasks_for_customer(self.cust, branch=self.branch)
        self.assertEqual(len(created), 1)
        task = FollowUpTask.objects.get()
        self.assertTrue(task.notes.startswith('phcode:130HD14864'))
        self.assertEqual(task.source_sale_date, timezone.localdate() - dt.timedelta(days=self.sale_days_ago))
