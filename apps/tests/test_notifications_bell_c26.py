"""
C26 / D-19 — the bell opens on «يحتاج إجراء» (action items), «الكل» one click away, remembered per user.

Covers:
  - the action-type list itself (one place, real types, no monitoring flood type)
  - ?view=action on the list / unread-count / category-counts (`action` key)
  - role notifier visibility + personal mute still apply to the action view; other users' rows never leak
  - mark-read paths: single (REST + log), bulk, «قراءة الكل» per view, and the websocket «قراءة الكل»
    now scoped like REST (it used to clear quiet feeds + snoozed rows and stamp every log row)
  - the per-user bell_view preference
"""
from datetime import timedelta

from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.notifications.action_items import ACTION_TYPES, ACTION_REASONS, clean_view
from apps.notifications.models import Notification, NotificationLog, RoleNotificationAccess
from .factories import make_branch, make_pharmacist

LIST_URL = '/api/notifications/'
COUNT_URL = '/api/notifications/unread-count/'
COUNTS_URL = '/api/notifications/category-counts/'
MARK_ALL_URL = '/api/notifications/mark-all-read/'
BULK_URL = '/api/notifications/bulk/'
PREFS_URL = '/api/notifications/preferences/'

# one of each shape the bell has to tell apart
ACTION_GLOBAL = 'churn_alert'          # global category, action
ACTION_QUIET = 'mention'               # mentions (quiet feed), action
ACTION_RES = 'stock_available'         # reservations, action
INFO_GLOBAL = 'announcement'           # global category, not an action
INFO_MONITOR = 'transit_critical'      # monitoring flood, not an action


def _notif(profile, ntype, *, is_read=False, snoozed=False, log=True):
    n = Notification.objects.create(recipient=profile, notification_type=ntype, title=ntype,
                                    is_read=is_read)
    if snoozed:
        Notification.objects.filter(pk=n.pk).update(snoozed_until=timezone.now() + timedelta(hours=1))
    if log:
        NotificationLog.objects.create(notification=n, recipient=profile)
    return n


class ActionTypeListTests(TestCase):
    def test_every_action_type_is_a_real_type_with_a_reason(self):
        real = {t for t, _ in Notification.NOTIFICATION_TYPES}
        self.assertTrue(ACTION_TYPES)
        self.assertEqual(ACTION_TYPES - real, set())
        for t in ACTION_TYPES:
            self.assertTrue(ACTION_REASONS[t].strip())

    def test_no_monitoring_feed_type_is_an_action(self):
        # the 📡 feed is the flood (726k rows, PERF-1) — it must never fill the action list
        monitoring = {t for t, c in Notification.TYPE_CATEGORY.items()
                      if c == Notification.CATEGORY_MONITORING}
        self.assertEqual(ACTION_TYPES & monitoring, set())

    def test_unknown_view_falls_back(self):
        self.assertEqual(clean_view('action'), 'action')
        self.assertEqual(clean_view('nonsense'), 'all')
        self.assertEqual(clean_view(None), 'all')


class ActionViewTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        _, self.prof, self.client = make_pharmacist('c26_ph', branch=self.branch)
        self.a_global = _notif(self.prof, ACTION_GLOBAL)
        self.a_quiet = _notif(self.prof, ACTION_QUIET)
        self.i_global = _notif(self.prof, INFO_GLOBAL)
        self.i_monitor = _notif(self.prof, INFO_MONITOR)

    def _ids(self, resp):
        self.assertEqual(resp.status_code, 200)
        return {row['id'] for row in resp.data}

    def test_action_view_lists_action_types_from_every_visible_category(self):
        ids = self._ids(self.client.get(LIST_URL, {'view': 'action'}))
        self.assertEqual(ids, {self.a_global.pk, self.a_quiet.pk})

    def test_all_view_is_todays_bell(self):
        ids = self._ids(self.client.get(LIST_URL))
        self.assertEqual(ids, {self.a_global.pk, self.i_global.pk})   # quiet feeds stay out
        self.assertEqual(ids, self._ids(self.client.get(LIST_URL, {'view': 'all'})))

    def test_rows_carry_is_action(self):
        rows = {r['id']: r for r in self.client.get(LIST_URL).data}
        self.assertTrue(rows[self.a_global.pk]['is_action'])
        self.assertFalse(rows[self.i_global.pk]['is_action'])

    def test_counts(self):
        _notif(self.prof, ACTION_GLOBAL, snoozed=True)   # snoozed rows never count
        _notif(self.prof, ACTION_GLOBAL, is_read=True)
        self.assertEqual(self.client.get(COUNT_URL, {'view': 'action'}).data['count'], 2)
        self.assertEqual(self.client.get(COUNT_URL).data['count'], 2)
        data = self.client.get(COUNTS_URL).data
        self.assertEqual(data['action'], 2)
        self.assertEqual(data['bell'], 2)
        self.assertEqual(data['mentions'], 1)
        self.assertEqual(data['monitoring'], 1)

    def test_other_users_rows_never_appear(self):
        _, other, _ = make_pharmacist('c26_other', branch=self.branch)
        theirs = _notif(other, ACTION_GLOBAL)
        self.assertNotIn(theirs.pk, self._ids(self.client.get(LIST_URL, {'view': 'action'})))
        self.assertEqual(self.client.get(COUNTS_URL).data['action'], 2)

    def test_role_hidden_category_stays_hidden_in_action_view(self):
        RoleNotificationAccess.objects.create(role='pharmacist', category='mentions', is_allowed=False)
        self.assertEqual(self._ids(self.client.get(LIST_URL, {'view': 'action'})), {self.a_global.pk})
        self.assertEqual(self.client.get(COUNTS_URL).data['action'], 1)

    def test_personal_mute_applies_to_action_view(self):
        self.prof.muted_notification_categories = ['global']
        self.prof.save(update_fields=['muted_notification_categories'])
        self.assertEqual(self._ids(self.client.get(LIST_URL, {'view': 'action'})), {self.a_quiet.pk})


class MarkReadPathTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        _, self.prof, self.client = make_pharmacist('c26_mr', branch=self.branch)

    def _read(self, n):
        n.refresh_from_db()
        return n.is_read

    def _logged(self, n):
        return NotificationLog.objects.get(notification=n).read_at is not None

    def test_single_mark_read_writes_row_and_log(self):
        n = _notif(self.prof, ACTION_RES)
        resp = self.client.post(f'/api/notifications/{n.pk}/read/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(self._read(n))
        self.assertTrue(self._logged(n))

    def test_single_mark_read_of_someone_elses_is_404(self):
        _, other, _ = make_pharmacist('c26_mr_other', branch=self.branch)
        n = _notif(other, ACTION_RES)
        self.assertEqual(self.client.post(f'/api/notifications/{n.pk}/read/').status_code, 404)
        self.assertFalse(self._read(n))

    def test_bulk_read_writes_rows_and_logs(self):
        a, b = _notif(self.prof, ACTION_RES), _notif(self.prof, INFO_GLOBAL)
        resp = self.client.post(BULK_URL, {'ids': [a.pk, b.pk], 'action': 'read'}, format='json')
        self.assertEqual(resp.data['updated'], 2)
        self.assertTrue(self._read(a) and self._read(b))
        self.assertTrue(self._logged(a) and self._logged(b))

    def test_mark_all_in_action_view_marks_only_action_items(self):
        act, quiet_act = _notif(self.prof, ACTION_GLOBAL), _notif(self.prof, ACTION_QUIET)
        info, mon = _notif(self.prof, INFO_GLOBAL), _notif(self.prof, INFO_MONITOR)
        resp = self.client.post(MARK_ALL_URL + '?view=action')
        self.assertEqual(resp.data['marked'], 2)
        self.assertTrue(self._read(act) and self._read(quiet_act))
        self.assertFalse(self._read(info) or self._read(mon))
        self.assertTrue(self._logged(act))
        self.assertFalse(self._logged(info) or self._logged(mon))

    def test_mark_all_default_leaves_quiet_feeds_and_their_logs(self):
        info, quiet = _notif(self.prof, INFO_GLOBAL), _notif(self.prof, ACTION_QUIET)
        snoozed = _notif(self.prof, INFO_GLOBAL, snoozed=True)
        self.assertEqual(self.client.post(MARK_ALL_URL).data['marked'], 1)
        self.assertTrue(self._read(info))
        self.assertFalse(self._read(quiet) or self._read(snoozed))
        # before C26 every unread log row of the user was stamped here
        self.assertFalse(self._logged(quiet) or self._logged(snoozed))

    def test_mark_all_on_a_hidden_category_is_refused(self):
        RoleNotificationAccess.objects.create(role='pharmacist', category='mentions', is_allowed=False)
        quiet = _notif(self.prof, ACTION_QUIET)
        self.assertEqual(self.client.post(MARK_ALL_URL + '?category=mentions').status_code, 403)
        self.assertFalse(self._read(quiet))


class BellViewPreferenceTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        _, self.prof, self.client = make_pharmacist('c26_pref', branch=self.branch)

    def test_defaults_to_action(self):
        self.assertEqual(self.client.get(PREFS_URL).data['bell_view'], 'action')

    def test_remembered_per_user(self):
        _, other, other_client = make_pharmacist('c26_pref2', branch=self.branch)
        resp = self.client.patch(PREFS_URL, {'bell_view': 'all'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['bell_view'], 'all')
        self.prof.refresh_from_db()
        self.assertEqual(self.prof.bell_view, 'all')
        self.assertEqual(other_client.get(PREFS_URL).data['bell_view'], 'action')

    def test_unknown_view_refused(self):
        resp = self.client.patch(PREFS_URL, {'bell_view': 'everything'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.prof.refresh_from_db()
        self.assertEqual(self.prof.bell_view, 'action')

    def test_needs_login(self):
        from rest_framework.test import APIClient
        self.assertIn(APIClient().get(PREFS_URL).status_code, (401, 403))


class WebsocketMarkAllReadTests(TransactionTestCase):
    """(Transactional: the consumer closes old DB connections.) The bell's «قراءة الكل» goes over the
    socket when it is up — it must mark exactly what REST marks."""

    def setUp(self):
        self.branch = make_branch()
        _, self.prof, _ = make_pharmacist('c26_ws', branch=self.branch)

    def _mark_all_over_socket(self, view=None):
        import json
        from unittest import mock
        from asgiref.sync import async_to_sync
        from channels.testing import WebsocketCommunicator
        from apps.notifications.consumers import NotificationConsumer

        async def go():
            comm = WebsocketCommunicator(NotificationConsumer.as_asgi(), '/ws/notifications/')
            comm.scope['user'] = self.prof.user
            connected, _ = await comm.connect()
            self.assertTrue(connected)
            payload = {'action': 'mark_all_read'}
            if view:
                payload['view'] = view
            await comm.send_to(text_data=json.dumps(payload))
            reply = json.loads(await comm.receive_from())
            while reply.get('event') != 'all_marked_read':
                reply = json.loads(await comm.receive_from())
            await comm.disconnect()
            return reply

        async def admit(self_):
            return True

        async def noop(self_):
            return None

        with mock.patch('apps.access.ws.ZoneGuardMixin.zone_admit', admit), \
                mock.patch('apps.access.ws.ZoneGuardMixin.zone_start', noop), \
                mock.patch('apps.access.ws.ZoneGuardMixin.zone_stop', noop):
            return async_to_sync(go)()

    def _read(self, n):
        n.refresh_from_db()
        return n.is_read

    def test_ws_mark_all_leaves_quiet_feeds_and_snoozed(self):
        info = _notif(self.prof, INFO_GLOBAL)
        quiet, mon = _notif(self.prof, ACTION_QUIET), _notif(self.prof, INFO_MONITOR)
        snoozed = _notif(self.prof, INFO_GLOBAL, snoozed=True)
        reply = self._mark_all_over_socket()
        self.assertEqual(reply['count'], 1)
        self.assertTrue(self._read(info))
        self.assertFalse(self._read(quiet) or self._read(mon) or self._read(snoozed))
        self.assertIsNone(NotificationLog.objects.get(notification=quiet).read_at)

    def test_ws_mark_all_in_action_view(self):
        act, quiet_act = _notif(self.prof, ACTION_GLOBAL), _notif(self.prof, ACTION_QUIET)
        info = _notif(self.prof, INFO_GLOBAL)
        reply = self._mark_all_over_socket('action')
        self.assertEqual(reply['count'], 2)
        self.assertTrue(self._read(act) and self._read(quiet_act))
        self.assertFalse(self._read(info))
