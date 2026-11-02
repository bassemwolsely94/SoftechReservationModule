"""System checks for the N1 network-label settings (a typo here silently changes who counts as internal)."""
from django.conf import settings
from django.core.checks import Error, Warning, register

ZONES = ('internal', 'external')
ENFORCEMENT = ('off', 'log', 'enforce')


@register()
def network_settings_check(app_configs, **kwargs):
    out = []
    zone = getattr(settings, 'NETWORK_UNTRUSTED_ZONE', 'internal')
    mode = getattr(settings, 'NETWORK_POLICY_ENFORCEMENT', 'log')
    if zone not in ZONES:
        out.append(Error(f'NETWORK_UNTRUSTED_ZONE={zone!r} is invalid; use one of {ZONES}.', id='access.E001'))
    if mode not in ENFORCEMENT:
        out.append(Error(f'NETWORK_POLICY_ENFORCEMENT={mode!r} is invalid; use one of {ENFORCEMENT}.',
                         id='access.E002'))
    if not settings.DEBUG and not getattr(settings, 'NETWORK_HEADER_TRUSTED', False):
        out.append(Warning(
            'NETWORK_HEADER_TRUSTED is False outside DEBUG: the X-ElR-Network header is ignored and every '
            f'request is labelled {zone!r}. Set NETWORK_HEADER_TRUSTED=True only when our nginx with '
            'elrezeiky-proxy-headers.conf is the only way in.',
            id='access.W001'))
    return out
