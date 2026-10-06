"""
Owner 2026-10-05: never a bare branch code — "code · name" in exports and notices
(apps/finance/recon_labels.branch_label); a loading bar while a sync / engine run is in
progress (supply freshness `progress`).
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.finance import recon_labels


class BranchLabelTests(TestCase):
    def setUp(self):
        from apps.branches.models import Branch
        Branch.objects.create(softech_branch_id='170', name='ElGeish Sq, Abbasia', name_ar='م. الجيش-العباسية')
        recon_labels._cache['at'] = 0            # the label map is cached for 10 minutes

    def test_label(self):
        self.assertEqual(recon_labels.branch_label('170'), '170 · م. الجيش-العباسية')
        self.assertEqual(recon_labels.branch_label('999'), '999')          # unknown code stays as is

    def test_server_down_notice_names_the_branch(self):
        from apps.purchasing import isr_fulfillment as F
        note = F.fallback_notes({'170': '2026-10-05 09:00'})[0]
        self.assertIn('سيرفر فرع 170 · م. الجيش-العباسية', note)
        self.assertNotIn('خادم', note)


class SyncProgressTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from .factories import make_user
        cls.user, _, _ = make_user('op_progress', role='purchasing')

    def test_running_sync_reports_steps(self):
        from apps.sync.models import SyncRun
        run = SyncRun.objects.create(status='running', progress={
            'phase': 'stock', 'message': 'سحب أرصدة الفروع (stkbal)…', 'step': 2, 'steps': 4})
        SyncRun.objects.filter(pk=run.pk).update(started_at=timezone.now() - timedelta(seconds=40))
        c = APIClient()
        c.force_authenticate(self.user)
        d = c.get('/api/supply/freshness/').json()
        self.assertTrue(d['sync_running'])
        p = d['progress'][0]
        self.assertEqual((p['kind'], p['pct']), ('sync', 50))
        self.assertIn('stkbal', p['message'])
        self.assertGreaterEqual(p['elapsed_s'], 39)

    def test_idle_has_no_progress(self):
        c = APIClient()
        c.force_authenticate(self.user)
        self.assertEqual(c.get('/api/supply/freshness/').json()['progress'], [])
