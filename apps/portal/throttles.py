"""
apps/portal/throttles.py

Rate-limit the unauthenticated portal entry points (magic-link request and
token exchange). Keyed by submitted phone + client IP so neither a single phone
nor a single IP can be hammered.
"""
from rest_framework.throttling import SimpleRateThrottle


class RequestLinkThrottle(SimpleRateThrottle):
    scope = 'portal_request_link'

    def get_cache_key(self, request, view):
        phone = (request.data.get('phone') or '').strip()
        ident = f'{phone}|{self.get_ident(request)}'
        return self.cache_format % {'scope': self.scope, 'ident': ident}


class AuthExchangeThrottle(SimpleRateThrottle):
    scope = 'portal_auth'

    def get_cache_key(self, request, view):
        return self.cache_format % {
            'scope': self.scope,
            'ident': self.get_ident(request),
        }
