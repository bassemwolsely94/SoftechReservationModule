"""
Where a request came from (N1, log only).

The zone (internal / external) is the X-ElR-Network header, written by nginx from the address the
request arrived on. It is believed only when NETWORK_HEADER_TRUSTED (behind our nginx); a missing or
unknown value then means external (fail closed). Without nginx (dev, tests) NETWORK_UNTRUSTED_ZONE
stands in. The site is the most specific active TrustedNetwork holding the client IP, and only an
internal request gets one.
"""
import hmac
import ipaddress
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

from core.client_ip import client_ip

INTERNAL = 'internal'
EXTERNAL = 'external'
_CACHE_KEY = 'access:trusted-networks'


@dataclass(frozen=True)
class NetworkInfo:
    zone: str
    ip: str | None
    site: object | None   # TrustedNetwork

    @property
    def label_ar(self):
        if self.zone != INTERNAL:
            return 'خارج الشبكة'
        if self.site is not None:
            return f'داخل الشبكة — {self.site.name}'
        return 'شبكة داخلية غير مسجلة'


def proxy_key_ok(request):
    """True when no NETWORK_PROXY_KEY is configured, else a constant-time match of X-ElR-Proxy-Key."""
    key = getattr(settings, 'NETWORK_PROXY_KEY', '') or ''
    if not key:
        return True
    sent = request.META.get('HTTP_X_ELR_PROXY_KEY') or ''
    # bytes, so a non-ASCII header can never make compare_digest raise
    return hmac.compare_digest(str(sent).encode('utf-8', 'surrogateescape'), str(key).encode('utf-8'))


def zone_from_request(request):
    if not getattr(settings, 'NETWORK_HEADER_TRUSTED', False):
        return INTERNAL if getattr(settings, 'NETWORK_UNTRUSTED_ZONE', INTERNAL) == INTERNAL else EXTERNAL
    if not proxy_key_ok(request):
        return EXTERNAL   # only our nginx knows the key
    return INTERNAL if request.META.get('HTTP_X_ELR_NETWORK') == INTERNAL else EXTERNAL


def invalidate_cache(*args, **kwargs):
    cache.delete(_CACHE_KEY)


def _active_networks():
    ttl = getattr(settings, 'ACCESS_NETWORKS_TTL', 60)
    if ttl:
        cached = cache.get(_CACHE_KEY)
        if cached is not None:
            return cached
    from .models import TrustedNetwork
    rows = []
    for tn in TrustedNetwork.objects.filter(is_active=True):
        try:
            rows.append((ipaddress.ip_network(tn.cidr, strict=False), tn))
        except ValueError:
            continue
    rows.sort(key=lambda r: r[0].prefixlen, reverse=True)
    if ttl:
        cache.set(_CACHE_KEY, rows, ttl)
    return rows


def match_site(ip):
    if not ip:
        return None
    try:
        addr = ipaddress.ip_address(str(ip).strip())
    except ValueError:
        return None
    for net, tn in _active_networks():
        if addr.version == net.version and addr in net:
            return tn
    return None


def request_network(request):
    zone = zone_from_request(request)
    ip = client_ip(request)
    return NetworkInfo(zone=zone, ip=ip, site=match_site(ip) if zone == INTERNAL else None)
