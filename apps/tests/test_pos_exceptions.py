"""
apps/tests/test_pos_exceptions.py — POS Exception Center bucketing (Wave 8).

Pure ORM test of `views.exception_buckets` (no HTTP/auth): orders in each problem state are
bucketed correctly, staleness thresholds are honoured, and value-at-risk sums doc_value.
Read-only aggregation — no SOFTECH contact, no status mutation.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.pos_orders.models import SoftechSalesOrder as S
from apps.pos_orders.views import exception_buckets
from .factories import make_branch


class ExceptionBucketTests(TestCase):
    def setUp(self):
        self.br = make_branch()
        self.now = timezone.now()

    def _order(self, status, doc_value='100', updated_ago_min=None, executed_ago_min=None,
               needs_review=False):
        o = S.objects.create(branch=self.br, softech_branchcode=self.br.softech_branch_id,
                             store_code=self.br.softech_branch_id[:3], channel='cash',
                             doc_kind='sale', customer_name='T', status=status, doc_value=doc_value,
                             needs_review=needs_review,
                             review_reason='pending_gone_no_final' if needs_review else '')
        # auto_now fields must be backdated with an UPDATE (save() would reset updated_at).
        fields = {}
        if updated_ago_min is not None:
            fields['updated_at'] = self.now - timedelta(minutes=updated_ago_min)
        if executed_ago_min is not None:
            fields['erp_executed_at'] = self.now - timedelta(minutes=executed_ago_min)
        if fields:
            S.objects.filter(pk=o.pk).update(**fields)
        return o

    def _bucket(self, buckets, key):
        return next(b for b in buckets if b['key'] == key)

    def test_push_failed_always_bucketed(self):
        self._order(S.STATUS_PUSH_FAILED, doc_value='250')
        b = self._bucket(exception_buckets(S.objects.all(), self.now), 'push_failed')
        self.assertEqual(b['count'], 1)
        self.assertEqual(b['value_at_risk'], 250.0)
        self.assertEqual(b['severity'], 'error')

    def test_stuck_queued_only_when_stale(self):
        self._order(S.STATUS_QUEUED, updated_ago_min=30)   # stale → bucketed
        self._order(S.STATUS_QUEUED, updated_ago_min=1)    # fresh → not yet
        b = self._bucket(exception_buckets(S.objects.all(), self.now, queued_stale=10), 'stuck_queued')
        self.assertEqual(b['count'], 1)

    def test_stuck_pushing_only_when_stale(self):
        self._order(S.STATUS_PUSHING, updated_ago_min=20)  # orphaned mid-push
        b = self._bucket(exception_buckets(S.objects.all(), self.now, pushing_stale=5), 'stuck_pushing')
        self.assertEqual(b['count'], 1)

    def test_awaiting_cashier_leakage_when_pushed_too_long(self):
        self._order(S.STATUS_PUSHED, doc_value='500', executed_ago_min=180)  # stale awaiting settle
        self._order(S.STATUS_PUSHED, executed_ago_min=5)                     # fresh → fine
        b = self._bucket(exception_buckets(S.objects.all(), self.now, pushed_stale=120), 'awaiting_cashier')
        self.assertEqual(b['count'], 1)
        self.assertEqual(b['value_at_risk'], 500.0)

    def test_leakage_bucket_from_needs_review(self):
        # reconcile flagged: pushed order whose pending vanished with no final doc
        self._order(S.STATUS_PUSHED, doc_value='300', executed_ago_min=300, needs_review=True)
        buckets = exception_buckets(S.objects.all(), self.now, pushed_stale=120)
        leak = self._bucket(buckets, 'leakage')
        self.assertEqual(leak['count'], 1)
        self.assertEqual(leak['value_at_risk'], 300.0)
        self.assertEqual(leak['severity'], 'error')
        # must NOT also appear under awaiting_cashier (deduped by needs_review=False filter)
        self.assertEqual(self._bucket(buckets, 'awaiting_cashier')['count'], 0)

    def test_healthy_orders_never_bucketed(self):
        self._order(S.STATUS_SETTLED)
        self._order(S.STATUS_DRAFT)
        self._order(S.STATUS_READY)
        buckets = exception_buckets(S.objects.all(), self.now)
        self.assertEqual(sum(b['count'] for b in buckets), 0)

    def test_order_row_shape_and_age(self):
        self._order(S.STATUS_PUSH_FAILED, updated_ago_min=45)
        b = self._bucket(exception_buckets(S.objects.all(), self.now), 'push_failed')
        row = b['orders'][0]
        self.assertIn('status_display', row)
        self.assertIn('branch_name', row)
        self.assertEqual(row['status'], S.STATUS_PUSH_FAILED)
        self.assertGreaterEqual(row['age_min'], 44)   # anchored on updated_at (no erp_executed_at)
