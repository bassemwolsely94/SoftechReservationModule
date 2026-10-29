"""
SOFTECH write safety — market-shortage decisions (Batch 2, P-2).

POST /api/purchasing/shortage/{flag,unflag,dismiss,retrieve}/ change the SOFTECH item
master for the whole chain (shortage flag + warning; on_request / obsolete dismissals
suspend ordering — itemnomoreuse). Before P-2 any logged-in user could call them.
They now need the matrix grant shortage/approve — admin, pharmacist, purchasing,
supervisor in the code matrix: exactly the roles that act on the «نواقص السوق» screen.
"""
from unittest import mock

from django.test import TestCase

from apps.tests.factories import make_item

from .fixtures import role_clients, seed_code_matrix

ENDPOINTS = {
    'flag':     lambda item: {'item_id': item.id, 'source': 'auto'},
    'unflag':   lambda item: {'item_id': item.id},
    'dismiss':  lambda item: {'item_id': item.id, 'reason': 'obsolete'},
    'retrieve': lambda item: {'item_id': item.id},
}
ALLOWED = ('admin', 'pharmacist', 'purchasing', 'supervisor')
REFUSED = ('viewer', 'delivery', 'call_center', 'salesperson', 'quality_manager')


class ShortageWritePermissionTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed_code_matrix()
        cls.clients = role_clients()

    def setUp(self):
        self.item = make_item(softech_id='SH001')
        self.push = mock.patch('apps.purchasing.shortage_writer.push_item', return_value=True)
        self.pushed = self.push.start()
        self.addCleanup(self.push.stop)

    def test_unauthorised_roles_cannot_touch_softech_items(self):
        for role in REFUSED:
            for name, body in ENDPOINTS.items():
                r = self.clients[role].post(f'/api/purchasing/shortage/{name}/', body(self.item),
                                            format='json')
                self.assertEqual(r.status_code, 403, f'{role} {name}')
        self.pushed.assert_not_called()
        self.item.refresh_from_db()
        self.assertFalse(self.item.in_shortage)
        self.assertFalse(self.item.shortage_dismissed)

    def test_screen_roles_still_work(self):
        for role in ALLOWED:
            for name, body in ENDPOINTS.items():
                r = self.clients[role].post(f'/api/purchasing/shortage/{name}/', body(self.item),
                                            format='json')
                self.assertEqual(r.status_code, 200, f'{role} {name}: {r.content[:120]}')
