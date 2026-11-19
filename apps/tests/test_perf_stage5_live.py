"""
Performance Stage 5 — live updates over the existing notification WebSocket
(plan docs/superpowers/plans/2026-11-19-perf-stage5-live-updates.md).

• Bell: every change to a user's unread notifications asks that user's sockets to send fresh
  category counts (after commit); the socket computes them, debounced, and sends integers only.
• Freshness: a finished sync run / lane broadcasts the changed freshness domains to every staff
  socket — domain keys and a time, nothing else.
"""
import json
from unittest import mock

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.notifications import live
from apps.notifications.models import Notification
from apps.sync.models import SyncRun

from .factories import make_branch, make_pharmacist

IN_MEMORY = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}


def _notif(profile, **kw):
    return Notification.objects.create(recipient=profile, notification_type='announcement',
                                       title='إشعار', **kw)


class CountsPushTests(TestCase):
    """Every unread-count change sends one data-free `notification.counts` to the user's group."""

    def setUp(self):
        _, self.prof, _ = make_pharmacist('s5_counts', branch=make_branch())
        self.client = APIClient()
        self.client.force_authenticate(self.prof.user)
        self.group = f'notifications_user_{self.prof.pk}'

    def _pushes(self, fn):
        with mock.patch.object(live, '_group_send') as send, \
                self.captureOnCommitCallbacks(execute=True):
            fn()
        return [c.args for c in send.call_args_list]

    def test_push_waits_for_commit_and_carries_no_data(self):
        with mock.patch.object(live, '_group_send') as send:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                live.request_counts_push(self.prof.pk)
                send.assert_not_called()              # nothing before commit
            for cb in callbacks:
                cb()
            send.assert_called_once_with(self.group, {'type': 'notification.counts'})

    def test_no_profile_no_push(self):
        with mock.patch.object(live, '_group_send') as send, self.captureOnCommitCallbacks(execute=True):
            live.request_counts_push(None)
        send.assert_not_called()

    def test_new_notification_pushes_counts(self):
        pushes = self._pushes(lambda: _notif(self.prof))
        self.assertIn((self.group, {'type': 'notification.counts'}), pushes)

    def test_send_to_user_pushes_counts(self):
        pushes = self._pushes(lambda: Notification.send_to_user(self.prof, 'announcement', 'مرحبا'))
        self.assertIn((self.group, {'type': 'notification.counts'}), pushes)

    def test_rest_read_paths_push_counts(self):
        a, b, c = _notif(self.prof), _notif(self.prof), _notif(self.prof)
        for call in (lambda: self.client.post(f'/api/notifications/{a.pk}/read/'),
                     lambda: self.client.post('/api/notifications/bulk/',
                                              {'ids': [b.pk], 'action': 'read'}, format='json'),
                     lambda: self.client.post(f'/api/notifications/{c.pk}/snooze/',
                                              {'minutes': 15}, format='json'),
                     lambda: self.client.delete(f'/api/notifications/{c.pk}/')):
            pushes = self._pushes(call)
            self.assertIn((self.group, {'type': 'notification.counts'}), pushes, call)

    def test_mark_all_read_pushes_only_when_something_changed(self):
        self.assertEqual(self._pushes(lambda: self.client.post('/api/notifications/mark-all-read/')), [])
        _notif(self.prof)
        pushes = self._pushes(lambda: self.client.post('/api/notifications/mark-all-read/'))
        self.assertEqual(pushes, [(self.group, {'type': 'notification.counts'})])

    def test_rest_counts_route_unchanged(self):
        _notif(self.prof)
        data = self.client.get('/api/notifications/category-counts/').json()
        self.assertEqual(data['global'], 1)
        self.assertEqual(data['bell'], 1)
        self.assertIn('visible', data)


class FreshnessBroadcastTests(TestCase):
    """A finished sync run broadcasts the domains it refreshed to `live_staff`."""

    def _broadcasts(self, fn):
        with mock.patch.object(live, '_group_send') as send, \
                self.captureOnCommitCallbacks(execute=True):
            fn()
        return [c.args for c in send.call_args_list if c.args[0] == live.LIVE_STAFF_GROUP]

    def test_running_row_broadcasts_nothing(self):
        self.assertEqual(self._broadcasts(lambda: SyncRun.objects.create(status='running', lane='fast')), [])

    def test_fast_lane_success_broadcasts_its_domains(self):
        run = SyncRun.objects.create(status='running', lane='fast')

        def finish():
            run.status = 'success'
            run.save()
        sent = self._broadcasts(finish)
        self.assertEqual(len(sent), 1)
        group, msg = sent[0]
        self.assertEqual(msg['type'], 'live.freshness')
        self.assertEqual(msg['domains'], ['branches', 'sales', 'stock'])
        self.assertEqual(set(msg), {'type', 'domains', 'at'})

    def test_failed_run_also_broadcasts(self):
        # a failure changes the bar too («آخر مزامنة فشلت»)
        sent = self._broadcasts(lambda: SyncRun.objects.create(status='failed', lane='slow'))
        self.assertEqual(sent[0][1]['domains'], ['catalog', 'customers', 'users'])

    def test_retention_lane_is_not_data(self):
        self.assertEqual(self._broadcasts(lambda: SyncRun.objects.create(status='success', lane='retention')), [])

    def test_full_and_blank_lanes_cover_every_main_domain(self):
        from apps.sync.live import lane_domains
        main = ['branches', 'catalog', 'customers', 'sales', 'stock', 'users']
        self.assertEqual(lane_domains('full'), main)
        self.assertEqual(lane_domains(''), main)
        self.assertEqual(lane_domains('items'), ['catalog'])

    def test_custom_source_run_broadcasts_its_domain(self):
        from apps.batches.models import StockExpirySyncRun
        run = StockExpirySyncRun.objects.create(triggered_by='s5-test')
        self.assertEqual(self._broadcasts(lambda: None), [])
        sent = self._broadcasts(lambda: run.finish('success'))
        self.assertEqual(sent[0][1]['domains'], ['expiry'])

    def test_every_source_domain_exists(self):
        from apps.sync.freshness import DOMAINS
        from apps.sync.live import SOURCE_MODELS
        for label, domains in SOURCE_MODELS.items():
            for d in domains or ('ar_contracts', 'ap_reconciliation'):
                self.assertIn(d, DOMAINS, label)

    def test_client_frame_is_built_from_known_fields_only(self):
        frame = live.freshness_message({'type': 'live.freshness', 'domains': ['stock', 7],
                                        'at': '2026-11-19T10:00:00+02:00',
                                        'phone': '01011111111', 'customer': 'x'})
        self.assertEqual(frame, {'event': 'freshness_changed', 'domains': ['stock'],
                                 'at': '2026-11-19T10:00:00+02:00'})


@override_settings(CHANNEL_LAYERS=IN_MEMORY)
class LiveSocketTests(TransactionTestCase):
    """(Transactional: the consumer runs its DB work in other threads.)"""

    def setUp(self):
        _, self.prof, _ = make_pharmacist('s5_sock', branch=make_branch())

    def _run(self, body, debounce=0):
        from apps.notifications import consumers
        from apps.notifications.consumers import NotificationConsumer

        async def go():
            comm = WebsocketCommunicator(NotificationConsumer.as_asgi(), '/ws/notifications/')
            comm.scope['user'] = self.prof.user
            connected, _ = await comm.connect()
            self.assertTrue(connected)
            try:
                return await body(comm)
            finally:
                await comm.disconnect()

        async def admit(self_):
            return True

        async def noop(self_):
            return None

        with mock.patch('apps.access.ws.ZoneGuardMixin.zone_admit', admit), \
                mock.patch('apps.access.ws.ZoneGuardMixin.zone_start', noop), \
                mock.patch('apps.access.ws.ZoneGuardMixin.zone_stop', noop), \
                mock.patch.object(consumers, 'COUNTS_DEBOUNCE_SECONDS', debounce):
            return async_to_sync(go)()

    def test_counts_event_sends_integer_counts(self):
        _notif(self.prof)
        _notif(self.prof)

        async def body(comm):
            frame = json.loads(await comm.receive_from())          # the pending notifications
            while frame.get('event') != 'pending_notifications':
                frame = json.loads(await comm.receive_from())
            await get_channel_layer().group_send(f'notifications_user_{self.prof.pk}',
                                                 {'type': 'notification.counts'})
            return json.loads(await comm.receive_from(timeout=3))
        frame = self._run(body)
        self.assertEqual(frame['event'], 'category_counts')
        self.assertEqual(frame['bell'], 2)
        self.assertEqual(frame['global'], 2)
        for key, value in frame.items():
            if key not in ('event', 'visible'):
                self.assertIsInstance(value, int, key)

    def test_burst_of_counts_events_sends_one_frame(self):
        async def body(comm):
            layer = get_channel_layer()
            for _ in range(5):
                await layer.group_send(f'notifications_user_{self.prof.pk}', {'type': 'notification.counts'})
            first = json.loads(await comm.receive_from(timeout=3))
            quiet = await comm.receive_nothing(timeout=0.5)
            return first, quiet
        # the 5 events land inside one debounce window → one frame
        first, quiet = self._run(body, debounce=0.3)
        self.assertEqual(first['event'], 'category_counts')
        self.assertTrue(quiet)

    def test_freshness_reaches_every_staff_socket_without_extra_fields(self):
        async def body(comm):
            await get_channel_layer().group_send(live.LIVE_STAFF_GROUP, {
                'type': 'live.freshness', 'domains': ['stock'], 'at': '2026-11-19T10:00:00+02:00',
                'phone': '01011111111'})
            return json.loads(await comm.receive_from(timeout=3))
        frame = self._run(body)
        self.assertEqual(frame, {'event': 'freshness_changed', 'domains': ['stock'],
                                 'at': '2026-11-19T10:00:00+02:00'})

    def test_disconnect_leaves_the_staff_group(self):
        seen = {}

        async def body(comm):
            layer = get_channel_layer()
            seen['inside'] = bool(layer.groups.get(live.LIVE_STAFF_GROUP))
            return None
        self._run(body)
        self.assertTrue(seen['inside'])
        self.assertFalse(get_channel_layer().groups.get(live.LIVE_STAFF_GROUP))
