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
    trusted = getattr(settings, 'NETWORK_HEADER_TRUSTED', False)
    has_key = bool(getattr(settings, 'NETWORK_PROXY_KEY', ''))
    if mode == 'enforce' and trusted and not has_key:
        out.append(Error(
            'NETWORK_POLICY_ENFORCEMENT=enforce with NETWORK_HEADER_TRUSTED needs NETWORK_PROXY_KEY: without '
            'it anything that can reach Daphne directly could send X-ElR-Network: internal.',
            id='access.E003'))
    elif trusted and not has_key and not settings.DEBUG:
        out.append(Warning(
            'NETWORK_PROXY_KEY is empty while NETWORK_HEADER_TRUSTED is True: X-ElR-Network is believed '
            'without proof it came from our nginx. Set the key (runbook, Batch N3) before enforcing.',
            id='access.W002'))
    if mode == 'enforce' and not trusted:
        out.append(Error(
            'NETWORK_POLICY_ENFORCEMENT=enforce needs NETWORK_HEADER_TRUSTED=True: without the nginx label every '
            f'request is {zone!r} (NETWORK_UNTRUSTED_ZONE), so the policy is either void or refuses everyone.',
            id='access.E004'))
    return out


@register()
def softech_gate_settings_check(app_configs, **kwargs):
    """N4: SOFTECH_GATE_ENFORCEMENT. An unknown value silently runs as `log` (W003); `enforce` on a
    setup that cannot tell inside from outside runs as `log` too (E005) - so the runbook's
    `env SOFTECH_GATE_ENFORCEMENT=enforce manage.py check` step refuses it before .env changes."""
    from .policy_middleware import enforce_problem
    out = []
    raw = getattr(settings, 'SOFTECH_GATE_ENFORCEMENT', 'log')
    value = str(raw or 'log').lower()
    if value not in ENFORCEMENT:
        out.append(Warning(
            f'SOFTECH_GATE_ENFORCEMENT={raw!r} is not one of {ENFORCEMENT}: it runs as log (nothing is '
            'refused).',
            id='access.W003'))
    elif value == 'enforce':
        problem = enforce_problem()
        if problem:
            out.append(Error(
                f'SOFTECH_GATE_ENFORCEMENT=enforce cannot be trusted ({problem}): it would run as log. '
                'Fix the N3 network label first.',
                id='access.E005'))
    return out
