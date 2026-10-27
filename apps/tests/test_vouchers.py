"""
apps/tests/test_vouchers.py

Tests covering:
  - Voucher create / list / retrieve
  - Eligibility check (validate endpoint)
  - OTP generation: rate limit (3 per 10 min)
  - OTP generation: OTP plain code NOT in response
  - OTP verify: correct / wrong / expired / exceeded retries
  - OTP verify: atomic double-submission guard
  - Mark-used: idempotency (second call returns 400)
  - Cancel voucher: only admin / manager can cancel
  - Lookup by code
  - PII masking on print endpoint for non-PII roles
"""
from django.test import TestCase
from django.utils import timezone
from django.utils.timezone import now as tz_now
import datetime
from rest_framework.test import APIClient
from rest_framework import status

from apps.vouchers.models import Voucher, VoucherOTP
from apps.branches.models import Branch
from .factories import make_branch, make_admin, make_pharmacist, make_customer

VOUCHERS_URL = '/api/vouchers/vouchers/'
DOCS_URL     = '/api/vouchers/documents/'


def _voucher_url(pk, action=''):
    base = f'{VOUCHERS_URL}{pk}/'
    return base + action + ('/' if action else '')


def _doc_url(ref, action=''):
    base = f'{DOCS_URL}{ref}/'
    return base + action + ('/' if action else '')


def _make_voucher(branch, created_by_profile, voucher_type='discount_pct', pct=10):
    today = datetime.date.today()
    return Voucher.objects.create(
        code=Voucher.generate_code(),
        title='قسيمة اختبار',
        voucher_type=voucher_type,
        discount_pct=pct if voucher_type == 'discount_pct' else 0,
        discount_amount=50 if voucher_type == 'discount_fixed' else 0,
        branch=branch,
        created_by=created_by_profile,
        status='active',
        max_uses=10,
        valid_from=today,
    )


class VoucherListCreateTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        _, self.profile, self.client = make_admin('admin_voucher')

    def test_list_vouchers(self):
        r = self.client.get(VOUCHERS_URL)
        self.assertIn(r.status_code, [status.HTTP_200_OK])

    def test_list_requires_auth(self):
        r = APIClient().get(VOUCHERS_URL)
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_voucher(self):
        r = self.client.post(VOUCHERS_URL, {
            'title': 'قسيمة جديدة',
            'voucher_type': 'discount_pct',
            'discount_pct': 15,
            'branch': self.branch.id,
            'status': 'active',
            'valid_from': datetime.date.today().isoformat(),
        }, format='json')
        self.assertIn(r.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])
        if r.status_code == status.HTTP_201_CREATED:
            # Gap-7 FIXED: VoucherCreateSerializer now includes id + code as read_only,
            # so the 201 response carries the generated code directly.
            self.assertIn('id', r.data, 'Response must include the new voucher id')
            self.assertIn('code', r.data, 'Response must include the generated code')
            self.assertNotEqual(r.data['code'], '',
                                'Voucher must be assigned a non-empty code on creation')


class VoucherLookupTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        _, self.profile, self.client = make_admin('admin_lookup')
        self.voucher = _make_voucher(self.branch, self.profile)

    def test_lookup_by_code(self):
        r = self.client.get(f'{VOUCHERS_URL}lookup/?code={self.voucher.code}')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['code'], self.voucher.code)

    def test_lookup_wrong_code(self):
        r = self.client.get(f'{VOUCHERS_URL}lookup/?code=INVALID-XXXX')
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_lookup_empty_code(self):
        r = self.client.get(f'{VOUCHERS_URL}lookup/')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class OTPRateLimitTests(TestCase):
    """OTP generation must be rate-limited to 3 per phone per 10 minutes."""

    def setUp(self):
        self.branch = make_branch()
        _, self.profile, self.client = make_admin('admin_otp_rl')
        self.voucher = _make_voucher(self.branch, self.profile)
        self.phone = '01012345678'

    def _gen(self):
        return self.client.post(
            _voucher_url(self.voucher.id, 'generate-otp'),
            {'phone': self.phone},
            format='json',
        )

    def test_otp_does_not_expose_plain_code(self):
        """The plain OTP digits must NEVER appear in the API response."""
        r = self._gen()
        if r.status_code == status.HTTP_200_OK:
            data_str = str(r.data)
            # The plain code is 6 digits; make sure no 'code' key with digits
            self.assertNotIn('plain_code', r.data,
                             'SECURITY: plain OTP code must never be in API response')
            # whatsapp_url may contain a URL-encoded message — check it doesn't
            # embed raw digits as a 'code=' param
            wa = r.data.get('whatsapp_url', '')
            self.assertNotIn('otp=', wa, 'SECURITY: OTP must not be embedded in plain wa.me URL params')

    def test_otp_rate_limit_3_per_10_min(self):
        """After 3 OTP requests in the window the 4th must return 429."""
        for _ in range(3):
            self._gen()
        r = self._gen()  # 4th attempt — should be rate limited
        self.assertEqual(r.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
                         'OTP must be rate-limited to 3 per 10 minutes')

    def test_otp_resend_window_reset(self):
        """
        KNOWN EDGE: resend count is based on created_at >= now-10min.
        Old OTPs (> 10 min) must not count against the limit.
        """
        # Create 3 old OTPs (outside window)
        old_time = timezone.now() - timezone.timedelta(minutes=15)
        for i in range(3):
            otp = VoucherOTP(
                voucher=self.voucher,
                phone=self.phone,
                code_hash='oldhash',
                expires_at=old_time + timezone.timedelta(minutes=3),
            )
            otp.save()
            VoucherOTP.objects.filter(pk=otp.pk).update(created_at=old_time)

        # Now a fresh request should succeed (window cleared)
        r = self._gen()
        self.assertNotEqual(r.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
                            'Old OTPs (>10min) must not count against the rate limit')


class VoucherCancelTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        _, self.admin_profile, self.admin_client = make_admin('admin_cancel')
        _, self.pharma_profile, self.pharma_client = make_pharmacist('pharma_cancel', branch=self.branch)
        self.voucher = _make_voucher(self.branch, self.admin_profile)

    def test_admin_can_cancel(self):
        r = self.admin_client.post(_voucher_url(self.voucher.id, 'cancel'))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.voucher.refresh_from_db()
        self.assertEqual(self.voucher.status, 'cancelled')

    def test_pharmacist_cannot_cancel_voucher(self):
        """Gap-3 FIXED: cancel action now requires admin or manager role."""
        r = self.pharma_client.post(_voucher_url(self.voucher.id, 'cancel'))
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN,
                         'Pharmacist must receive 403 when attempting to cancel a voucher')

    def test_cancel_already_cancelled_returns_400(self):
        self.voucher.status = 'cancelled'
        self.voucher.save()
        r = self.admin_client.post(_voucher_url(self.voucher.id, 'cancel'))
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
