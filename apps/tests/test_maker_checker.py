"""
apps/tests/test_maker_checker.py

UAT W5b P0 (2026-11-17): nobody approves a money document they created themselves — ISR
replenishment, GL entries (test_gl_api) and price-change requests. The admin role is exempt while
SELF_APPROVAL_ADMIN_EXEMPT is True (the owner prepares and approves today; owner decision D4).
"""
from django.test import TestCase, override_settings

from core import maker_checker

from .factories import make_item, make_user


class RefusalUnitTests(TestCase):
    def setUp(self):
        self.p_user, self.p_prof, _ = make_user('mc_purch', role='purchasing')
        self.o_user, self.o_prof, _ = make_user('mc_other', role='purchasing')
        self.a_user, self.a_prof, _ = make_user('mc_admin', role='admin', access_all=True)

    def test_other_person_may_approve(self):
        self.assertIsNone(maker_checker.refusal(self.p_user, self.o_user))

    def test_same_person_refused_user_or_profile(self):
        self.assertEqual(maker_checker.refusal(self.p_user, self.p_user), maker_checker.MESSAGE)
        self.assertEqual(maker_checker.refusal(self.p_prof, self.p_user), maker_checker.MESSAGE)
        self.assertEqual(maker_checker.refusal(self.p_user, self.p_prof), maker_checker.MESSAGE)

    def test_unknown_maker_never_blocks(self):
        self.assertIsNone(maker_checker.refusal(None, self.p_user))

    def test_admin_exempt_by_default_and_not_when_switched_off(self):
        self.assertIsNone(maker_checker.refusal(self.a_prof, self.a_user))
        with override_settings(SELF_APPROVAL_ADMIN_EXEMPT=False):
            self.assertEqual(maker_checker.refusal(self.a_prof, self.a_user), maker_checker.MESSAGE)


class IsrApproveMakerCheckerTests(TestCase):
    def setUp(self):
        from apps.purchasing.models import IsrPush
        self.maker, _, self.maker_c = make_user('isr_maker', role='purchasing', access_all=True)
        _, _, self.other_c = make_user('isr_other', role='purchasing', access_all=True)
        self.push = IsrPush.objects.create(branchcode='100', dest_branchcode='160',
                                           kind=IsrPush.KIND_HQ_TO_BRANCH, status=IsrPush.STATUS_PROPOSED,
                                           lines_snapshot=[], created_by=self.maker)

    def _approve(self, client):
        return client.post(f'/api/purchasing/isr/pushes/{self.push.pk}/approve/', {}, format='json')

    def test_creator_cannot_approve_own_isr(self):
        r = self._approve(self.maker_c)
        self.assertEqual(r.status_code, 403, r.content)
        self.assertEqual(r.data['code'], 'self_approval')
        self.push.refresh_from_db()
        self.assertEqual(self.push.status, self.push.STATUS_PROPOSED)

    def test_colleague_approves(self):
        r = self._approve(self.other_c)
        self.assertEqual(r.status_code, 200, r.content)
        self.push.refresh_from_db()
        self.assertEqual(self.push.status, self.push.STATUS_APPROVED)


class PricingApproveMakerCheckerTests(TestCase):
    def setUp(self):
        from apps.discount_approvals.models import ItemPriceChangeRequest
        self.admin, _, self.admin_c = make_user('px_admin', role='admin', access_all=True)
        self.req = ItemPriceChangeRequest.objects.create(
            item=make_item(), requested_by=self.admin, old_values={}, new_values={'special_discp': '15'},
            reason='t', status=ItemPriceChangeRequest.STATUS_PENDING)

    @override_settings(SELF_APPROVAL_ADMIN_EXEMPT=False)
    def test_requester_cannot_approve_own_price_change(self):
        r = self.admin_c.post(f'/api/pricing-approvals/{self.req.pk}/approve/', {}, format='json')
        self.assertEqual(r.status_code, 403, r.content)
        self.assertEqual(r.data['error_code'], 'self_approval')

    def test_admin_exempt_reaches_the_writer_gate(self):
        # exempt: the self-check passes and the next guard (writer off in tests) answers
        r = self.admin_c.post(f'/api/pricing-approvals/{self.req.pk}/approve/', {}, format='json')
        self.assertNotEqual(r.data.get('error_code'), 'self_approval')
