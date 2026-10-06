"""
apps/omni/providers/meta_graph.py

Meta Graph Send API provider — Facebook Messenger + Instagram DM.
One provider serves both (same endpoint; the page access token determines
the surface). Credentials: {'token': '<page access token>'}.
"""
import logging

import requests
from django.conf import settings

from apps.omni.providers.base import BaseProvider, ProviderError

logger = logging.getLogger('elrezeiky.omni')

_API_BASE = 'https://graph.facebook.com'


class MetaGraphProvider(BaseProvider):

    def __init__(self, account=None):
        super().__init__(account)
        creds = account.get_credentials() if account is not None else {}
        self.token   = creds.get('token', '')
        self.version = creds.get('api_version') or getattr(settings, 'WHATSAPP_API_VERSION', 'v19.0')

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def send_message(self, payload: dict) -> dict:
        if not self.token:
            who = f'الحساب #{self.account.pk}' if self.account else 'الحساب'
            raise ProviderError(f'صفحة Meta غير مهيأة لـ {who} — أضف page access token')
        resp = requests.post(
            f'{_API_BASE}/{self.version}/me/messages',
            params={'access_token': self.token},
            json=payload,
            timeout=10,
        )
        if resp.status_code >= 400:
            raise ProviderError(f'Meta Graph رفض الإرسال: {resp.text[:300]}')
        return resp.json()

    def health(self) -> dict:
        if not self.token:
            return {'ok': False, 'detail': 'unconfigured'}
        try:
            resp = requests.get(
                f'{_API_BASE}/{self.version}/me',
                params={'access_token': self.token, 'fields': 'id,name'},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                return {'ok': True, 'page_id': data.get('id', ''), 'name': data.get('name', '')}
            return {'ok': False, 'detail': f'HTTP {resp.status_code}: {resp.text[:200]}'}
        except Exception as exc:
            return {'ok': False, 'detail': str(exc)}
