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
        from apps.customers import consent
        for c in (make_customer('عميل أول', '01011111111'), make_customer('عميل ثان', '01022222222')):
            consent.record(c, consent.MARKETING, True, source='counter')     # P-05: offers are opt-in

    def tearDown(self):
        module_access.clear_cache()

    def _campaign(self, status):
        return WhatsAppCampaign.objects.create(
            name='حملة', message_template='مرحبا {{customer_name}}', status=status,
            wa_template_name='summer_offer', wa_template_vars=['customer_name'],     # P-05 templates only
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


@override_settings(WHATSAPP_TOKEN='test-token')
class TemplatesOnlyTests(TestCase):
    """P-05: campaigns go out only with a Meta-approved template."""

    def setUp(self):
        module_access.clear_cache()
        for role, actions in GRANTS.items():
            for a in actions:
                RoleModuleAccess.objects.create(role=role, module='campaigns', action=a)
        self.branch = make_branch()
        self.cc = make_user('tpl_cc', role='call_center', branch=self.branch, access_all=True)[2]
        self.sup = make_user('tpl_sup', role='supervisor', branch=self.branch, access_all=True)[2]
        from apps.customers import consent
        self.cust = make_customer('منى', '01033333333')
        consent.record(self.cust, consent.MARKETING, True, source='counter')

    def tearDown(self):
        module_access.clear_cache()

    def test_no_template_blocks_approval_and_queue(self):
        c = WhatsAppCampaign.objects.create(name='x', message_template='مرحبا', status='draft')
        r = self.cc.post(f'/api/campaigns/{c.pk}/request-approval/', {}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('قالب واتساب معتمد', r.data['detail'])
        WhatsAppCampaign.objects.filter(pk=c.pk).update(status='approved')     # approved before the rule
        r = self.sup.post(f'/api/campaigns/{c.pk}/queue/', {}, format='json')
        self.assertEqual(r.status_code, 400)
        with override_settings(CAMPAIGN_TEMPLATES_ONLY=False):
            WhatsAppCampaign.objects.filter(pk=c.pk).update(status='draft')
            self.assertEqual(self.cc.post(f'/api/campaigns/{c.pk}/request-approval/', {}, format='json')
                             .status_code, 200)

    def test_template_rows_are_sent_with_send_template(self):
        from unittest import mock
        from apps.campaigns.dispatcher import drain_queue
        c = WhatsAppCampaign.objects.create(name='x', message_template='مرحبا {{customer_name}}', status='approved',
                                            wa_template_name='summer_offer', wa_template_vars=['customer_name', 'branch_name'])
        self.assertEqual(self.sup.post(f'/api/campaigns/{c.pk}/queue/', {}, format='json').status_code, 200)
        row = WAMessageQueue.objects.get()
        self.assertEqual((row.message_type, row.template_name), ('template', 'summer_offer'))
        self.assertEqual(row.template_vars['params'], [{'type': 'text', 'text': 'منى'}, {'type': 'text', 'text': '—'}])
        with mock.patch('apps.whatsapp.sender.WhatsAppSender') as WS:
            WS.return_value.is_configured = True
            WS.return_value.send_template.return_value = {'messages': [{'id': 'wamid.t1'}]}
            drain_queue()
        WS.return_value.send_template.assert_called_once()
        self.assertEqual(WS.return_value.send_template.call_args.kwargs['template_name'], 'summer_offer')
        WS.return_value.send_text.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.status, 'sent')

    def test_free_text_campaign_row_outside_window_is_skipped_not_sent(self):
        from unittest import mock
        from apps.campaigns.dispatcher import drain_queue
        from apps.campaigns.models import CampaignMessage
        from apps.whatsapp.models import WAConversation
        c = WhatsAppCampaign.objects.create(name='old', message_template='hi', status='running')
        conv = WAConversation.objects.create(wa_id='201033333333', customer=self.cust, status='open')
        CampaignMessage.objects.create(campaign=c, customer=self.cust, phone_number=self.cust.phone, message_text='hi',
                                       status='pending')
        WAMessageQueue.objects.create(conversation=conv, message_type='text', body='hi', priority=3)
        with mock.patch('apps.whatsapp.sender.WhatsAppSender') as WS:
            WS.return_value.is_configured = True
            drain_queue()
        WS.return_value.send_text.assert_not_called()
        self.assertEqual(WAMessageQueue.objects.get().status, 'failed')
        self.assertEqual(CampaignMessage.objects.get().status, 'skipped')

    def test_template_vars_are_validated(self):
        r = self.cc.post('/api/campaigns/', {'name': 'x', 'message_template': 'm', 'wa_template_name': 'Bad Name',
                                             'wa_template_vars': ['phone']}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('wa_template_name', r.data)
        self.assertIn('wa_template_vars', r.data)
