"""
Authentication — WebSocket connections (Batch 3, A-4).

apps/notifications/middleware.py validated the handshake token with UntypedToken, so a 7-day
REFRESH token (even a blacklisted one) opened a socket; a disabled account's token still worked;
and config/asgi.py had no Origin check, so a page on another site could open a socket to ours.
"""
import importlib

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework_simplejwt.tokens import RefreshToken

from apps.notifications.middleware import JWTAuthMiddleware
from apps.tests.factories import make_user


def _ws_user(token):
    # The function under database_sync_to_async, called directly: the async wrapper closes the
    # database connection, which a TestCase transaction can't survive.
    return JWTAuthMiddleware.__dict__['_get_user_from_token'].func(JWTAuthMiddleware(None), token)


class WebSocketTokenTests(TestCase):

    def setUp(self):
        self.user, self.profile, _ = make_user('ws_user', role='pharmacist')
        self.refresh = RefreshToken.for_user(self.user)

    def test_access_token_opens_a_socket(self):
        self.assertEqual(_ws_user(str(self.refresh.access_token)).pk, self.user.pk)

    def test_refresh_token_is_refused(self):
        self.assertFalse(_ws_user(str(self.refresh)).is_authenticated, '7-day refresh token accepted')

    def test_disabled_account_is_refused(self):
        access = str(self.refresh.access_token)
        self.profile.is_active = False
        self.profile.save(update_fields=['is_active'])
        self.assertFalse(_ws_user(access).is_authenticated)


@override_settings(ALLOWED_HOSTS=['erp.example'])
class WebSocketOriginTests(TransactionTestCase):

    def setUp(self):
        import config.asgi
        self.app = importlib.reload(config.asgi).application     # built with ALLOWED_HOSTS above
        user, _, _ = make_user('ws_origin', role='pharmacist')
        self.token = str(RefreshToken.for_user(user).access_token)

    def _connects(self, origin):
        async def go():
            c = WebsocketCommunicator(self.app, f'/ws/notifications/?token={self.token}',
                                      headers=[(b'origin', origin.encode())])
            ok, _ = await c.connect()
            await c.disconnect()
            return ok
        return async_to_sync(go)()

    def test_our_own_site_connects(self):
        self.assertTrue(self._connects('https://erp.example'))

    def test_another_site_is_refused(self):
        self.assertFalse(self._connects('https://evil.example'), 'cross-site WebSocket accepted')
