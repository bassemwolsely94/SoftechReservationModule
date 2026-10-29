"""
WhatsApp campaign workflow (apps/campaigns): approve / reject / send need 'campaigns/approve'
and cancelling 'edit' or 'approve' (security Batch 4, Z-8b); a scheduled campaign stays out of
the WhatsApp send queue until its time; cancelling removes everything still pending. Before
2026-10-26 a scheduled campaign was queued for sending at once and cancel only changed the
status.
"""
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.campaigns.dispatcher import release_due_scheduled_campaigns
from apps.campaigns.models import CampaignMessage, WhatsAppCampaign
from apps.tests.factories import make_branch, make_customer, make_user
from apps.users.models import RoleModuleAccess
from apps.whatsapp.models import WAMessageQueue
from core.middleware import module_access

GRANTS = {
    'call_center': {'view', 'create', 'edit'},
    'supervisor':  {'view', 'create', 'edit', 'approve', 'export'},
}


@override_settings(WHATSAPP_TOKEN='test-token')
class CampaignWorkflowTests(TestCase):
    def setUp(self):
        module_access.clear_cache()
        for role, actions in GRANTS.items():
            for a in actions:
                RoleModuleAccess.objects.create(role=role, module='campaigns', action=a)
        self.branch = make_branch()
        self.cc = make_user('camp_cc', role='call_center', branch=self.branch, access_all=True)[2]
        self.sup = make_user('camp_sup', role='supervisor', branch=self.branch, access_all=True)[2]
        make_customer('عميل أول', '01011111111')
        make_customer('عميل ثان', '01022222222')

    def tearDown(self):
        module_access.clear_cache()

    def _campaign(self, status):
        return WhatsAppCampaign.objects.create(
            name='حملة', message_template='مرحبا {{customer_name}}', status=status,
        )

    def _url(self, c, action):
        return f'/api/campaigns/{c.pk}/{action}/'

    # ── permissions ──────────────────────────────────────────────────────────
    def test_role_without_approve_gets_403(self):
        c = self._campaign('pending_approval')
        self.assertEqual(self.cc.post(self._url(c, 'approve'), {}, format='json').status_code, 403)
        self.assertEqual(self.cc.post(self._url(c, 'reject'), {'reason': 'x'}, format='json').status_code, 403)
        c.refresh_from_db()
        self.assertEqual(c.status, 'pending_approval')

        c2 = self._campaign('approved')
        self.assertEqual(self.cc.post(self._url(c2, 'queue'), {}, format='json').status_code, 403)
        c2.refresh_from_db()
        self.assertEqual(c2.status, 'approved')
        self.assertFalse(c2.messages.exists())
        self.assertFalse(WAMessageQueue.objects.exists())

    def test_role_with_approve_succeeds(self):
        c = self._campaign('pending_approval')
        r = self.sup.post(self._url(c, 'approve'), {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.data['my_can_approve'])
        c.refresh_from_db()
        self.assertEqual(c.status, 'approved')

        r = self.sup.post(self._url(c, 'queue'), {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        c.refresh_from_db()
        self.assertEqual(c.status, 'running')
        self.assertEqual(c.queued_by.user.username, 'camp_sup')
        self.assertIsNotNone(c.queued_at)
        # immediate send → in the WhatsApp queue now
        self.assertEqual(WAMessageQueue.objects.filter(status='pending').count(), 2)

    def test_my_can_approve_flag_false_for_call_center(self):
        c = self._campaign('pending_approval')
        r = self.cc.get(f'/api/campaigns/{c.pk}/')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(r.data['my_can_approve'])

    def test_drafter_may_cancel_and_sees_it(self):
        # Batch 4 Z-8b: whoever edits campaigns may also cancel one (not only approvers)
        c = self._campaign('approved')
        r = self.cc.get(f'/api/campaigns/{c.pk}/')
        self.assertTrue(r.data['my_can_cancel'])
        r = self.cc.post(self._url(c, 'cancel'), {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        c.refresh_from_db()
        self.assertEqual(c.status, 'cancelled')
        self.assertEqual(c.cancelled_by.user.username, 'camp_cc')

    # ── scheduling ───────────────────────────────────────────────────────────
    def test_scheduled_campaign_not_in_wa_queue_before_its_time(self):
        c = self._campaign('approved')
        when = timezone.now() + timedelta(hours=3)
        r = self.sup.post(self._url(c, 'queue'), {'scheduled_at': when.isoformat()}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        c.refresh_from_db()
        self.assertEqual(c.status, 'scheduled')
        self.assertEqual(c.messages.filter(status='pending').count(), 2)
        self.assertFalse(WAMessageQueue.objects.exists())

        # the scheduler run before the time releases nothing
        self.assertEqual(release_due_scheduled_campaigns(now=timezone.now()), 0)
        self.assertFalse(WAMessageQueue.objects.exists())

        # once the time has passed it is released exactly once
        later = when + timedelta(minutes=1)
        self.assertEqual(release_due_scheduled_campaigns(now=later), 1)
        c.refresh_from_db()
        self.assertEqual(c.status, 'running')
        self.assertEqual(WAMessageQueue.objects.filter(status='pending').count(), 2)
        self.assertEqual(release_due_scheduled_campaigns(now=later), 0)

    # ── cancel ───────────────────────────────────────────────────────────────
    def test_cancel_leaves_nothing_pending(self):
        c = self._campaign('approved')
        when = timezone.now() - timedelta(minutes=1)
        self.sup.post(self._url(c, 'queue'), {'scheduled_at': when.isoformat()}, format='json')
        release_due_scheduled_campaigns()   # in the WhatsApp queue now
        self.assertEqual(WAMessageQueue.objects.filter(status='pending').count(), 2)
        # 'running' is not cancellable (can_cancel); 'paused' is, with sends still queued
        WhatsAppCampaign.objects.filter(pk=c.pk).update(status='paused')

        r = self.sup.post(self._url(c, 'cancel'), {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        c.refresh_from_db()
        self.assertEqual(c.status, 'cancelled')
        self.assertEqual(c.cancelled_by.user.username, 'camp_sup')
        self.assertFalse(WAMessageQueue.objects.filter(status='pending').exists())
        self.assertFalse(CampaignMessage.objects.filter(campaign=c, status='pending').exists())
        self.assertEqual(CampaignMessage.objects.filter(campaign=c, status='skipped').count(), 2)
        self.assertEqual(c.messages_queued, 0)

        # a later scheduler run sends nothing for it
        self.assertEqual(release_due_scheduled_campaigns(), 0)
        self.assertFalse(WAMessageQueue.objects.exists())

    def test_cancel_scheduled_before_release(self):
        c = self._campaign('approved')
        when = timezone.now() + timedelta(hours=1)
        self.sup.post(self._url(c, 'queue'), {'scheduled_at': when.isoformat()}, format='json')
        self.assertEqual(self.sup.post(self._url(c, 'cancel'), {}, format='json').status_code, 200)
        self.assertEqual(release_due_scheduled_campaigns(now=when + timedelta(minutes=5)), 0)
        self.assertFalse(WAMessageQueue.objects.exists())
        self.assertFalse(CampaignMessage.objects.filter(campaign=c, status='pending').exists())
