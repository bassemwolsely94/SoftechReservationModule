"""
apps/users/audit.py — small helpers for UserActivityLog rows, shared by views, mfa, lockout and
apps.access.devices (no import of views needed).
"""


def request_network_fields(request):
    """The network label and browser of a request, for the activity log (blank without one)."""
    if request is None:
        return {}
    try:
        from apps.access.network import request_network
        acc = getattr(request, 'access', None)
        net = acc.network if acc else request_network(request)
        return {
            'network': net.zone,
            'network_site': net.site.name if net.site else '',
            'user_agent': (request.META.get('HTTP_USER_AGENT') or '')[:300],
        }
    except Exception:
        return {}
