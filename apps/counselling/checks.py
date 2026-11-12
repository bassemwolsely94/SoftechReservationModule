"""Deploy check: the opt-out hash key must not be the public default in production (go-live 2026-11-12)."""
from django.conf import settings
from django.core.checks import Tags, Warning, register

PUBLIC_DEFAULT = 'elrezeiky-counsel-phone-v1'


@register(Tags.security, deploy=True)
def counsel_phone_hash_key_check(app_configs, **kwargs):
    key = (getattr(settings, 'COUNSEL_PHONE_HASH_KEY', '') or '').strip()
    if settings.DEBUG or (key and key != PUBLIC_DEFAULT):
        return []
    return [Warning(
        'COUNSEL_PHONE_HASH_KEY is empty or the default that is in the repository: stored counselling opt-outs '
        'can be matched against phone numbers by anyone who has the database.',
        hint='Set it once, before the first card is sent, to the same value on the office and the VPS '
             '(openssl rand -hex 32), and never change it afterwards.',
        id='counselling.W001')]
