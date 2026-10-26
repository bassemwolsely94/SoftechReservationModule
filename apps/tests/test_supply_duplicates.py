"""
Supplier lists — one row per item once a list is locked (owner 2026-10-12): rows matched to
the same item are merged into one (confirmed first, then the one with more supplier terms,
then the earliest), the others drop out of the review / counts / comparison, the merge is in
the audit trail, unlocking brings them back, and an order can never carry the same item twice.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.supply import availability as av
from apps.supply.execution import ExecutionError, _resolve_lines
from apps.supply.models import AvailabilityBatch, AvailabilityLine


class DuplicateCollapseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item
        from .factories import make_user
        cls.aug = Item.objects.create(softech_id='630001', name='AUGMENTIN 1G 14TAB', is_active=True)
        cls.pan = Item.objects.create(softech_id='630002', name='PANADOL ACUTE 20TAB', is_active=True)
        cls.bru = Item.objects.create(softech_id='630003', name='BRUFEN 400MG 30TAB', is_active=True)
        cls.user, _, _ = make_user('op_avail_dups', role='purchasing')

    def setUp(self):
        self.c = APIClient()
        self.c.force_authenticate(self.user)
        self.b = AvailabilityBatch.objects.create(source='whatsapp')
        mk = lambda raw, item, **kw: AvailabilityLine.objects.create(batch=self.b, raw_text=raw, item=item, **kw)
        self.a1 = mk('اوجمنتين 1 جم *100', self.aug)
        self.a2 = mk('اوجمنتين 1 جم 14 ق', self.aug, is_confirmed=True)       # confirmed → kept
        self.p1 = mk('بانادول لنزلات البرد 20 ق', self.pan)
        self.p2 = mk('بانادول لنزلات البرد 20 ق', self.pan, quota=Decimal('5'))  # more terms → kept
        self.b1 = mk('بروفين 400', self.bru)
        self.url = f'/api/supply/availability/{self.b.id}/'

    def test_lock_keeps_one_row_per_item_and_unlock_restores(self):
        r = self.c.post(self.url + 'lock/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['duplicates_merged'], 2)
        self.assertEqual(r.json()['line_count'], 3)
        self.a1.refresh_from_db()
        self.p1.refresh_from_db()
        self.assertEqual((self.a1.duplicate_of_id, self.p1.duplicate_of_id), (self.a2.id, self.p2.id))
        rows = self.c.get(self.url + 'analysis/').json()['lines']
        self.assertEqual(sorted(x['line_id'] for x in rows), sorted([self.a2.id, self.p2.id, self.b1.id]))
        kept = next(x for x in rows if x['line_id'] == self.a2.id)
        self.assertEqual([m['raw_text'] for m in kept['merged']], ['اوجمنتين 1 جم *100'])
        # audited
        locked = next(x for x in self.c.get(self.url + 'history/').json() if x['event'] == 'locked')
        self.assertEqual(len(locked['extra']['duplicates_merged']), 2)
        # unlock brings them back
        r = self.c.post(self.url + 'unlock/', {'reason': 'fix a match'}, format='json')
        self.assertEqual(r.json()['line_count'], 5)
        self.assertFalse(AvailabilityLine.objects.filter(batch=self.b, duplicate_of__isnull=False).exists())
        self.a2.refresh_from_db()
        self.assertNotIn('merged', self.a2.match_reason)
        self.assertEqual(len(self.c.get(self.url + 'analysis/').json()['lines']), 5)

    def test_no_duplicates_no_change(self):
        AvailabilityLine.objects.filter(pk__in=[self.a1.pk, self.p1.pk]).delete()
        self.assertEqual(av.collapse_duplicates(self.b), [])

    def test_an_order_never_carries_the_same_item_twice(self):
        with self.assertRaisesMessage(ExecutionError, 'صنف مكرر'):
            _resolve_lines([{'item_id': self.aug.id, 'qty': 3, 'availability_line_id': self.a1.id},
                            {'item_id': self.aug.id, 'qty': 3, 'availability_line_id': self.a2.id}])
        self.assertEqual(len(_resolve_lines([{'item_id': self.aug.id, 'qty': 3}, {'item_id': self.pan.id, 'qty': 1}])), 2)
