"""
apps/tests/test_pos_returns_switch.py

UAT owner decision D3 (2026-11-17): returns are not on the POS screen. POS_RETURNS_ENABLED
(default False) refuses a NEW return order; existing return orders keep their posting path.
The reference endpoint tells the screen whether to offer «مرتجع» and which branches it may sell for.
"""
from django.test import TestCase, override_settings
from rest_framework import status

from .factories import make_branch, make_branch2, make_call_center, make_user
from .test_pos_api import BASE, _payload


class PosReturnsSwitchTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        _, _, self.cc = make_call_center('cc_ret')

    def _return(self):
        return {**_payload(self.branch.id), 'doc_kind': 'return', 'return_of_invoice': 1234}

    def test_new_return_refused_by_default(self):
        r = self.cc.post(BASE, self._return(), format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.data)
        self.assertIn('doc_kind', r.data)

    @override_settings(POS_RETURNS_ENABLED=True)
    def test_return_allowed_when_switched_on(self):
        r = self.cc.post(BASE, self._return(), format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)

    def test_sale_unaffected(self):
        r = self.cc.post(BASE, _payload(self.branch.id), format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)

    def test_reference_reports_returns_off(self):
        self.assertFalse(self.cc.get(BASE + 'reference/').data['returns_enabled'])


class PosReferenceBranchesTests(TestCase):
    def test_branch_user_gets_own_branch_only(self):
        a, b = make_branch('فرع أ', 'B01'), make_branch2('فرع ب', 'B02')
        _, _, seller = make_user('ref_seller', role='salesperson', branch=a)
        ids = seller.get(BASE + 'reference/').data['pos_branch_ids']
        self.assertEqual(ids, [a.pk])
        self.assertNotIn(b.pk, ids)

    def test_all_branch_role_gets_none(self):
        make_branch()
        _, _, cc = make_call_center('ref_cc')
        self.assertIsNone(cc.get(BASE + 'reference/').data['pos_branch_ids'])
