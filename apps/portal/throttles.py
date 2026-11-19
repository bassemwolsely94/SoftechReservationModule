"""
apps/portal/throttles.py

Rate-limit the unauthenticated portal entry points (magic-link request and
token exchange). A link request is limited per PHONE (whatever the IP — so a
caller cannot flood one customer's WhatsApp by changing address) and, separately,
per IP (so one caller cannot walk through many numbers). Batch 6, W-5.
"""
from rest_framework.throttling import SimpleRateThrottle
from core.limits import limits_cache


class RequestLinkThrottle(SimpleRateThrottle):
    scope = 'portal_request_link'
    cache = limits_cache   # fail-closed security counters (core/limits.py)

    def get_cache_key(self, request, view):
        from apps.portal.services import _core_digits
        phone = _core_digits(str(request.data.get('phone') or '')) or '-'
        return self.cache_format % {'scope': self.scope, 'ident': phone}


class RequestLinkIPThrottle(SimpleRateThrottle):
    scope = 'portal_request_link_ip'
    cache = limits_cache   # fail-closed security counters (core/limits.py)

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


class AuthExchangeThrottle(SimpleRateThrottle):
    scope = 'portal_auth'
    cache = limits_cache   # fail-closed security counters (core/limits.py)

    def get_cache_key(self, request, view):
        return self.cache_format % {
            'scope': self.scope,
            'ident': self.get_ident(request),
        }
