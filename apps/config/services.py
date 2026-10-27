"""
apps/config/services.py

Cached accessor for SystemSetting values.

Usage:
    from apps.config.services import get_setting

    # String
    pharmacy_name = get_setting('pharmacy_name', default='صيدليات الرزيقي')

    # Typed
    expiry_minutes = int(get_setting('voucher_otp_expiry_minutes', default='3'))

Cache TTL: 5 minutes (SETTINGS_CACHE_TTL).
Cache is automatically invalidated when a SystemSetting is saved (post_save signal).
"""
from django.core.cache import cache
from django.db.models.signals import post_save
from django.dispatch import receiver

SETTINGS_CACHE_TTL    = 300          # 5 minutes
_CACHE_KEY_PREFIX     = 'syssetting:'
_CACHE_ALL_KEYS_KEY   = '_syssetting_all_keys'   # used only by invalidation logic


def _cache_key(key: str) -> str:
    return f'{_CACHE_KEY_PREFIX}{key}'


def get_setting(key: str, *, default: str = '') -> str:
    """
    Return the *raw string* value of a SystemSetting by key.

    Result is cached for SETTINGS_CACHE_TTL seconds.
    Returns `default` if the key does not exist in the database.
    """
    cache_key = _cache_key(key)
    cached    = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        from .models import SystemSetting
        value = SystemSetting.objects.get(key=key).value
    except Exception:
        value = default

    cache.set(cache_key, value, SETTINGS_CACHE_TTL)
    return value


def get_typed_setting(key: str, *, default=None):
    """
    Return the *typed* value of a SystemSetting (via typed_value()).
    Caches the raw string; type conversion happens after cache retrieval.
    """
    raw = get_setting(key, default='' if default is None else str(default))
    try:
        from .models import SystemSetting
        obj = SystemSetting(key=key, value=raw)
        # Peek at the stored type for coercion — a second DB hit only if not cached
        try:
            real = SystemSetting.objects.get(key=key)
            return real.typed_value()
        except SystemSetting.DoesNotExist:
            return default
    except Exception:
        return default


def invalidate_setting(key: str):
    """Manually remove one setting from cache."""
    cache.delete(_cache_key(key))


# ── Signal: auto-invalidate on save ──────────────────────────────────────────

@receiver(post_save, sender='config.SystemSetting')
def _on_setting_saved(sender, instance, **kwargs):
    """Clear the cache entry whenever a setting is created or updated."""
    cache.delete(_cache_key(instance.key))
