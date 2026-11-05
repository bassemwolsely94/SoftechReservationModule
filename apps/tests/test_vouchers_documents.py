"""
Vouchers — redemption documents (R7, suite batch 7).

Business rule: Voucher.calculate_discount (min order, cap, never above the order).
View: a POS document lookup; permission: delivery (no voucher grant) cannot finish a document.

V-1 (fixed, owner OK 2026-11-05): mark-used locked the document with select_for_update() while also joining
the nullable `otp` FK, which PostgreSQL refuses ("FOR UPDATE cannot be applied to the nullable
side of an outer join"), so every call answered 500 and no VoucherRedemption audit row was ever
written. Fix: select_for_update(of=('self',)).
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.tests.factories import make_branch, make_user
from apps.tests.security.fixtures import bearer_client, seed_code_matrix
from apps.vouchers.models import Voucher, VoucherRedemption, VoucherRedemptionDocument
from core.middleware import module_access


def _voucher(**kw):
    base = dict(code='R7V1', title='خصم', voucher_type='discount_pct', discount_pct=Decimal('10'),
                valid_from=timezone.localdate(), status='active')
    base.update(kw)
    return Voucher.objects.create(**base)


class CalculateDiscountTests(TestCase):

    def test_percent_capped_and_min_order(self):
        v = _voucher(max_discount_cap=Decimal('15'), min_order_value=Decimal('50'))
        self.assertEqual(v.calculate_discount(40), 0.0)        # below the minimum order
        self.assertAlmostEqual(v.calculate_discount(100), 10.0)
        self.assertEqual(v.calculate_discount(500), 15.0)      # capped

    def test_fixed_never_exceeds_order(self):
        v = _voucher(code='R7V2', voucher_type='discount_fixed', discount_amount=Decimal('30'))
        self.assertEqual(v.calculate_discount(20), 20.0)


@override_settings(RBAC_ENFORCEMENT='log')
class DocumentViewTests(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.branch = make_branch()
        self.voucher = _voucher(code='R7V3')
        self.doc = VoucherRedemptionDocument.objects.create(
            voucher=self.voucher, customer_phone='01012345678', branch=self.branch,
            expires_at=timezone.now() + timedelta(minutes=15), reference_code='R7DOC1',
            order_amount=Decimal('100'), discount_applied=Decimal('10'))

    def tearDown(self):
        module_access.clear_cache()

    def _client(self, role):
        return bearer_client(make_user(f'r7v_{role}', role=role, branch=self.branch)[0])

    def test_pharmacist_reads_document(self):
        r = self._client('pharmacist').get('/api/vouchers/documents/r7doc1/')
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertEqual(r.data['reference_code'], 'R7DOC1')

    def test_unknown_document_is_404(self):
        r = self._client('pharmacist').get('/api/vouchers/documents/NOPE/')
        self.assertEqual(r.status_code, 404)

    def test_delivery_cannot_mark_used(self):
        r = self._client('delivery').post('/api/vouchers/documents/R7DOC1/mark-used/', {}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_mark_used_with_the_screens_empty_body_uses_the_stored_order(self):
        r = self._client('pharmacist').post('/api/vouchers/documents/R7DOC1/mark-used/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertEqual(r.data['discount_applied'], 10.0)      # 10% of the stored 100
        again = self._client('pharmacist').post('/api/vouchers/documents/R7DOC1/mark-used/', {},
                                                format='json')
        self.assertEqual(again.status_code, 400)                 # never redeemed twice
        self.assertEqual(VoucherRedemption.objects.filter(document=self.doc).count(), 1)

    def test_mark_used_writes_the_redemption_audit_row(self):
        c = self._client('pharmacist')
        c.raise_request_exception = False
        r = c.post('/api/vouchers/documents/R7DOC1/mark-used/', {'order_amount': 200}, format='json')
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertEqual(r.data['discount_applied'], 20.0)
        red = VoucherRedemption.objects.get(document=self.doc)
        self.assertEqual(red.discount_applied, Decimal('20'))
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.status, 'used')
