"""
apps/tests/test_insights.py  (doc 18)

Exercises the narrative engine end-to-end on synthetic data: a rule fires,
findings persist, and the bilingual narrative renders.
"""
from datetime import datetime, date
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.branches.models import Branch
from apps.catalog.models import Item, Category
from apps.customers.models import Customer, PurchaseHistory, PurchaseHistoryLine
from apps.forecasting.models import ChannelBucketMap
from apps.insights.engine import InsightEngine


class InsightsEngineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.b = Branch.objects.create(softech_branch_id='970', code='970', name='Ins Test',
                                      name_ar='فرع الاختبار', is_operational=True)
        cls.cust = Customer.objects.create(name='c', softech_pic='PICI', softech_id='C-I')
        cls.med = Item.objects.create(softech_id='INM', name='دواء', medicine_type='10')
        ChannelBucketMap.objects.create(person_type='10', channel='91', label='cash',
                                        bucket='cash', counts_customer=True, include_in_profit=True, active=True)

        def inv(ref, when, total, user):
            ph = PurchaseHistory.objects.create(customer=cls.cust, softech_invoice_id=ref, branch=cls.b,
                 doc_code='115', total_amount=Decimal(total), invoice_date=when, sales_channel='91',
                 sales_person_type='10', softech_user=user, softech_phcode='PIC-' + ref)
            PurchaseHistoryLine.objects.create(purchase=ph, item=cls.med, quantity=Decimal(1),
                 unit_price=Decimal(total), line_total=Decimal(total), cost_at_sale=Decimal(10), list_price=Decimal(total))
            return ph

        # target day 2026-06-10 (Wed). Daily branch_vs_prev now triggers on the
        # SAME-WEEKDAY-LAST-WEEK comparison → seed 2026-06-03 (Wed) high, target day low.
        inv('LW', timezone.make_aware(datetime(2026, 6, 3, 12)), 100000, '500')   # same weekday last week (baseline)
        inv('P1', timezone.make_aware(datetime(2026, 6, 9, 12)), 100000, '500')   # previous day (shown for context)
        inv('P2', timezone.make_aware(datetime(2026, 6, 10, 12)), 1000, '500')    # big drop
        # a bulk sale on target day
        inv('BULK', timezone.make_aware(datetime(2026, 6, 10, 13)), 30000, '501')

    def test_generate_day_report_bilingual(self):
        run = InsightEngine.run(period_type='day', ref_date=date(2026, 6, 10))
        self.assertEqual(run.period_type, 'day')
        self.assertGreater(run.findings_count, 0)
        # bilingual narratives rendered
        self.assertIn('التقرير السردي', run.narrative_ar)
        self.assertIn('board report', run.narrative_en)
        # branch drop rule fired
        codes = set(run.findings.values_list('rule_code', flat=True))
        self.assertIn('branch_vs_prev', codes)
        # bulk sale detected (30000 ≥ default 20000)
        self.assertIn('bulk_sale', codes)

    def test_no_findings_reads_clean(self):
        # a quiet period (no data) → no findings, clean message
        run = InsightEngine.run(period_type='day', ref_date=date(2020, 1, 1))
        self.assertEqual(run.findings_count, 0)
        self.assertIn('لا توجد ملاحظات', run.narrative_ar)
