"""
apps/tests/test_segmentation_config.py

Configurable CRM segmentation (Commerce-OS Phase 2): thresholds are now a tunable
singleton read by segment_customers; the classification stays deterministic.
"""
from django.test import TestCase

from apps.customers.models import SegmentationConfig
from apps.customers.management.commands.segment_customers import _compute_segment
from .factories import make_user


class SegmentComputeTests(TestCase):
    def test_defaults_match_legacy(self):
        # ltv 6000, 10 days since visit → vip under default 5000 threshold
        self.assertEqual(_compute_segment(6000, 10, 1, 100), 'vip')

    def test_config_raises_vip_bar(self):
        cfg = SegmentationConfig.get_solo()
        cfg.vip_ltv_threshold = 10000
        cfg.save()
        # same 6000 LTV now below the raised bar → not vip
        self.assertNotEqual(_compute_segment(6000, 10, 1, 100, cfg=cfg), 'vip')

    def test_config_changes_loyal_bar(self):
        cfg = SegmentationConfig.get_solo()
        cfg.loyal_min_purchases = 2
        cfg.save()
        self.assertEqual(_compute_segment(100, 10, 2, 100, cfg=cfg), 'loyal')

    def test_never_purchased_new_vs_churned(self):
        cfg = SegmentationConfig.get_solo()
        self.assertEqual(_compute_segment(0, None, 0, 30, cfg=cfg), 'new')
        self.assertEqual(_compute_segment(0, None, 0, 400, cfg=cfg), 'churned')


class SegmentationConfigApiTests(TestCase):
    def test_get_returns_thresholds(self):
        _, _, client = make_user('seg_user', role='pharmacist')
        r = client.get('/api/customers/segmentation-config/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('vip_ltv_threshold', r.data)

    def test_non_admin_cannot_patch(self):
        _, _, client = make_user('seg_ph', role='pharmacist')
        r = client.patch('/api/customers/segmentation-config/', {'vip_ltv_threshold': 9999}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_admin_can_patch(self):
        _, _, admin = make_user('seg_admin', role='admin')
        r = admin.patch('/api/customers/segmentation-config/', {'vip_ltv_threshold': 8000}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(float(r.data['vip_ltv_threshold']), 8000.0)
        self.assertEqual(float(SegmentationConfig.get_solo().vip_ltv_threshold), 8000.0)
