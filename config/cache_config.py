"""
CACHES from the environment (performance Stage 2; runbook §13.6).

No Redis URLs (dev, tests, the office) → two LocMem aliases that share one storage, exactly as
before (`cache.clear()` still resets every counter).

CACHE_REDIS_URL + LIMITS_REDIS_URL (the VPS, before the extra web processes are enabled) →
  default  core.cache_backends.FailOpenRedisCache   (plain caches; Redis down = cache miss)
  limits   core.cache_backends.FailClosedRedisCache (security counters; Redis down = 503)
Both are required together and must differ: the limits live in their own Redis database with
`maxmemory-policy noeviction`, so a full plain cache can never evict a limit.
"""
from django.core.exceptions import ImproperlyConfigured

LOCMEM_LOCATION = 'elrezeiky-default'


def _redis_options():
    # Short timeouts and one quick retry: a dead Redis costs a request about a second, not a hang.
    from redis.backoff import ExponentialBackoff
    from redis.retry import Retry
    return {
        'socket_connect_timeout': 0.5,
        'socket_timeout': 0.5,
        'health_check_interval': 30,
        'retry': Retry(ExponentialBackoff(cap=0.2, base=0.05), 1),
    }


def build_caches(*, cache_url, limits_url, max_entries):
    cache_url, limits_url = (cache_url or '').strip(), (limits_url or '').strip()
    if not cache_url and not limits_url:
        locmem = {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': LOCMEM_LOCATION,
            'OPTIONS': {'MAX_ENTRIES': max_entries},
        }
        return {'default': dict(locmem), 'limits': dict(locmem)}
    if not (cache_url and limits_url):
        raise ImproperlyConfigured(
            'Set CACHE_REDIS_URL and LIMITS_REDIS_URL together (runbook §13.6), or neither.')
    if cache_url == limits_url:
        raise ImproperlyConfigured(
            'LIMITS_REDIS_URL must be its own Redis database (noeviction), not CACHE_REDIS_URL.')
    return {
        'default': {'BACKEND': 'core.cache_backends.FailOpenRedisCache',
                    'LOCATION': cache_url, 'OPTIONS': _redis_options()},
        'limits': {'BACKEND': 'core.cache_backends.FailClosedRedisCache',
                   'LOCATION': limits_url, 'OPTIONS': _redis_options()},
    }
