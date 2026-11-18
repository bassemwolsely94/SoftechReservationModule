"""
apps/tests/test_wave2_transfer_send.py — full audit Wave 2, FE-11.

A transfer request is saved and sent in ONE server call (POST /api/transfers/?submit=1). Before, the
screen called create then submit; a refused submit left a draft behind and pressing «حفظ» again made a
second request.
"""
from django.core.management import call_command
from django.test import TestCase

from apps.transfers.models import TransferRequest

from .factories import make_branch, make_branch2, make_item, make_pharmacist

URL = '/api/transfers/'


class TransferSaveAndSendTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_permissions', verbosity=0)

    def setUp(self):
        self.b1 = make_branch()
        self.b2 = make_branch2()
        self.item = make_item()
        _, self.profile, self.c = make_pharmacist('fe11_pharma', branch=self.b1)

    def _payload(self, items=True):
        return {
            'requesting_branch': self.b1.pk, 'supplying_branch': self.b2.pk, 'notes': '',
            'items': [{'item': self.item.pk, 'quantity': '3', 'notes': ''}] if items else [],
        }

    def test_one_call_saves_and_sends(self):
        r = self.c.post(f'{URL}?submit=1', self._payload(), format='json')
        self.assertEqual(r.status_code, 201, r.content[:400])
        self.assertEqual(r.json()['status'], 'pending')
        tr = TransferRequest.objects.get()
        self.assertEqual(tr.status, 'pending')
        self.assertIsNotNone(tr.submitted_at)
        self.assertEqual(tr.items.count(), 1)

    def test_a_refused_send_saves_nothing(self):
        r = self.c.post(f'{URL}?submit=1', self._payload(items=False), format='json')
        self.assertEqual(r.status_code, 400, r.content[:400])
        self.assertIn('detail', r.json())
        self.assertFalse(TransferRequest.objects.exists())   # no orphan draft to duplicate on retry

    def test_retry_after_a_refusal_makes_exactly_one_request(self):
        self.c.post(f'{URL}?submit=1', self._payload(items=False), format='json')
        r = self.c.post(f'{URL}?submit=1', self._payload(), format='json')
        self.assertEqual(r.status_code, 201, r.content[:400])
        self.assertEqual(TransferRequest.objects.count(), 1)

    def test_without_submit_it_is_still_a_draft(self):
        r = self.c.post(URL, self._payload(), format='json')
        self.assertEqual(r.status_code, 201, r.content[:400])
        self.assertEqual(TransferRequest.objects.get().status, 'draft')

    def test_another_branch_cannot_be_the_requester(self):
        payload = self._payload()
        payload['requesting_branch'], payload['supplying_branch'] = self.b2.pk, self.b1.pk
        r = self.c.post(f'{URL}?submit=1', payload, format='json')
        self.assertIn(r.status_code, (400, 403), r.content[:400])
        self.assertFalse(TransferRequest.objects.exists())

    def test_separate_submit_still_works_for_drafts(self):
        tr_id = self.c.post(URL, self._payload(), format='json').json()['id']
        r = self.c.post(f'{URL}{tr_id}/submit/')
        self.assertEqual(r.status_code, 200, r.content[:400])
        self.assertEqual(TransferRequest.objects.get().status, 'pending')
