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
