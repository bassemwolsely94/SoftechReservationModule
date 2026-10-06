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

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from apps.notifications.middleware import JWTAuthMiddlewareStack
from apps.notifications.routing import websocket_urlpatterns

application = ProtocolTypeRouter({
    'http': get_asgi_application(),
    'websocket': JWTAuthMiddlewareStack(
        URLRouter(websocket_urlpatterns)
    ),
})
