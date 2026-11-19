"""
The cache that holds security counters (performance Stage 2; owner decision 2026-11-19 §9).

`limits_cache` is the `limits` cache alias: every DRF throttle, the login unknown-identifier
lockout, 2FA code replay / tries, the public-form proof-of-work replay keys and per-phone daily
caps (N6) and the bulk-read counters (N5). On the VPS it is its own Redis database with
`maxmemory-policy noeviction`, apart from the plain cache and the Channels layer, so a full cache
can never evict a limit.

It FAILS CLOSED: when Redis cannot be reached, core.cache_backends.FailClosedRedisCache raises
LimitsUnavailable and the request is refused with 503 and the Arabic "try again shortly"
message — never served without its limit. In dev / tests it is LocMem sharing storage with
`default`.
"""
from django.core.cache import caches
from django.utils.connection import ConnectionProxy
from rest_framework.exceptions import APIException

LIMITS_ALIAS = 'limits'
LIMITS_UNAVAILABLE_MESSAGE = 'الخدمة غير متاحة مؤقتاً — حاول مرة أخرى بعد قليل'
LIMITS_UNAVAILABLE_CODE = 'limits_unavailable'
RETRY_AFTER_SECONDS = 30

# Resolved on every use, so override_settings(CACHES=...) in tests takes effect.
limits_cache = ConnectionProxy(caches, LIMITS_ALIAS)


class LimitsUnavailable(APIException):
    status_code = 503
    default_detail = LIMITS_UNAVAILABLE_MESSAGE
    default_code = LIMITS_UNAVAILABLE_CODE


def refusal_body():
    return {'detail': LIMITS_UNAVAILABLE_MESSAGE, 'code': LIMITS_UNAVAILABLE_CODE}
