"""
apps/omni/providers/stubs.py

Placeholders for providers that are architecturally supported but not yet
contracted. Each raises ProviderError with a clear message so an account
misconfigured to one of these fails loudly rather than silently.

- 360dialog / Twilio: BSP alternatives to direct Meta Cloud API (Phase 1+
  business decision; 360dialog speaks the same Cloud message format).
- Android bridge: connecting the existing branch phones through an
  unofficial WhatsApp-web bridge VIOLATES WhatsApp ToS (doc 15 §3) —
  deliberately unimplemented; migration path is official Cloud API numbers.
"""
from apps.omni.providers.base import BaseProvider, ProviderError


class Dialog360Provider(BaseProvider):
    def send_message(self, payload: dict) -> dict:
        raise ProviderError('مزوّد 360dialog غير مفعّل بعد — يتطلب عقد BSP')


class TwilioProvider(BaseProvider):
    def send_message(self, payload: dict) -> dict:
        raise ProviderError('مزوّد Twilio غير مفعّل بعد — يتطلب حساب Twilio WhatsApp')


class AndroidBridgeProvider(BaseProvider):
    def send_message(self, payload: dict) -> dict:
        raise ProviderError(
            'جسر الأندرويد غير مدعوم — يخالف شروط استخدام واتساب. '
            'رحّل الرقم إلى Cloud API رسمي (انظر doc 15 §3)'
        )
