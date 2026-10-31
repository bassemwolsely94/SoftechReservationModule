"""
config/asgi.py

ASGI entrypoint for the ElRezeiky platform.

Handles:
  - HTTP  → standard Django ASGI application
  - WebSocket → Django Channels with JWT authentication

WebSocket URLs:
  /ws/notifications/                     → NotificationConsumer
  /ws/chatter/{model_name}/{record_id}/  → ChatterConsumer
"""
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Must import after setting env var
import django
django.setup()

from config.writers import run_startup_checks  # noqa: E402
run_startup_checks()     # P-54: refuse to serve on a duplicated .env key or a contradictory role

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from apps.notifications.middleware import JWTAuthMiddlewareStack
from apps.notifications.routing import websocket_urlpatterns

application = ProtocolTypeRouter({
    'http': get_asgi_application(),
    # Origin must be one of ALLOWED_HOSTS: the access cookie travels with the handshake, so
    # without this a page on another site could open a socket as the logged-in user (A-4).
    'websocket': AllowedHostsOriginValidator(JWTAuthMiddlewareStack(
        URLRouter(websocket_urlpatterns)
    )),
})
