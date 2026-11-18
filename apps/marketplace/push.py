"""
apps/marketplace/push.py — push stock / order status to a platform, dry-run unless switched on.

Dry-run (settings.MARKETPLACE_PUSH_ENABLED off, or channel inactive) logs the payload and calls nothing.
Never raises: an adapter failure is logged and stored on the PushLog. Nothing here touches SOFTECH.
"""
import logging
from decimal import Decimal

from django.conf import settings

from apps.marketplace.adapters import get_adapter
from apps.marketplace.availability import snapshot
from apps.marketplace.models import ChannelStore, PushLog
from core.errors import redact

logger = logging.getLogger('elrezeiky.marketplace')


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
    log = PushLog(channel=channel, store=store, kind=kind, payload=_json_safe(payload))
    if not _live(channel):
        log.dry_run, log.ok = True, True
        log.save()
        return log
    log.dry_run = False
    try:
        response = call(get_adapter(channel.adapter, channel))
        log.response, log.ok = _json_safe(response or {}), True
    except Exception as exc:  # noqa: BLE001 - a push never raises; the failure is stored on the PushLog
        logger.warning('marketplace push failed: channel=%s kind=%s error=%s', channel.code, kind, type(exc).__name__)
        log.ok = False
        log.response = {'error': type(exc).__name__, 'detail': redact(str(exc))[:300]}
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
