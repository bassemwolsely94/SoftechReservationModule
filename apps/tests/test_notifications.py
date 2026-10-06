"""
apps/tests/test_notifications.py

Tests covering:
  - Notification list: user sees only own notifications (ownership isolation)
  - Unread count
  - Mark single / all read
  - Delete single notification
  - Clear all
  - Delete old (read > 30 days)
  - Notification preferences: GET + PATCH
  - Deduplication: identical key within 5 minutes suppresses second create
  - send_to_user: suppressed when enable_notifications=False
  - Chatter: list — Gap-4 FIXED: branch-scoped (cross-branch → 403)
  - Chatter: post valid message
  - Chatter: post empty message → 400
  - Chatter: invalid model_name → 400
  - Chatter: message too long → 400
  - Chatter: all endpoints require auth
"""
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from rest_framework import status

from apps.notifications.models import Notification, NotificationLog, ChatterMessage
from .factories import make_branch, make_branch2, make_admin, make_pharmacist, make_user

NOTIF_URL       = '/api/notifications/'
UNREAD_URL      = '/api/notifications/unread-count/'
MARK_ALL_URL    = '/api/notifications/mark-all-read/'
DELETE_OLD_URL  = '/api/notifications/delete-old/'
CLEAR_ALL_URL   = '/api/notifications/clear-all/'
PREFS_URL       = '/api/notifications/preferences/'


def _read_url(pk):
    return f'/api/notifications/{pk}/read/'


def _delete_url(pk):
    return f'/api/notifications/{pk}/'


def _chatter_list_url(model, record_id):
    return f'/api/notifications/chatter/{model}/{record_id}/'


def _chatter_post_url(model, record_id):
    return f'/api/notifications/chatter/{model}/{record_id}/post/'


def _make_notif(profile, title='إشعار', is_read=False, dedup_key='', days_ago=0):
    # 'announcement' maps to CATEGORY_GLOBAL, which is visible in the default bell.
    # ('system' → CATEGORY_SETTINGS, a module feed excluded from the bell list.)
    n = Notification.objects.create(
        recipient=profile,
        notification_type='announcement',
        title=title,
        body='',
        is_read=is_read,
        dedup_key=dedup_key,
    )
    if days_ago:
        Notification.objects.filter(pk=n.pk).update(
            created_at=timezone.now() - timedelta(days=days_ago)
        )
        n.refresh_from_db()
    return n


class NotificationListTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        _, self.prof1, self.client1 = make_pharmacist('notif_user1', branch=self.branch)
        _, self.prof2, self.client2 = make_pharmacist('notif_user2', branch=self.branch)
        self.n1 = _make_notif(self.prof1, 'للمستخدم الأول')
        self.n2 = _make_notif(self.prof2, 'للمستخدم الثاني')

    def test_list_requires_auth(self):
        r = APIClient().get(NOTIF_URL)
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_user_sees_only_own_notifications(self):
        r = self.client1.get(NOTIF_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        ids = [n['id'] for n in r.data]
        self.assertIn(self.n1.id, ids)
        self.assertNotIn(self.n2.id, ids,
                         'SECURITY: User must not see another user\'s notifications')

    def test_unread_only_filter(self):
        _make_notif(self.prof1, 'مقروء', is_read=True)
        r = self.client1.get(NOTIF_URL + '?unread_only=true')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        for n in r.data:
            self.assertFalse(n['is_read'], 'unread_only=true must not return read notifications')

    def test_search_filter(self):
        _make_notif(self.prof1, 'مخزون متاح')
        _make_notif(self.prof1, 'تقرير أسبوعي')
        r = self.client1.get(NOTIF_URL + '?search=مخزون')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        for n in r.data:
            self.assertIn('مخزون', n['title'])

    def test_limit_param(self):
        for i in range(10):
            _make_notif(self.prof1, f'إشعار {i}')
        r = self.client1.get(NOTIF_URL + '?limit=3')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertLessEqual(len(r.data), 3)


class UnreadCountTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        _, self.profile, self.client = make_pharmacist('notif_count', branch=self.branch)

    def test_unread_count_requires_auth(self):
        r = APIClient().get(UNREAD_URL)
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unread_count_correct(self):
        _make_notif(self.profile, 'غير مقروء 1')
        _make_notif(self.profile, 'غير مقروء 2')
        _make_notif(self.profile, 'مقروء', is_read=True)
        r = self.client.get(UNREAD_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['count'], 2)


class MarkReadTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        _, self.prof1, self.client1 = make_pharmacist('notif_mark1', branch=self.branch)
        _, self.prof2, self.client2 = make_pharmacist('notif_mark2', branch=self.branch)

    def test_mark_single_read(self):
        n = _make_notif(self.prof1)
        r = self.client1.post(_read_url(n.id))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        n.refresh_from_db()
        self.assertTrue(n.is_read)

    def test_mark_read_requires_auth(self):
        n = _make_notif(self.prof1)
        r = APIClient().post(_read_url(n.id))
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_mark_other_user_notification_returns_404(self):
        """User cannot mark another user's notification as read."""
        n = _make_notif(self.prof2)
        r = self.client1.post(_read_url(n.id))
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND,
                         'SECURITY: Must not be able to mark another user\'s notification as read')

    def test_mark_all_read(self):
        for _ in range(3):
            _make_notif(self.prof1)
        r = self.client1.post(MARK_ALL_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['marked'], 3)
        self.assertFalse(
            Notification.objects.filter(recipient=self.prof1, is_read=False).exists()
        )

    def test_mark_all_read_requires_auth(self):
        r = APIClient().post(MARK_ALL_URL)
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)


class DeleteNotificationTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        _, self.prof1, self.client1 = make_pharmacist('notif_del1', branch=self.branch)
        _, self.prof2, self.client2 = make_pharmacist('notif_del2', branch=self.branch)

    def test_delete_own_notification(self):
        n = _make_notif(self.prof1)
        r = self.client1.delete(_delete_url(n.id))
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Notification.objects.filter(pk=n.id).exists())

    def test_delete_requires_auth(self):
        n = _make_notif(self.prof1)
        r = APIClient().delete(_delete_url(n.id))
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_delete_other_user_notification_returns_404(self):
        """User cannot delete another user's notification."""
        n = _make_notif(self.prof2)
        r = self.client1.delete(_delete_url(n.id))
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND,
                         'SECURITY: Must not be able to delete another user\'s notification')

    def test_clear_all_only_deletes_own(self):
        _make_notif(self.prof1, 'للمستخدم 1')
        _make_notif(self.prof2, 'للمستخدم 2')
        r = self.client1.delete(CLEAR_ALL_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['deleted'], 1)
        self.assertTrue(Notification.objects.filter(recipient=self.prof2).exists(),
                        'clear-all must not delete other users\' notifications')

    def test_delete_old_only_removes_read_older_than_30_days(self):
        old_read   = _make_notif(self.prof1, 'قديم مقروء',   is_read=True,  days_ago=31)
        old_unread = _make_notif(self.prof1, 'قديم غير مقروء', is_read=False, days_ago=31)
        recent     = _make_notif(self.prof1, 'حديث مقروء',   is_read=True,  days_ago=5)

        r = self.client1.delete(DELETE_OLD_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['deleted'], 1)
        self.assertFalse(Notification.objects.filter(pk=old_read.id).exists())
        self.assertTrue(Notification.objects.filter(pk=old_unread.id).exists(),
                        'delete-old must not remove unread notifications')
        self.assertTrue(Notification.objects.filter(pk=recent.id).exists(),
                        'delete-old must not remove recent notifications')


class NotificationPreferencesTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        _, self.profile, self.client = make_pharmacist('notif_prefs', branch=self.branch)

    def test_get_preferences_requires_auth(self):
        r = APIClient().get(PREFS_URL)
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_preferences_returns_fields(self):
        r = self.client.get(PREFS_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn('enable_notifications', r.data)
        self.assertIn('enable_sound', r.data)

    def test_patch_preferences(self):
        r = self.client.patch(PREFS_URL, {'enable_sound': False}, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertFalse(r.data['enable_sound'])
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.enable_sound)

    def test_patch_unknown_field_ignored(self):
        """Unknown fields in PATCH body must be silently ignored, not raise 500."""
        r = self.client.patch(PREFS_URL, {'evil_field': True}, format='json')
        self.assertIn(r.status_code, [status.HTTP_200_OK])


class NotificationDeduplicationTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        _, self.profile, _ = make_pharmacist('notif_dedup', branch=self.branch)

    def test_duplicate_within_window_suppressed(self):
        key = 'test_dedup_key_xyz'
        n1 = Notification.send_to_user(
            self.profile, 'system', 'إشعار أول', dedup_key=key
        )
        n2 = Notification.send_to_user(
            self.profile, 'system', 'إشعار ثانٍ (مكرر)', dedup_key=key
        )
        self.assertIsNotNone(n1)
        self.assertIsNone(n2, 'Duplicate notification within 5-min window must be suppressed')

    def test_no_dedup_key_not_suppressed(self):
        n1 = Notification.send_to_user(self.profile, 'system', 'إشعار 1')
        n2 = Notification.send_to_user(self.profile, 'system', 'إشعار 2')
        self.assertIsNotNone(n1)
        self.assertIsNotNone(n2, 'Notifications without dedup_key should never be suppressed')

    def test_suppressed_when_enable_notifications_false(self):
        self.profile.enable_notifications = False
        self.profile.save(update_fields=['enable_notifications'])
        n = Notification.send_to_user(self.profile, 'system', 'محجوب')
        self.assertIsNone(n, 'Notification must be suppressed when enable_notifications=False')


class ChatterListTests(TestCase):

    def setUp(self):
        from apps.reservations.models import Reservation
        from .factories import make_item

        self.branch1 = make_branch('فرع 1', 'B01')
        self.branch2 = make_branch2('فرع 2', 'B02')
        _, self.prof1, self.client1 = make_pharmacist('chatter_user1', branch=self.branch1)
        _, self.prof2, self.client2 = make_pharmacist('chatter_user2', branch=self.branch2)
        _, _, self.admin_client     = make_admin('chatter_admin')

        # Create a real Reservation at branch1 so the dispatch lookup has data.
        # Gap-4 fix: the view now looks up the reservation's branch_id to scope access.
        item = make_item()
        self.res = Reservation.objects.create(
            item=item, branch=self.branch1,
            quantity_requested=1, contact_name='عميل اختبار',
            contact_phone='01011111111', created_by=self.prof1,
        )

        # Post a message on that reservation (using its real PK)
        ChatterMessage.objects.create(
            model_name='reservation',
            record_id=self.res.id,
            author=self.prof1,
            message='ملاحظة من الفرع 1',
        )

    def test_chatter_list_requires_auth(self):
        r = APIClient().get(_chatter_list_url('reservation', self.res.id))
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_chatter_list_returns_messages_for_own_branch(self):
        """Branch1 pharmacist can read chatter on branch1's reservation."""
        r = self.client1.get(_chatter_list_url('reservation', self.res.id))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertGreater(len(r.data), 0)

    def test_chatter_cross_branch_access_forbidden(self):
        """Gap-4 FIXED: pharmacist from branch2 cannot read chatter on branch1's reservation."""
        r = self.client2.get(_chatter_list_url('reservation', self.res.id))
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN,
                         'Branch-scoped staff must receive 403 for cross-branch chatter access')

    def test_admin_can_read_any_branch_chatter(self):
        """Admin bypass: admins in _CHATTER_BYPASS_ROLES see all branches."""
        r = self.admin_client.get(_chatter_list_url('reservation', self.res.id))
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_chatter_since_id_filter(self):
        """?since_id filters to messages newer than that id."""
        m1 = ChatterMessage.objects.create(
            model_name='reservation', record_id=self.res.id,
            author=self.prof1, message='رسالة قديمة',
        )
        m2 = ChatterMessage.objects.create(
            model_name='reservation', record_id=self.res.id,
            author=self.prof1, message='رسالة جديدة',
        )
        r = self.client1.get(
            f'{_chatter_list_url("reservation", self.res.id)}?since_id={m1.id}'
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        ids = [msg['id'] for msg in r.data]
        self.assertNotIn(m1.id, ids)
        self.assertIn(m2.id, ids)


class ChatterPostTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        _, self.profile, self.client = make_pharmacist('chatter_poster', branch=self.branch)

    def test_post_message_success(self):
        r = self.client.post(
            _chatter_post_url('reservation', 42),
            {'message': 'رسالة تجريبية'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertIn('message', r.data)

    def test_post_requires_auth(self):
        r = APIClient().post(
            _chatter_post_url('reservation', 42),
            {'message': 'test'},
        )
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_post_empty_message_rejected(self):
        r = self.client.post(
            _chatter_post_url('reservation', 42),
            {'message': ''},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_post_message_too_long_rejected(self):
        r = self.client.post(
            _chatter_post_url('reservation', 42),
            {'message': 'x' * 2001},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_post_invalid_model_name_rejected(self):
        """Model name not in allowed list must return 400."""
        r = self.client.post(
            _chatter_post_url('evil_model', 42),
            {'message': 'رسالة'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_post_nonexistent_record_id_allowed(self):
        """The chatter endpoint does NOT enforce record existence —
        it just stores the (model_name, record_id) pair. Posting to a
        non-existent record_id with a valid message must succeed (201)."""
        r = self.client.post(
            _chatter_post_url('reservation', 999999),
            {'message': 'رسالة على سجل غير موجود'},
            format='json',
        )
        # Chatter does not validate that the record exists
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_message_persisted_correctly(self):
        r = self.client.post(
            _chatter_post_url('transfer', 77),
            {'message': 'تحقق من الطلب'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        msg = ChatterMessage.objects.get(pk=r.data['id'])
        self.assertEqual(msg.model_name, 'transfer')
        self.assertEqual(msg.record_id, 77)
        self.assertEqual(msg.author, self.profile)

    # ── voice_note (TD-H001 parity) ───────────────────────────────────────────

    def test_post_voice_note_only(self):
        """A message with only a voice note (no text) is accepted and stored in
        the dedicated voice_note field."""
        voice = SimpleUploadedFile('note.webm', b'\x00\x01voicebytes', content_type='audio/webm')
        r = self.client.post(
            _chatter_post_url('reservation', 42),
            {'voice_note': voice},
            format='multipart',
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        msg = ChatterMessage.objects.get(pk=r.data['id'])
        self.assertTrue(msg.voice_note)
        self.assertFalse(msg.attachment)
        self.assertIsNotNone(r.data.get('voice_note_url'))

    def test_post_image_and_voice_together(self):
        """Image attachment and voice note ride the same message (parity with
        reservation/transfer chatter)."""
        image = SimpleUploadedFile('photo.png', b'\x89PNGfakedata', content_type='image/png')
        voice = SimpleUploadedFile('note.webm', b'\x00voicebytes', content_type='audio/webm')
        r = self.client.post(
            _chatter_post_url('reservation', 42),
            {'message': 'صورة وصوت', 'attachment': image, 'voice_note': voice},
            format='multipart',
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        msg = ChatterMessage.objects.get(pk=r.data['id'])
        self.assertTrue(msg.attachment)
        self.assertTrue(msg.voice_note)
        self.assertEqual(msg.file_type, 'image')

    def test_post_non_audio_voice_note_rejected(self):
        """The voice_note field only accepts audio — an image there is rejected."""
        not_audio = SimpleUploadedFile('photo.png', b'\x89PNGfakedata', content_type='image/png')
        r = self.client.post(
            _chatter_post_url('reservation', 42),
            {'voice_note': not_audio},
            format='multipart',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
