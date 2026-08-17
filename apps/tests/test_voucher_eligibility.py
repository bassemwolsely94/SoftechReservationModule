"""
apps/tests/test_voucher_eligibility.py

TD-M006 — item-level (and bundled branch-level) voucher eligibility gating.

Covers:
  - model: check_items_eligibility / check_branch_eligibility (unit)
  - validate / generate-otp / verify-otp reject when an item-restricted voucher
    is redeemed without (or with the wrong) items
  - the same flow succeeds when a qualifying item is supplied
  - an ineligible verify-otp does NOT consume the customer's OTP
  - branch restriction: redemption at a non-eligible branch is rejected
"""
import datetime

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from apps.vouchers.models import Voucher, VoucherOTP
from .factories import make_branch, make_branch2, make_admin, make_user, make_item

VOUCHERS_URL = '/api/vouchers/vouchers/'


def _url(pk, action):
    return f'{VOUCHERS_URL}{pk}/{action}/'


def _voucher(**extra):
    defaults = dict(
        code=Voucher.generate_code(), title='قسيمة اختبار',
        voucher_type='discount_pct', discount_pct=10,
        status='active', max_uses=10, valid_from=datetime.date.today(),
    )
    defaults.update(extra)
    return Voucher.objects.create(**defaults)


class VoucherItemEligibilityModelTests(TestCase):
    """Unit-level gate behaviour (no HTTP)."""

    def setUp(self):
        self.item  = make_item(name='صنف مؤهل', softech_id='ELG01')
        self.other = make_item(name='صنف آخر',  softech_id='OTH01')

    def test_unrestricted_always_eligible(self):
        v = _voucher()
        self.assertTrue(v.check_items_eligibility([])[0])
        self.assertTrue(v.check_items_eligibility([self.other.id])[0])

    def test_restricted_requires_items(self):
        v = _voucher()
        v.applicable_items.add(self.item)
        self.assertFalse(v.check_items_eligibility([])[0])           # none supplied
        self.assertFalse(v.check_items_eligibility([self.other.id])[0])  # wrong item
        self.assertTrue(v.check_items_eligibility([self.item.id])[0])    # qualifying

    def test_branch_gate(self):
        b1, b2 = make_branch(), make_branch2()
        v = _voucher()
        self.assertTrue(v.check_branch_eligibility(b1)[0])  # unrestricted
        v.applicable_branches.add(b2)
        self.assertFalse(v.check_branch_eligibility(b1)[0])
        self.assertTrue(v.check_branch_eligibility(b2)[0])
        self.assertFalse(v.check_branch_eligibility(None)[0])


class VoucherItemEligibilityViewTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        _, self.profile, self.client = make_admin('admin_item_elig')
        self.item  = make_item(name='صنف مؤهل', softech_id='ELG02')
        self.other = make_item(name='صنف آخر',  softech_id='OTH02')
        self.voucher = _voucher()
        self.voucher.applicable_items.add(self.item)
        self.phone = '01000000000'

    def test_validate_rejects_without_items(self):
        r = self.client.post(_url(self.voucher.id, 'validate'),
                             {'phone': self.phone}, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_validate_rejects_non_applicable_item(self):
        r = self.client.post(_url(self.voucher.id, 'validate'),
                             {'phone': self.phone, 'item_ids': [self.other.id]}, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_validate_accepts_applicable_item(self):
        r = self.client.post(_url(self.voucher.id, 'validate'),
                             {'phone': self.phone, 'item_ids': [self.item.id]}, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(r.data['eligible'])

    def test_generate_otp_rejects_without_items(self):
        r = self.client.post(_url(self.voucher.id, 'generate-otp'),
                             {'phone': self.phone}, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unrestricted_voucher_needs_no_items(self):
        v = _voucher()  # no applicable_items
        r = self.client.post(_url(v.id, 'validate'),
                             {'phone': self.phone}, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_verify_without_items_rejected_and_otp_preserved(self):
        otp, _, plain = VoucherOTP.create_for_voucher(self.voucher, self.phone)
        r = self.client.post(_url(self.voucher.id, 'verify-otp'),
                             {'phone': self.phone, 'code': plain}, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        otp.refresh_from_db()
        self.assertFalse(otp.is_used)   # ineligible request must NOT burn the code

    def test_verify_with_items_creates_document(self):
        otp, _, plain = VoucherOTP.create_for_voucher(self.voucher, self.phone)
        r = self.client.post(_url(self.voucher.id, 'verify-otp'),
                             {'phone': self.phone, 'code': plain,
                              'item_ids': [self.item.id]}, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn('document', r.data)


class VoucherBranchEligibilityViewTests(TestCase):

    def setUp(self):
        self.b1 = make_branch()
        self.b2 = make_branch2()
        # Employee stationed at b1
        _, self.profile, self.client = make_user(
            'emp_branch_gate', role='admin', branch=self.b1, access_all=True,
        )
        self.voucher = _voucher()
        self.voucher.applicable_branches.add(self.b2)  # valid only at b2
        self.phone = '01000000000'

    def test_validate_rejects_wrong_branch(self):
        r = self.client.post(_url(self.voucher.id, 'validate'),
                             {'phone': self.phone}, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_validate_accepts_matching_branch(self):
        self.voucher.applicable_branches.set([self.b1])
        r = self.client.post(_url(self.voucher.id, 'validate'),
                             {'phone': self.phone}, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(r.data['eligible'])
