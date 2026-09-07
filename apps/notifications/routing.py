"""
apps/notifications/routing.py

WebSocket URL patterns for the notification system.

  /ws/notifications/                       → NotificationConsumer
  /ws/chatter/{model_name}/{record_id}/    → ChatterConsumer

Both require ?token=<jwt> appended to the URL.
"""
from django.urls import re_path
from . import consumers
from apps.pbx.consumers import AgentCallConsumer

websocket_urlpatterns = [
    re_path(
        r'^ws/notifications/$',
        consumers.NotificationConsumer.as_asgi(),
        name='ws-notifications',
    ),
    re_path(
        r'^ws/chatter/(?P<model_name>[a-z_]+)/(?P<record_id>\d+)/$',
        consumers.ChatterConsumer.as_asgi(),
        name='ws-chatter',
    ),
    re_path(
        r'^ws/pbx/agent/$',
        AgentCallConsumer.as_asgi(),
        name='ws-pbx-agent',
    ),
]
