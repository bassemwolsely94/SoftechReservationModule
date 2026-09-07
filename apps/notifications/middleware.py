"""
apps/notifications/middleware.py

JWT authentication middleware for Django Channels WebSocket connections.

Usage — attach in asgi.py:
    from apps.notifications.middleware import JWTAuthMiddlewareStack
    application = ProtocolTypeRouter({
        'http':      get_asgi_application(),
        'websocket': JWTAuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
    })

How it works:
  1. Reads ?token=<jwt> from the WebSocket query string
  2. Validates the token using SimpleJWT's UntypedToken
  3. Resolves the Django User and injects it into scope['user']
  4. Falls back to AnonymousUser on any failure — consumers must check is_authenticated
"""
import logging
from urllib.parse import parse_qs

from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser

logger = logging.getLogger('elrezeiky.notifications')


class JWTAuthMiddleware(BaseMiddleware):
    """
    Async ASGI middleware that extracts ?token=<jwt> from the WebSocket
    handshake URL and populates scope['user'] with the resolved Django User.
    """

    async def __call__(self, scope, receive, send):
        # Only process WebSocket connections
        if scope['type'] == 'websocket':
            scope['user'] = await self._authenticate(scope)
        return await super().__call__(scope, receive, send)

    async def _authenticate(self, scope):
        query_string = scope.get('query_string', b'')
        if isinstance(query_string, bytes):
            query_string = query_string.decode('utf-8', errors='replace')
        params = parse_qs(query_string)
        token_list = params.get('token', [])
        if not token_list:
            return AnonymousUser()
        token = token_list[0]
        return await self._get_user_from_token(token)

    @database_sync_to_async
    def _get_user_from_token(self, token: str):
        try:
            from rest_framework_simplejwt.tokens import UntypedToken
            from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
            from rest_framework_simplejwt.settings import api_settings
            from django.contrib.auth import get_user_model

            User = get_user_model()

            # Validate the token — raises on invalid/expired
            UntypedToken(token)

            # Decode without re-validating (already validated above)
            import jwt as pyjwt
            decoded = pyjwt.decode(
                token,
                options={'verify_signature': False},
                algorithms=['HS256'],
            )
            user_id = decoded.get(api_settings.USER_ID_CLAIM)
            if not user_id:
                return AnonymousUser()
            user = User.objects.get(**{api_settings.USER_ID_FIELD: user_id})
            return user

        except Exception as exc:
            logger.debug('WS JWT auth failed: %s', exc)
            return AnonymousUser()


def JWTAuthMiddlewareStack(inner):
    """
    Convenience wrapper — wraps with JWTAuthMiddleware then AuthMiddlewareStack
    so session-based auth also works as a fallback.
    """
    return JWTAuthMiddleware(AuthMiddlewareStack(inner))
