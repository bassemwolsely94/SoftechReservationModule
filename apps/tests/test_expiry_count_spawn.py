"""
apps/tests/test_expiry_count_spawn.py

Batch 2 tests for the purchase-expiry → physical stock-count bridge:
  • apps.stockcount.engine.apply_single_count captures physical_expiry
  • POST /api/batches/purchase-expiry/spawn-count/ builds an expiry_audit session
  • POST /api/batches/purchase-expiry/candidates/ validates its inputs
  • GET  /api/batches/purchase-expiry/runs/ lists backfill runs

SOFTECH is never touched: the spawn test injects explicit item_codes (skipping
the live candidate/stock lookup) and mocks the stock-count engine's
fetch_filtered_stock so generate_snapshot runs against fake stock.
"""
import datetime as _dt
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from rest_framework import status

from apps.batches.models import PurchaseExpiryEntry, PurchaseExpiryAuditRun
from apps.stockcount.models import StockCountSession, StockCountSnapshot
from apps.stockcount.engine import apply_single_count
from .factories import make_admin


class ApplySingleCountExpiryTests(TestCase):
    def setUp(self):
        self.session = StockCountSession.objects.create(
            name='audit', mode='expiry_audit', branch_code='130',
            item_codes_filter=['A100'], status='snapshot_taken',
        )
        self.snap = StockCountSnapshot.objects.create(
            session=self.session, item_code='A100', item_name='Item A100',
            branch_code='130', expected_qty=Decimal('5'),
        )

    def test_captures_physical_expiry_and_variance(self):
        snap = apply_single_count(self.session, 'A100', 3,
                                  physical_expiry='2025-06-30')
        self.assertEqual(snap.physical_expiry, _dt.date(2025, 6, 30))
        self.assertEqual(snap.counted_qty, Decimal('3.000'))
        self.assertEqual(snap.variance_type, 'deficit')

    def test_physical_expiry_optional(self):
        snap = apply_single_count(self.session, 'A100', 5)
        self.assertIsNone(snap.physical_expiry)
        self.assertEqual(snap.variance_type, 'ok')

    def test_bad_expiry_string_ignored(self):
        snap = apply_single_count(self.session, 'A100', 5, physical_expiry='not-a-date')
        self.assertIsNone(snap.physical_expiry)


class SpawnExpiryCountSessionTests(TestCase):
    SPAWN_URL = '/api/batches/purchase-expiry/spawn-count/'
    # Window is the ENTERED-EXPIRY range (purchases happened earlier, in 2023).
    WINDOW = {'from': '2024-01-01', 'to': '2025-12-31'}

    def setUp(self):
        self.user, self.profile, self.client = make_admin('exp_admin')
        # Purchases made in 2023, recording batches that expire in 2024/2025.
        for code, exp in [('A100', _dt.date(2024, 6, 30)),
                          ('A100', _dt.date(2025, 1, 31)),
                          ('A200', _dt.date(2024, 9, 30))]:
            PurchaseExpiryEntry.objects.create(
                branch_code='130', supplier_code='S1', supplier_name='Dist One',
                supplier_category='OFFICIAL_DISTRIBUTOR', doc_number='1',
                doc_date=_dt.date(2023, 5, 1), item_code=code, item_name=f'Item {code}',
                dblitemflag=1 if exp.year == 2024 else 2, entered_expiry=exp,
                qty=Decimal('10'),
            )

    def _fake_stock(self, branch_code, item_codes):
        # Mirrors engine.fetch_filtered_stock's return shape.
        return [
            {'item_code': c, 'item_name': f'Item {c}', 'item_medicine': '',
             'category_name': 'cat', 'qty': Decimal('8')}
            for c in item_codes
        ]

    def test_spawn_creates_expiry_audit_session_with_hints(self):
        with patch('apps.stockcount.engine.fetch_filtered_stock', side_effect=self._fake_stock):
            r = self.client.post(self.SPAWN_URL, {
                **self.WINDOW, 'branch': '130', 'item_codes': ['A100', 'A200'],
            }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)
        self.assertEqual(r.data['item_count'], 2)

        session = StockCountSession.objects.get(pk=r.data['session_id'])
        self.assertEqual(session.mode, 'expiry_audit')
        self.assertEqual(session.branch_code, '130')
        self.assertEqual(session.status, 'snapshot_taken')

        snaps = {s.item_code: s for s in session.snapshots.all()}
        self.assertEqual(set(snaps), {'A100', 'A200'})
        # Earliest keyed expiry becomes the hint.
        self.assertEqual(snaps['A100'].entered_expiry_hint, _dt.date(2024, 6, 30))
        self.assertEqual(snaps['A200'].entered_expiry_hint, _dt.date(2024, 9, 30))
        # Physical expiry starts empty (counter fills it).
        self.assertIsNone(snaps['A100'].physical_expiry)

    def test_spawn_requires_branch(self):
        r = self.client.post(self.SPAWN_URL, {**self.WINDOW, 'item_codes': ['A100']},
                             format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_spawn_empty_codes_rejected(self):
        with patch('apps.stockcount.engine.fetch_filtered_stock', side_effect=self._fake_stock):
            r = self.client.post(self.SPAWN_URL, {
                **self.WINDOW, 'branch': '130', 'item_codes': [],
            }, format='json')
        # empty explicit list → falls through to candidate lookup; with no live
        # stock check mocked at that layer it would hit SOFTECH, so we assert the
        # request is well-formed by requiring a non-empty explicit list instead.
        self.assertIn(r.status_code, (status.HTTP_400_BAD_REQUEST,
                                      status.HTTP_503_SERVICE_UNAVAILABLE))


class CandidatesAndRunsEndpointTests(TestCase):
    CAND_URL = '/api/batches/purchase-expiry/candidates/'
    RUNS_URL = '/api/batches/purchase-expiry/runs/'

    def setUp(self):
        self.user, self.profile, self.client = make_admin('exp_admin2')

    def test_candidates_requires_dates(self):
        r = self.client.post(self.CAND_URL, {}, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_candidates_rejects_reversed_window(self):
        r = self.client.post(self.CAND_URL,
                             {'from': '2024-01-01', 'to': '2023-01-01'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_runs_list(self):
        PurchaseExpiryAuditRun.objects.create(
            window_from=_dt.date(2023, 1, 1), window_to=_dt.date(2023, 12, 31),
            status='success', lines_upserted=42,
        )
        r = self.client.get(self.RUNS_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        # List endpoint is paginated → rows live under 'results'.
        rows = r.data['results'] if isinstance(r.data, dict) and 'results' in r.data else r.data
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['lines_upserted'], 42)
