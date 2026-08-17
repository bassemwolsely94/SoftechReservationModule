"""
apps/omni/providers/meta_cloud.py

Meta WhatsApp Business Cloud API provider — extracted from the HTTP core of
apps/whatsapp/sender.py (which now delegates here).

Credential resolution per account:
  1. account.get_credentials() → {'token', 'phone_number_id', 'api_version'?}
  2. env fallback (WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID) — used by the
     legacy default account and by account=None callers.
"""
import logging

import requests
from django.conf import settings

from apps.omni.providers.base import BaseProvider, ProviderError

logger = logging.getLogger('elrezeiky.omni')

_API_BASE = 'https://graph.facebook.com'


class MetaCloudProvider(BaseProvider):

    def __init__(self, account=None):
        super().__init__(account)
        creds = account.get_credentials() if account is not None else {}
        self.token    = creds.get('token') or getattr(settings, 'WHATSAPP_TOKEN', '')
        self.phone_id = (
            creds.get('phone_number_id')
            or (account.provider_ref if account is not None else '')
            or getattr(settings, 'WHATSAPP_PHONE_NUMBER_ID', '')
        )
        self.version  = creds.get('api_version') or getattr(settings, 'WHATSAPP_API_VERSION', 'v19.0')

    @property
    def configured(self) -> bool:
        return bool(self.token and self.phone_id)

    def send_message(self, payload: dict) -> dict:
        if not self.configured:
            who = f'الحساب #{self.account.pk}' if self.account else 'الحساب الافتراضي'
            raise ProviderError(
                f'واتساب غير مهيأ لـ {who} — أضف token و phone_number_id '
                '(بيانات الحساب أو WHATSAPP_TOKEN/WHATSAPP_PHONE_NUMBER_ID في env)'
            )
        resp = requests.post(
            f'{_API_BASE}/{self.version}/{self.phone_id}/messages',
            json=payload,
            headers={
                'Authorization': f'Bearer {self.token}',
                'Content-Type': 'application/json',
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def health(self) -> dict:
        """GET the phone-number object from the Graph API (never raises)."""
        if not self.configured:
            return {'ok': False, 'detail': 'unconfigured'}
        try:
            resp = requests.get(
                f'{_API_BASE}/{self.version}/{self.phone_id}',
                params={'fields': 'display_phone_number,quality_rating,verified_name'},
                headers={'Authorization': f'Bearer {self.token}'},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    'ok': True,
                    'display_phone_number': data.get('display_phone_number', ''),
                    'quality_rating': data.get('quality_rating', ''),
                    'verified_name': data.get('verified_name', ''),
                }
            return {'ok': False, 'detail': f'HTTP {resp.status_code}: {resp.text[:200]}'}
        except Exception as exc:
            return {'ok': False, 'detail': str(exc)}
