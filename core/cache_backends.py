"""
Redis cache backends with an explicit failure rule (performance Stage 2, design §9).

FailOpenRedisCache  — the `default` alias (plain performance caches, log dedupe, compute-once
                      locks). A Redis error is a cache miss: reads give the default, writes are
                      dropped, add() answers True (go ahead and compute), incr() raises
                      ValueError like a missing key. The request is served without the cache.
FailClosedRedisCache — the `limits` alias (core/limits.py). A Redis error raises
                      LimitsUnavailable: the request is refused with 503, never served without
                      its limit.

Either logs a Redis error at most once a minute per process (no key names: they can hold a
hashed identifier or a phone).
"""
import logging
import time

from django.core.cache.backends.base import DEFAULT_TIMEOUT
from django.core.cache.backends.redis import RedisCache
from redis.exceptions import RedisError

from core.limits import LimitsUnavailable

log = logging.getLogger('elrezeiky.cache')

LOG_EVERY_SECONDS = 60
_last_logged = {}


def _note(kind, exc):
    now = time.monotonic()
    if now - _last_logged.get(kind, -LOG_EVERY_SECONDS) >= LOG_EVERY_SECONDS:
        _last_logged[kind] = now
        log.error('redis %s cache unreachable (%s)', kind, type(exc).__name__)


class FailOpenRedisCache(RedisCache):

    def _miss(self, exc, value):
        _note('default', exc)
        return value

    def get(self, key, default=None, version=None):
        try:
            return super().get(key, default, version)
        except RedisError as exc:
            return self._miss(exc, default)

    def get_many(self, keys, version=None):
        try:
            return super().get_many(keys, version)
        except RedisError as exc:
            return self._miss(exc, {})

    def has_key(self, key, version=None):
        try:
            return super().has_key(key, version)
        except RedisError as exc:
            return self._miss(exc, False)

    def add(self, key, value, timeout=DEFAULT_TIMEOUT, version=None):
        try:
            return super().add(key, value, timeout, version)
        except RedisError as exc:
            return self._miss(exc, True)

    def set(self, key, value, timeout=DEFAULT_TIMEOUT, version=None):
        try:
            return super().set(key, value, timeout, version)
        except RedisError as exc:
            return self._miss(exc, None)

    def set_many(self, data, timeout=DEFAULT_TIMEOUT, version=None):
        try:
            return super().set_many(data, timeout, version)
        except RedisError as exc:
            return self._miss(exc, [])

    def touch(self, key, timeout=DEFAULT_TIMEOUT, version=None):
        try:
            return super().touch(key, timeout, version)
        except RedisError as exc:
            return self._miss(exc, False)

    def delete(self, key, version=None):
        try:
            return super().delete(key, version)
        except RedisError as exc:
            return self._miss(exc, False)

    def delete_many(self, keys, version=None):
        try:
            return super().delete_many(keys, version)
        except RedisError as exc:
            return self._miss(exc, None)

    def incr(self, key, delta=1, version=None):
        try:
            return super().incr(key, delta, version)
        except RedisError as exc:
            _note('default', exc)
            raise ValueError("Key '%s' not found" % key) from exc

    def clear(self):
        try:
            return super().clear()
        except RedisError as exc:
            return self._miss(exc, False)


def _closed(method):
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except RedisError as exc:
            _note('limits', exc)
            raise LimitsUnavailable() from exc
    wrapper.__name__ = method.__name__
    wrapper.__doc__ = method.__doc__
    return wrapper


class FailClosedRedisCache(RedisCache):
    pass


for _name in ('get', 'get_many', 'has_key', 'add', 'set', 'set_many', 'touch', 'delete',
              'delete_many', 'incr', 'clear'):
    setattr(FailClosedRedisCache, _name, _closed(getattr(RedisCache, _name)))
