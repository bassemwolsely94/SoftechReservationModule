"""
The client's address, as our own proxies saw it (Batch 3, A-6).

X-Forwarded-For is written by the client and APPENDED to by each proxy, so only the entries our
proxies added can be trusted: with settings.NUM_PROXIES = n the client is the n-th entry from the
right — the same rule DRF's throttles use (REST_FRAMEWORK['NUM_PROXIES']). With 0 (no proxy) the
header is ignored and REMOTE_ADDR is the client.
"""
from django.conf import settings


def client_ip(request):
    remote = request.META.get('REMOTE_ADDR') or None
    hops = getattr(settings, 'NUM_PROXIES', 0) or 0
    if hops <= 0:
        return remote
    chain = [a.strip() for a in request.META.get('HTTP_X_FORWARDED_FOR', '').split(',') if a.strip()]
    if not chain:
        return remote
    return chain[-min(hops, len(chain))]


def peer_meta(scope):
    """The request.META entry for the socket peer of a Channels scope (the only other place that
    spells the REMOTE_ADDR key, so client_ip() above reads sockets and requests alike)."""
    client = scope.get('client')
    return {'REMOTE_ADDR': client[0]} if client else {}
