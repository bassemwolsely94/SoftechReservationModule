"""Piece 4 — readers that turn an invoice channel code into a KPI bucket must read customer
channels only (person type '10'). SOFTECH reuses the same numbers for other person types
(job titles, doctors, suppliers …), and on the office data a later row used to overwrite the
customer row: contract '10' read as 'exclude'."""
import datetime as _dt

from django.test import TestCase

from apps.forecasting import channels
from apps.forecasting.models import ChannelBucketMap


class ChannelReadersIgnoreOtherPersonTypesTests(TestCase):
    def setUp(self):
        channels.invalidate_cache()
        # created in Meta order (person_type, channel), the order the old readers iterated
        ChannelBucketMap.objects.create(person_type='10', channel='10', label='تعاقدات / آجل', bucket='credit')
        ChannelBucketMap.objects.create(person_type='10', channel='30', label='عميل دائم', bucket='cash',
                                        subtype='regular')
        ChannelBucketMap.objects.create(person_type='30', channel='10', label='عامل', bucket='exclude')
        ChannelBucketMap.objects.create(person_type='40', channel='30', label='الاستاذ', bucket='exclude')
        ChannelBucketMap.objects.create(person_type='80', channel='10', label='شركات شقيقة', bucket='exclude')

    def tearDown(self):
        channels.invalidate_cache()

    def test_pic_analytics_map_uses_customer_rows(self):
        from apps.pic_analytics.build import channel_bucket_map
        m = channel_bucket_map()
        self.assertEqual(m['10'], 'credit')
        self.assertEqual(m['30'], 'regular')

    def test_stock_audit_context_uses_customer_rows(self):
        from apps.stock_audit.engine import build_context
        today = _dt.date(2026, 11, 13)
        ctx = build_context(today - _dt.timedelta(days=30), today)
        self.assertEqual(ctx.channel_bucket, {'10': 'credit', '30': 'cash'})
