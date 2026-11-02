"""
Platform & abuse — the live chatter socket (Batch 6, W-3).

Before: `/ws/chatter/<model>/<id>/` let any logged-in user join any record's thread — any model
name, any branch — and `post` to it with no model allow-list, branch check or length cap (the REST
endpoints have all three). A branch user could listen to another branch's record threads, signed
attachment links included, and write into them.

Now: joining and posting follow the REST rules — the chattable-model list, the record's branch
through `core.branch_scope` (all-branch roles see every branch), and the 2,000-character cap.
"""
import importlib

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.test import TestCase, TransactionTestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.notifications.models import ChatterMessage
from apps.reservations.models import Reservation
from apps.tests.factories import make_admin, make_branch, make_branch2, make_item, make_pharmacist



def _reservation(branch, by):
    return Reservation.objects.create(item=make_item(), branch=branch, quantity_requested=1,
                                      contact_name='عميل', contact_phone='01011111111', created_by=by)


class ChatterAccessRuleTests(TestCase):

    def setUp(self):
        self.a, self.b = make_branch(), make_branch2()
        self.user_a, self.prof_a, _ = make_pharmacist('w3_a', branch=self.a)
        self.user_b, self.prof_b, _ = make_pharmacist('w3_b', branch=self.b)
        self.res = _reservation(self.a, self.prof_a)

    def _can(self, user, model, rid):
        from apps.notifications.chatter_access import can_use_thread
        return can_use_thread(user, model, rid)

    def test_another_branch_cannot_use_a_records_thread(self):
        self.assertFalse(self._can(self.user_b, 'reservation', self.res.pk))
        self.assertTrue(self._can(self.user_a, 'reservation', self.res.pk))

    def test_only_chattable_models(self):
        self.assertFalse(self._can(self.user_a, 'staffprofile', self.prof_a.pk))

    def test_all_branch_roles_see_every_branch(self):
        admin, _, _ = make_admin('w3_admin')
        self.assertTrue(self._can(admin, 'reservation', self.res.pk))


class ChatterSocketTests(TransactionTestCase):

    def setUp(self):
        import config.asgi
        self.app = importlib.reload(config.asgi).application
        self.a, self.b = make_branch(), make_branch2()
        _, self.prof_a, _ = make_pharmacist('w3s_a', branch=self.a)
        self.user_b, _, _ = make_pharmacist('w3s_b', branch=self.b)
        self.user_a = self.prof_a.user
        self.res = _reservation(self.a, self.prof_a)

    def _socket(self, user, model, rid, send=None):
        token = str(RefreshToken.for_user(user).access_token)

        async def go():
            c = WebsocketCommunicator(self.app, f'/ws/chatter/{model}/{rid}/?token={token}',
                                      headers=[(b'origin', b'http://localhost')])
            ok, _ = await c.connect()
            if ok and send is not None:
                await c.send_json_to(send)
                await c.receive_nothing(timeout=0.5)
            await c.disconnect()
            return ok
        return async_to_sync(go)()

    def test_another_branch_is_refused_and_writes_nothing(self):
        self.assertFalse(self._socket(self.user_b, 'reservation', self.res.pk,
                                      send={'action': 'post', 'message': 'x'}))
        self.assertFalse(ChatterMessage.objects.exists())

    def test_an_over_long_message_is_not_stored(self):
        self.assertTrue(self._socket(self.user_a, 'reservation', self.res.pk,
                                     send={'action': 'post', 'message': 'x' * 2001}))
        self.assertFalse(ChatterMessage.objects.exists())
