"""
apps/tests/test_offers_channel_a.py

Channel A — flat-rate offer → item posdiscp PLANNER (PG-only dry-run, ZERO SOFTECH
writes). Only percent offers are eligible; the plan diffs the synced pos_discp
mirror against the offer's %. The live write (A2) is gated + not wired.
"""
from decimal import Decimal
from django.test import TestCase, override_settings

from apps.catalog.models import Item
from apps.offers.models import Offer
from apps.offers.channel_a import is_channel_a_eligible, plan_posdiscp, apply_posdiscp
from .factories import make_item, make_user


def _item(code, producer, pos_discp=0):
    it = make_item(name=code, softech_id=code)
    it.producer_code = producer
    it.pos_discp = Decimal(str(pos_discp))
    it.save()
    return it


def _percent_offer(value=25, **kw):
    kw.setdefault('require_stock', False)
    return Offer.objects.create(name='flat', offer_type='percent', status='active',
                                value=Decimal(str(value)), **kw)


class EligibilityTests(TestCase):
    def test_percent_eligible(self):
        self.assertTrue(is_channel_a_eligible(_percent_offer(25))[0])

    def test_bxgy_not_eligible(self):
        o = Offer.objects.create(name='b', offer_type='bxgy', status='active', require_stock=False)
        self.assertFalse(is_channel_a_eligible(o)[0])

    def test_bad_percent_not_eligible(self):
        self.assertFalse(is_channel_a_eligible(_percent_offer(0))[0])
        self.assertFalse(is_channel_a_eligible(_percent_offer(150))[0])


class PlanTests(TestCase):
    def setUp(self):
        self.a = _item('A', 'PARK', pos_discp=0)     # needs change → 25
        self.b = _item('B', 'PARK', pos_discp=25)    # already 25 → unchanged
        self.c = _item('C', 'OTHER', pos_discp=0)    # not targeted
        self.o = _percent_offer(25, target_spec={'rules': [{'field': 'producer_code', 'op': 'eq', 'value': 'PARK'}]})

    def test_plan_diffs_correctly(self):
        plan = plan_posdiscp(self.o)
        self.assertTrue(plan['eligible'])
        changed = {c['softech_id'] for c in plan['changes']}
        self.assertEqual(changed, {'A'})                 # only A needs change
        self.assertEqual(plan['summary']['unchanged'], 1)  # B already 25
        self.assertEqual(plan['changes'][0]['new_posdiscp'], 25.0)
        self.assertEqual(plan['changes'][0]['current_posdiscp'], 0.0)

    def test_plan_respects_exclude(self):
        self.o.excluded_items.add(self.a)
        plan = plan_posdiscp(self.o)
        self.assertEqual(plan['changes'], [])            # A excluded, B unchanged

    def test_ineligible_offer_plan_empty(self):
        o = Offer.objects.create(name='b', offer_type='bxgy', status='active', require_stock=False)
        self.assertFalse(plan_posdiscp(o)['eligible'])


class ApplyGateTests(TestCase):
    def setUp(self):
        self.a = _item('A', 'PARK', pos_discp=0)
        self.o = _percent_offer(25, target_spec={'rules': [{'field': 'producer_code', 'op': 'eq', 'value': 'PARK'}]})

    def test_apply_flag_off_writes_nothing(self):
        res = apply_posdiscp(self.o, commit=True)      # flag default off
        self.assertFalse(res['applied'])
        self.assertIn('plan', res)
        self.a.refresh_from_db()
        self.assertEqual(self.a.pos_discp, Decimal('0'))   # pos_discp untouched

    @override_settings(POS_OFFERS_POSDISCP_WRITE_ENABLED=True)
    def test_flag_on_still_needs_confirm(self):
        # flag on but no confirm token → returns requires_confirm, no SOFTECH contact
        res = apply_posdiscp(self.o, commit=True, confirm=False)
        self.assertTrue(res['requires_confirm'])
        self.a.refresh_from_db()
        self.assertEqual(self.a.pos_discp, Decimal('0'))

    @override_settings(POS_OFFERS_POSDISCP_WRITE_ENABLED=True)
    def test_flag_on_confirm_but_no_softech_user_blocks(self):
        # confirmed, but the actor has no linked SOFTECH usercode → no write attempted
        _, profile, _ = make_user('ca_nouser', role='admin')   # softech_user_id blank
        res = apply_posdiscp(self.o, actor=profile, commit=True, confirm=True)
        self.assertFalse(res['applied'])
        self.assertEqual(res['error'], 'no_softech_user')
        self.a.refresh_from_db()
        self.assertEqual(self.a.pos_discp, Decimal('0'))


class ApiTests(TestCase):
    def setUp(self):
        self.a = _item('A', 'PARK', pos_discp=0)
        self.o = _percent_offer(25, target_spec={'rules': [{'field': 'producer_code', 'op': 'eq', 'value': 'PARK'}]})

    def test_plan_endpoint(self):
        _, _, admin = make_user('ca_admin', role='admin')
        r = admin.get(f'/api/offers/{self.o.id}/posdiscp-plan/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['eligible'])
        self.assertEqual(len(r.data['changes']), 1)

    def test_apply_endpoint_non_admin_forbidden(self):
        _, _, sup = make_user('ca_sup', role='supervisor')
        r = sup.post(f'/api/offers/{self.o.id}/posdiscp-apply/')
        self.assertEqual(r.status_code, 403)

    def test_apply_endpoint_flag_off_returns_plan(self):
        _, _, admin = make_user('ca_admin2', role='admin')
        r = admin.post(f'/api/offers/{self.o.id}/posdiscp-apply/')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data['applied'])
        self.a.refresh_from_db()
        self.assertEqual(self.a.pos_discp, Decimal('0'))
