"""Marketplace channels (doc 38) — Task 1: access, seed grants, model constraints."""
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from apps.marketplace.access import Access
from apps.marketplace.models import ChannelStore, ExternalOrder, MarketplaceChannel
from apps.tests.factories import make_admin, make_branch, make_pharmacist
from apps.users.management.commands.seed_permissions import PERMISSIONS


class MarketplaceAccessTests(TestCase):
    def test_flag_off_hides_everything(self):
        user, _, _ = make_admin('mp_admin_off')
        with override_settings(MARKETPLACE_ENABLED=False):
            a = Access(user)
            self.assertIs(a.can_view, False)
            self.assertIs(a.can_create, False)
            self.assertIs(a.can_approve, False)
            self.assertIs(a.can_edit, False)

    @override_settings(MARKETPLACE_ENABLED=True)
    def test_flag_on_admin_sees_all(self):
        user, _, _ = make_admin('mp_admin_on')
        a = Access(user)
        self.assertTrue(a.can_view and a.can_create and a.can_approve and a.can_edit)
        self.assertEqual(set(a.as_dict()), {'can_view', 'can_create', 'can_approve', 'can_edit'})

    def test_seed_grants_match_brief(self):
        self.assertEqual(PERMISSIONS['supervisor']['marketplace'], {'view', 'create', 'approve', 'edit', 'export'})
        self.assertEqual(PERMISSIONS['pharmacist']['marketplace'], {'view', 'create'})
        self.assertEqual(PERMISSIONS['call_center']['marketplace'], {'view', 'create'})
        self.assertEqual(PERMISSIONS['quality_manager']['marketplace'], {'view', 'export'})
        self.assertEqual(PERMISSIONS['purchasing']['marketplace'], {'view'})
        self.assertNotIn('marketplace', PERMISSIONS['viewer'])

    @override_settings(MARKETPLACE_ENABLED=True)
    def test_pharmacist_has_view_and_create_not_approve(self):
        from django.core.management import call_command
        call_command('seed_permissions', verbosity=0)
        user, _, _ = make_pharmacist('mp_pharma')
        a = Access(user)
        self.assertTrue(a.can_view)
        self.assertTrue(a.can_create)
        self.assertFalse(a.can_approve)
        self.assertFalse(a.can_edit)


class MarketplaceModelTests(TestCase):
    def test_external_order_unique_per_channel(self):
        branch = make_branch()
        ch = MarketplaceChannel.objects.create(code='manual_test', name='تجربة', adapter='manual')
        store = ChannelStore.objects.create(channel=ch, branch=branch)
        ExternalOrder.objects.create(channel=ch, store=store, branch=branch, external_id='A1')
        with self.assertRaises(IntegrityError), transaction.atomic():
            ExternalOrder.objects.create(channel=ch, store=store, branch=branch, external_id='A1')
        # same external id on another channel is fine
        ch2 = MarketplaceChannel.objects.create(code='fake_two', name='ثانية', adapter='fake')
        store2 = ChannelStore.objects.create(channel=ch2, branch=branch)
        ExternalOrder.objects.create(channel=ch2, store=store2, branch=branch, external_id='A1')
