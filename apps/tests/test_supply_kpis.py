"""
Phase-7 tests for the control-tower KPIs (doc 24 §25) — each formula pinned exactly.
"""
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.supply.kpis import supply_kpis
from apps.supply.models import (AvailabilityBatch, AvailabilityLine, SupplyCase,
                                 SupplyDecision)
from .factories import make_user


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item
        from apps.branches.models import Branch
        cls.item = Item.objects.create(softech_id='900001', name='KPI ITEM', is_active=True)
        cls.item2 = Item.objects.create(softech_id='900002', name='KPI OTHER', is_active=True)
        cls.a = Branch.objects.create(softech_branch_id='130', name='A')
        cls.b = Branch.objects.create(softech_branch_id='140', name='B')
        cls.user, cls.staff, _ = make_user('kpi_buyer', role='purchasing')


class EmptyTests(_Base):
    def test_empty_window_gives_none_ratios_not_zero_or_hundred(self):
        k = supply_kpis(days=30)
        self.assertIsNone(k['sourcing']['internal_share'])
        self.assertIsNone(k['sourcing']['supplier_fill_rate'])
        self.assertIsNone(k['matching']['match_precision'])
        self.assertIsNone(k['resolution']['avg_days_to_resolve'])
        self.assertIn('cash_avoided', k['definitions'])


class ResolutionTests(_Base):
    def test_average_and_median_days_to_resolve_for_fulfilled_only(self):
        now = timezone.now()
        for days_open in (2, 4, 9):
            c = SupplyCase.objects.create(item=self.item if days_open != 9 else self.item2,
                                          branch=self.a if days_open != 4 else self.b,
                                          status=SupplyCase.STATUS_FULFILLED, closed_at=now)
            SupplyCase.objects.filter(pk=c.pk).update(first_detected_at=now - timedelta(days=days_open))
        cancelled = SupplyCase.objects.create(item=self.item, branch=None,
                                              status=SupplyCase.STATUS_CANCELLED, closed_at=now)
        SupplyCase.objects.filter(pk=cancelled.pk).update(first_detected_at=now - timedelta(days=30))
        r = supply_kpis(days=30)['resolution']
        self.assertEqual(r['resolved_count'], 3)
        self.assertEqual(r['avg_days_to_resolve'], 5.0)       # (2+4+9)/3
        self.assertEqual(r['median_days_to_resolve'], 4.0)
        self.assertEqual(r['cancelled_count'], 1)             # not counted as resolved


class SourcingTests(_Base):
    def _transfer(self, status, qty):
        from apps.transfers.models import TransferRequest, TransferRequestItem
        tr = TransferRequest.objects.create(requesting_branch=self.a, supplying_branch=self.b,
                                            status=status)
        TransferRequestItem.objects.create(request=tr, item=self.item, quantity=qty)
        SupplyDecision.objects.create(kind=SupplyDecision.KIND_INTERNAL_TRANSFER, item=self.item,
                                      branch=self.a, recommended_qty=qty, decided_qty=qty,
                                      result_refs={'transfer_requests': [tr.pk]},
                                      idempotency_key=f't-{status}-{qty}')

    def _purchase(self, qty, receipt, price=None, eff=None, key=''):
        SupplyDecision.objects.create(kind=SupplyDecision.KIND_PURCHASE, item=self.item,
                                      branch=self.a, recommended_qty=qty, decided_qty=qty,
                                      receipt_status=receipt, unit_price=price,
                                      effective_cost=eff, order_ref=key or f'o-{receipt}',
                                      idempotency_key=f'p-{receipt}-{qty}-{key}')

    def test_mix_cash_avoided_and_supplier_fill_rate(self):
        from apps.procurement.models import PurchaseLine
        PurchaseLine.objects.create(item=self.item, item_code=self.item.softech_id, branch_code='100',
                                    supplier_code='260', doc_number='1',
                                    doc_date=date.today() - timedelta(days=40),
                                    doccode='10', effective_cost=70)
        PurchaseLine.objects.create(item=self.item, item_code=self.item.softech_id, branch_code='100',
                                    supplier_code='260', doc_number='2', doc_date=date.today(),
                                    doccode='10', effective_cost=80)      # latest → used
        self._transfer('approved', 5)          # realized → counts, saves 5 × 80
        self._transfer('draft', 2)             # in progress → mix only, no cash yet
        self._transfer('rejected', 9)          # dead → excluded everywhere
        self._purchase(7, SupplyDecision.RECEIPT_RECEIVED, price=100, eff=80, key='o1')
        self._purchase(3, SupplyDecision.RECEIPT_CANCELLED, key='o2')
        s = supply_kpis(days=30)['sourcing']
        self.assertEqual(s['internal_realized_qty'], 5.0)
        self.assertEqual(s['internal_in_progress_qty'], 2.0)
        self.assertEqual(s['internal_rejected_qty'], 9.0)
        self.assertEqual(s['internal_qty'], 7.0)
        self.assertEqual(s['external_qty'], 7.0)              # cancelled order excluded
        self.assertEqual(s['internal_share'], 0.5)
        self.assertEqual(s['cash_avoided'], 400.0)            # 5 × latest effective cost 80
        self.assertEqual(s['supplier_fill_rate'], 0.7)        # 7 received / (7 + 3)
        p = supply_kpis(days=30)['procurement']
        self.assertEqual(p['committed_value'], 700.0)          # 7 × 100
        self.assertEqual(p['foc_savings'], 140.0)             # (100 − 80) × 7


class MatchingTests(_Base):
    def test_precision_correction_and_manual_rates(self):
        b = AvailabilityBatch.objects.create(source='whatsapp')
        mk = lambda **kw: AvailabilityLine.objects.create(batch=b, raw_text='x', **kw)
        mk(item=self.item, is_confirmed=True, match_reason={'suggested_item_id': self.item.id})    # accepted
        mk(item=self.item, is_confirmed=True, match_reason={'suggested_item_id': self.item.id})    # accepted
        mk(item=self.item2, is_confirmed=True, match_reason={'suggested_item_id': self.item.id})   # corrected
        mk(item=self.item2, is_confirmed=True, match_reason={'suggested_item_id': None})           # manual
        mk(match_reason={'suggested_item_id': None}, is_unmatched=True)                            # unmatched
        m = supply_kpis(days=30)['matching']
        self.assertEqual(m['lines'], 5)
        self.assertEqual(m['auto_match_rate'], 0.6)           # 3 of 5 had a suggestion
        self.assertEqual(m['match_precision'], 0.667)         # 2 accepted of 3 judged
        self.assertEqual(m['correction_rate'], 0.333)
        self.assertEqual(m['manual_match_rate'], 0.25)        # 1 of 4 confirmed
        self.assertEqual(m['unmatched_lines'], 1)

    def test_ingest_preserves_the_original_suggestion(self):
        from apps.supply.availability import build_line
        b = AvailabilityBatch.objects.create(source='whatsapp')
        line = build_line(b, 'KPI ITEM 5')
        self.assertIn('suggested_item_id', line.match_reason)


class EndpointTests(_Base):
    def test_purchasing_sees_kpis_salesperson_is_denied(self):
        c = APIClient()
        c.force_authenticate(self.user)
        r = c.get('/api/dashboard/supply/?days=14')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['window_days'], 14)
        seller, _, _ = make_user('kpi_seller', role='salesperson')
        c2 = APIClient()
        c2.force_authenticate(seller)
        self.assertEqual(c2.get('/api/dashboard/supply/').status_code, 403)
