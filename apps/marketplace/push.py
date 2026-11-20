"""
apps/marketplace/push.py — push stock / order status to a platform, dry-run unless switched on.

Dry-run (settings.MARKETPLACE_PUSH_ENABLED off, or channel inactive) logs the payload and calls nothing.
Never raises: an adapter failure is logged and stored on the PushLog. Nothing here touches SOFTECH.
What is stored is masked first (doc 38 M2 gate): the channel's own credential values, secret-named keys
(token / secret / password / api key / authorization) and anything core.errors.redact recognises — a
platform echoing our token in its reply must never reach the push-log screen.
"""
import logging
import re
from decimal import Decimal

from django.conf import settings

from apps.marketplace.adapters import get_adapter
from apps.marketplace.availability import snapshot
from apps.marketplace.models import ChannelStore, PushLog
from core.errors import redact

logger = logging.getLogger('elrezeiky.marketplace')

MASK = '***'
_SECRET_KEY = re.compile(r'(token|secret|passw|api[_-]?key|authori[sz]ation|signature|credential|cookie)', re.I)
_MIN_SECRET_LEN = 6          # shorter credential values would mask ordinary words / numbers


def _secret_values(channel) -> list:
    out = []

    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
        elif v is not None and not isinstance(v, bool) and len(str(v)) >= _MIN_SECRET_LEN:
            out.append(str(v))
    walk(getattr(channel, 'credentials', None) or {})
    return sorted(set(out), key=len, reverse=True)   # longest first: a secret containing another one


def mask(value, secrets=()):
    """`value` (JSON-safe) with secrets masked: secret-named keys, the given credential values, redact()."""
    if isinstance(value, dict):
        return {k: (MASK if isinstance(k, str) and _SECRET_KEY.search(k) and v not in (None, '')
                    else mask(v, secrets)) for k, v in value.items()}
    if isinstance(value, list):
        return [mask(v, secrets) for v in value]
    if isinstance(value, str):
        for s in secrets:
            value = value.replace(s, MASK)
        return redact(value)
    return value


def _json_safe(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _live(channel) -> bool:
    return bool(getattr(settings, 'MARKETPLACE_PUSH_ENABLED', False)) and channel.is_active


def _run(channel, store, kind, payload, call):
    secrets = _secret_values(channel)
    log = PushLog(channel=channel, store=store, kind=kind, payload=mask(_json_safe(payload), secrets))
    if not _live(channel):
        log.dry_run, log.ok = True, True
        log.save()
        return log
    log.dry_run = False
    try:
        response = call(get_adapter(channel.adapter, channel))
        log.response, log.ok = mask(_json_safe(response or {}), secrets), True
    except Exception as exc:  # noqa: BLE001 - a push never raises; the failure is stored on the PushLog
        logger.warning('marketplace push failed: channel=%s kind=%s error=%s', channel.code, kind, type(exc).__name__)
        log.ok = False
        log.response = {'error': type(exc).__name__, 'detail': mask(str(exc), secrets)[:300]}
    log.save()
    return log


def push_stock(channel, store=None, *, user=None) -> list:
    """One PushLog per store (store=None: every active ChannelStore). Rows are the availability snapshot,
    qty + price together; non-sellable rows carry qty 0 so the platform delists them."""
    if store is not None:
        stores = [store]
    else:
        stores = list(ChannelStore.objects.filter(channel=channel, is_active=True).select_related('branch'))
    logs = []
    for s in stores:
        rows = snapshot(channel, s)
        logs.append(_run(channel, s, PushLog.KIND_STOCK, rows, lambda a, s=s, rows=rows: a.push_stock(s, rows)))
    return logs


def push_status(order) -> PushLog:
    payload = {'external_id': order.external_id, 'status': order.status}
    return _run(order.channel, order.store, PushLog.KIND_STATUS, payload,
                lambda a: a.send_status(order, order.status))
