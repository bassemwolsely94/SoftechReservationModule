"""Refill tasks auto-close when the same PIC buys the same item AFTER the sale that created the
task — read from the synced PurchaseHistory. They used to read the ERPTransaction mirror that
stopped on 2026-04-30, so no task had auto-closed since (2026-11-01)."""
import datetime as dt
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.customers.models import Customer, PurchaseHistory, PurchaseHistoryLine
from apps.followups.models import FollowUpTask
from apps.followups.services import auto_close_followup_tasks_from_erp, auto_close_with_substitute_detection
from apps.tests.factories import make_branch, make_item

PIC = '130HD14864'


class AutoCloseTests(TestCase):

    def setUp(self):
        self.branch = make_branch('فرع ١٣٠', '130')
        self.item = make_item('CONCOR 5MG', 'IT501')
        self.cust = Customer.objects.create(name='صيدلية دكتور باسم', softech_pic=PIC)
        self.today = timezone.localdate()
        self.task = self._task(phcode=PIC, source=self.today - dt.timedelta(days=30))

    def _task(self, phcode='', notes='', source=None, item=None):
        return FollowUpTask.objects.create(
            phcode=phcode, notes=notes, item=item or self.item, branch=self.branch, task_type='refill',
            status='pending', due_date=self.today, source_sale_date=source)

    def _sale(self, n, days_ago, item=None, pic=PIC):
        when = timezone.make_aware(dt.datetime.combine(self.today - dt.timedelta(days=days_ago), dt.time(12)))
        ph = PurchaseHistory.objects.create(
            customer=self.cust, branch=self.branch, doc_code='115', docnumber=str(n), invoice_date=when,
            softech_phcode=pic, softech_invoice_id=f'130-115-{n}-{when:%Y%m%d}')
        PurchaseHistoryLine.objects.create(purchase=ph, item=item or self.item, quantity=1,
                                           unit_price=Decimal('10'), line_total=Decimal('10'))
        return ph

    def test_a_later_purchase_closes_the_task_with_the_invoice(self):
        sale = self._sale(1, days_ago=2)
        self.assertEqual(auto_close_followup_tasks_from_erp(since_minutes=60 * 24 * 7), 1)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'auto_closed')
        self.assertEqual(self.task.closing_erp_transaction, sale.softech_invoice_id)
        self.assertIn('CONCOR 5MG', self.task.result_note)

    def test_the_triggering_sale_or_another_pic_does_not_close_it(self):
        self._sale(1, days_ago=30)                      # the sale the task came from
        self._sale(2, days_ago=1, pic='130HD99999')     # someone else
        self.assertEqual(auto_close_followup_tasks_from_erp(since_minutes=60 * 24 * 60), 0)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'pending')

    def test_a_mirror_era_task_does_not_close_on_its_own_sale(self):
        # ERPTransaction tasks carry the UTC date — one day BEFORE the synced invoice's date
        own = self._sale(7, days_ago=29)
        FollowUpTask.objects.filter(pk=self.task.pk).update(source_erp_transaction='7', source_softech_branch_code='130')
        self.assertEqual(auto_close_followup_tasks_from_erp(since_minutes=60 * 24 * 60, dry_run=True), 0)
        self.assertEqual(auto_close_with_substitute_detection(since_minutes=60 * 24 * 60)['exact_closed'], 0)
        self._sale(8, days_ago=1)                       # a real repurchase still closes it
        self.assertEqual(auto_close_followup_tasks_from_erp(since_minutes=60 * 24 * 60), 1)
        self.task.refresh_from_db()
        self.assertNotEqual(self.task.closing_erp_transaction, own.softech_invoice_id)

    def test_dry_run_counts_without_saving(self):
        self._sale(1, days_ago=2)
        self.assertEqual(auto_close_followup_tasks_from_erp(since_minutes=60 * 24 * 7, dry_run=True), 1)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'pending')

    def test_the_lookback_window_limits_the_sales_read(self):
        self._sale(1, days_ago=10)
        self.assertEqual(auto_close_followup_tasks_from_erp(since_minutes=12), 0)
        self.assertEqual(auto_close_followup_tasks_from_erp(since_minutes=60 * 24 * 14), 1)

    def test_pic_in_notes_is_used_when_the_field_is_empty(self):
        FollowUpTask.objects.filter(pk=self.task.pk).update(phcode='', notes=f'phcode:{PIC} آخر صرف')
        self._sale(1, days_ago=2)
        self.assertEqual(auto_close_followup_tasks_from_erp(since_minutes=60 * 24 * 7), 1)

    def test_a_substitute_with_the_same_effect_code_closes_it(self):
        from apps.catalog.models import Item
        alt = make_item('BISOCARD 5MG', 'IT502')
        Item.objects.filter(pk__in=[self.item.pk, alt.pk]).update(effect_code='BB01')
        self._sale(1, days_ago=2, item=alt)
        r = auto_close_with_substitute_detection(since_minutes=60 * 24 * 7)
        self.assertEqual(r, {'exact_closed': 0, 'substitute_closed': 1})
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'auto_closed')


class GeneratorTests(TestCase):
    """The bulk refill generator reads the synced PurchaseHistory (the ERPTransaction mirror
    stopped 2026-04-30 — no task was generated after 2026-06-01)."""

    def setUp(self):
        from apps.followups.models import ChronicMedicationProfile
        self.branch = make_branch('فرع ١٣٠', '130')
        self.item = make_item('CONCOR 5MG', 'IT501')
        self.cust = Customer.objects.create(name='صيدلية دكتور باسم', softech_pic=PIC)
        self.today = timezone.localdate()
        ChronicMedicationProfile.objects.create(item=self.item, is_chronic=True,
                                                expected_duration_days=30, followup_before_days=5)

    def _sale(self, n, days_ago, pic=PIC):
        when = timezone.make_aware(dt.datetime.combine(self.today - dt.timedelta(days=days_ago), dt.time(23, 30)))
        ph = PurchaseHistory.objects.create(
            customer=self.cust, branch=self.branch, doc_code='115', docnumber=str(n), invoice_date=when,
            total_amount=Decimal('99'), softech_phcode=pic, softech_invoice_id=f'130-115-{n}-{when:%Y%m%d}')
        PurchaseHistoryLine.objects.create(purchase=ph, item=self.item, quantity=1,
                                           unit_price=Decimal('99'), line_total=Decimal('99'))

    def test_a_due_refill_creates_one_task_from_the_latest_sale(self):
        from apps.followups.services import generate_followup_tasks_bulk
        self._sale(1, days_ago=60)
        self._sale(2, days_ago=27)                      # latest — trigger day 25 passed, refill on day 30
        self.assertEqual(generate_followup_tasks_bulk(dry_run=True), 1)
        self.assertFalse(FollowUpTask.objects.exists())
        self.assertEqual(generate_followup_tasks_bulk(), 1)
        t = FollowUpTask.objects.get()
        self.assertEqual((t.phcode, t.customer, t.source_erp_transaction, t.source_softech_branch_code),
                         (PIC, self.cust, '2', '130'))
        self.assertEqual(t.source_sale_date, self.today - dt.timedelta(days=27))   # Cairo date, 23:30 sale
        self.assertEqual(t.due_date, self.today + dt.timedelta(days=3))
        self.assertEqual(generate_followup_tasks_bulk(), 0)                       # open task → no duplicate

    def test_a_sale_that_already_had_a_task_never_gets_another(self):
        from apps.followups.services import generate_followup_tasks_bulk
        self._sale(2, days_ago=27)
        self.assertEqual(generate_followup_tasks_bulk(), 1)
        FollowUpTask.objects.update(status='done')
        self.assertEqual(generate_followup_tasks_bulk(), 0)

    def test_too_early_or_too_late_creates_nothing(self):
        from apps.followups.services import generate_followup_tasks_bulk
        self._sale(1, days_ago=10)                      # trigger day 25 not reached
        self._sale(2, days_ago=60, pic='130HD22222')    # refill + 14 days grace long passed
        self.assertEqual(generate_followup_tasks_bulk(dry_run=True), 0)


class ChronicInferenceTests(TestCase):
    """A medicine is chronic when enough patients rebuy it on a steady 20–100 day cycle."""

    def setUp(self):
        from apps.catalog.models import Item
        from apps.followups.models import ChronicMedicationProfile
        self.branch = make_branch('فرع ١٣٠', '130')
        self.today = timezone.localdate()
        self.concor = make_item('CONCOR 5MG', 'IT501')
        self.augmentin = make_item('AUGMENTIN 1G', 'IT502')
        self.coupon = make_item('COUPON SERVED TO CUSTOMER', 'IT503')
        Item.objects.filter(pk__in=[self.concor.pk, self.augmentin.pk]).update(medicine_type='10')
        Item.objects.filter(pk=self.coupon.pk).update(medicine_type='60')
        self.n = 0
        # 6 patients rebuy CONCOR every ~30 days; AUGMENTIN is bought once or twice, irregularly
        for p in range(6):
            pic = f'130HD{p}'
            for k in range(4):
                self._buy(pic, self.concor, 30 * k + p)
                self._buy(pic, self.coupon, 30 * k + p)          # steady, but not a medicine
            self._buy(pic, self.augmentin, 5 + p)
            if p % 2:
                self._buy(pic, self.augmentin, 150 + p)
        self.old_junk = ChronicMedicationProfile.objects.create(item=self.coupon, is_chronic=True,
                                                                expected_duration_days=30, source='erp_infer')
        # save() derives the duration from pack ÷ usage — a 7-unit pack at 1/day = 7 days
        self.manual = ChronicMedicationProfile.objects.create(item=self.augmentin, is_chronic=True,
                                                              pack_size=7, source='manual')

    def _buy(self, pic, item, days_ago):
        self.n += 1
        when = timezone.make_aware(dt.datetime.combine(self.today - dt.timedelta(days=days_ago), dt.time(12)))
        ph = PurchaseHistory.objects.create(
            customer=Customer.objects.get_or_create(softech_pic=pic, defaults={'name': pic})[0], branch=self.branch,
            doc_code='115', docnumber=str(self.n), invoice_date=when, softech_phcode=pic,
            softech_invoice_id=f'130-115-{self.n}-{when:%Y%m%d}')
        PurchaseHistoryLine.objects.create(purchase=ph, item=item, quantity=1, unit_price=Decimal('1'),
                                           line_total=Decimal('1'))

    def test_dry_run_reports_without_saving(self):
        from apps.followups.models import ChronicMedicationProfile
        from apps.followups.services import infer_chronic_profiles_from_sales
        r = infer_chronic_profiles_from_sales(dry_run=True)
        self.assertEqual((r['chronic'], r['created'], r['switched_off']), (1, 1, 1))
        self.assertEqual(r['items'][0][:3], ('CONCOR 5MG', 30, 6))
        self.assertEqual(r['items'][0][4], 100.0)                  # 6 of its 6 buyers rebuy steadily
        self.assertFalse(ChronicMedicationProfile.objects.filter(item=self.concor).exists())
        self.old_junk.refresh_from_db()
        self.assertTrue(self.old_junk.is_chronic)

    def test_apply_creates_steady_medicines_switches_off_junk_keeps_manual(self):
        from apps.followups.models import ChronicMedicationProfile
        from apps.followups.services import infer_chronic_profiles_from_sales
        infer_chronic_profiles_from_sales()
        p = ChronicMedicationProfile.objects.get(item=self.concor)
        self.assertEqual((p.is_chronic, p.expected_duration_days, p.followup_before_days, p.source),
                         (True, 30, 4, 'sales_infer'))
        self.old_junk.refresh_from_db()
        self.manual.refresh_from_db()
        self.assertFalse(self.old_junk.is_chronic)                 # coupon: not a medicine
        self.assertEqual((self.manual.is_chronic, self.manual.expected_duration_days), (True, 7))

    def test_a_non_round_cycle_survives_the_model_save(self):
        from apps.followups.models import ChronicMedicationProfile
        from apps.followups.services import infer_chronic_profiles_from_sales
        PurchaseHistory.objects.all().delete()
        for p in range(6):                               # 6 patients on a steady 37-day cycle
            for k in range(4):
                self._buy(f'130HD{p}', self.concor, 37 * k + p)
        infer_chronic_profiles_from_sales()
        self.assertEqual(ChronicMedicationProfile.objects.get(item=self.concor).expected_duration_days, 37)


class EscalationTests(TestCase):
    """Overdue tasks become 'missed' only once they have existed for the grace period too."""

    def setUp(self):
        self.branch = make_branch('فرع ١٣٠', '130')
        self.item = make_item('CONCOR 5MG', 'IT501')
        self.today = timezone.localdate()

    def _task(self, due_days_ago, created_days_ago):
        t = FollowUpTask.objects.create(phcode=PIC, item=self.item, branch=self.branch, task_type='refill',
                                        status='pending', due_date=self.today - dt.timedelta(days=due_days_ago))
        FollowUpTask.objects.filter(pk=t.pk).update(created_at=timezone.now() - dt.timedelta(days=created_days_ago))
        return t

    def test_a_catch_up_task_gets_its_grace_before_missed(self):
        from apps.followups.services import escalate_overdue_tasks
        fresh = self._task(due_days_ago=10, created_days_ago=0)      # created already overdue
        old = self._task(due_days_ago=10, created_days_ago=10)
        self.assertEqual(escalate_overdue_tasks(overdue_days=3)['escalated'], 1)
        fresh.refresh_from_db(); old.refresh_from_db()
        self.assertEqual((fresh.status, old.status), ('pending', 'missed'))
