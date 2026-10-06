"""
apps/omni/providers/telegram_bot.py

Telegram Bot API provider. Credentials: {'token': '<bot token>',
'webhook_secret': '<secret sent back by Telegram in webhook headers>'}.
"""
import logging

import requests

from apps.omni.providers.base import BaseProvider, ProviderError

logger = logging.getLogger('elrezeiky.omni')

_API_BASE = 'https://api.telegram.org'


class TelegramBotProvider(BaseProvider):

    def __init__(self, account=None):
        super().__init__(account)
        creds = account.get_credentials() if account is not None else {}
        self.token = creds.get('token', '')

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def send_message(self, payload: dict) -> dict:
        if not self.token:
            who = f'الحساب #{self.account.pk}' if self.account else 'الحساب'
            raise ProviderError(f'بوت تيليجرام غير مهيأ لـ {who} — أضف bot token')
        resp = requests.post(
            f'{_API_BASE}/bot{self.token}/sendMessage',
            json=payload,
            timeout=10,
        )
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400 or not data.get('ok', False):
            raise ProviderError(f"تيليجرام رفض الإرسال: {data.get('description', resp.text[:200])}")
        return data

    def health(self) -> dict:
        if not self.token:
            return {'ok': False, 'detail': 'unconfigured'}
        try:
            resp = requests.get(f'{_API_BASE}/bot{self.token}/getMe', timeout=10)
            data = resp.json() if resp.content else {}
            if data.get('ok'):
                bot = data.get('result', {})
                return {'ok': True, 'username': bot.get('username', ''),
                        'name': bot.get('first_name', '')}
            return {'ok': False, 'detail': data.get('description', f'HTTP {resp.status_code}')}
        except Exception as exc:
            return {'ok': False, 'detail': str(exc)}
