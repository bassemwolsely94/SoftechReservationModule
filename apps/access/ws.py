"""
Access context and verdict for WebSocket connections (N5).

A Channels `scope` is turned into a request-shaped object so the same network / device / zone
code that serves HTTP serves sockets. `verdict` is the outer gate: account, device, token expiry,
then the zone rules. Consumers run their own record checks after it.
"""
import asyncio
import logging
from dataclasses import dataclass
from http.cookies import SimpleCookie

from django.core.cache import cache

from apps.users.sessions import account_active
from core.client_ip import client_ip, peer_meta

from . import context, devices, policy, session_policy
from .context import AccessContext
from .network import INTERNAL, NetworkInfo, request_network
from .policy_middleware import _mode
from .zones import Z3, Z4, zone_for

log = logging.getLogger('elrezeiky.access')

CLOSE_AUTH = 4001
CLOSE_EXPIRED = 4002
CLOSE_ZONE = 4403
WS_RECHECK_SECONDS = 300

# kind -> (path given to policy.decide, module)
SOCKET_KINDS = {
    'notifications': ('/api/notifications/', None),
    'chatter': ('/api/notifications/chatter/', None),
    'pbx': ('/ws/pbx/agent/', 'callcenter'),
}


class ScopeRequest:
    """The parts of an HttpRequest the access code reads, built from a Channels scope."""
    method = 'GET'

    def __init__(self, scope):
        self.META = {}
        self.META.update(peer_meta(scope))
        for name, value in scope.get('headers') or ():
            key = 'HTTP_' + name.decode('latin-1').upper().replace('-', '_')
            self.META[key] = value.decode('latin-1')
        self.COOKIES = {}
        try:
            jar = SimpleCookie()
            jar.load(self.META.get('HTTP_COOKIE', ''))
            self.COOKIES = {k: m.value for k, m in jar.items()}
        except Exception:
            self.COOKIES = {}
        self.path = self.path_info = scope.get('path', '')
        self.GET = {}


def context_for_scope(scope, user):
    """The AccessContext of a socket for `user`. Never raises: on error, the fallback context."""
    request = ScopeRequest(scope)
    try:
        network = request_network(request)
        device = devices.resolve(request)
        zone = zone_for(network.zone, device.status if device is not None else None)
        return AccessContext(network=network, user_id=user.pk if user else None,
                             role=context._role(user) if user else None, device=device, zone=zone)
    except Exception:
        log.warning('socket access context failed', exc_info=True)
        fb = context.fallback(request)
        return AccessContext(network=fb.network, user_id=getattr(user, 'pk', None),
                             role=context._role(user) if user else None, failed=True)


@dataclass(frozen=True)
class WsVerdict:
    allowed: bool
    close_code: int | None
    reason: str | None
    zone: str | None
    enforced: bool


def _device_revoked(scope):
    if devices.is_revoked(scope.get('token_dev')):
        return True
    try:
        dev = devices.resolve(ScopeRequest(scope))
    except Exception:
        dev = None
    return dev is not None and dev.status in ('blocked', 'retired')


def verdict(scope, user, kind, token_exp=None, now=None):
    """Whether the socket may stay open. First match wins (see the N5 plan)."""
    if not account_active(user):
        return WsVerdict(False, CLOSE_AUTH, 'inactive', None, True)
    if _device_revoked(scope):
        return WsVerdict(False, CLOSE_AUTH, 'device_revoked', None, True)
    if token_exp is not None:
        if now is None:
            import time
            now = time.time()
        if now >= token_exp:
            return WsVerdict(False, CLOSE_EXPIRED, 'expired', None, True)
    mode = _mode()
    if mode == 'off':
        return WsVerdict(True, None, None, None, False)
    try:
        ctx = context_for_scope(scope, user)
        if ctx.failed and ctx.network.zone == INTERNAL:      # F3: open inside, closed outside
            return WsVerdict(True, None, None, None, False)
        zone = ctx.zone
        path, module = SOCKET_KINDS[kind]
        profile = session_policy.subject(user)
        if kind == 'pbx' and zone in (Z3, Z4):
            reason = 'module'
        else:
            decision = policy.decide(profile, zone, path, 'GET', module=module)
            reason = None if decision.allowed else decision.reason
            zone = decision.zone
    except Exception:
        log.warning('socket verdict failed', exc_info=True)
        return WsVerdict(False, CLOSE_ZONE, 'error', None, mode == 'enforce')
    if reason is None:
        return WsVerdict(True, None, None, zone, False)
    return WsVerdict(False, CLOSE_ZONE, reason, zone, mode == 'enforce')


# ── Server push ──────────────────────────────────────────────────────────────

def _send_recheck(user_ids):
    """Group-send `access.recheck`. Never raises: a failure is one WARNING line."""
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        layer = get_channel_layer()
        if layer is None:
            return
        groups = ['access_all'] if user_ids is None else [f'access_user_{i}' for i in user_ids]
        for group in groups:
            async_to_sync(layer.group_send)(group, {'type': 'access.recheck'})
    except Exception as exc:
        log.warning('access re-check push failed: %s', exc)


def push_recheck(user_ids=None):
    """Ask open sockets to re-run their verdict now: the given users' sockets, or everyone's when
    `user_ids` is None. Runs after the surrounding transaction commits. Never raises."""
    ids = None if user_ids is None else list(user_ids)
    if ids is not None and not ids:
        return
    try:
        from django.db import transaction
        transaction.on_commit(lambda: _send_recheck(ids))
    except Exception as exc:
        log.warning('access re-check push failed: %s', exc)


# ── Consumers ────────────────────────────────────────────────────────────────

AUDIT_ACTION = 'ws_zone_denied'
DEDUPE_SECONDS = 600


def _fresh_user(user_id):
    """The user as the database has it now: a socket lives for hours, the scope's copy does not
    see a disabled account. None when it is gone."""
    from django.contrib.auth import get_user_model
    if user_id is None:
        return None
    return get_user_model().objects.select_related('staff_profile').filter(pk=user_id).first()


def _write_audit(user_id, note_text, extra):
    """One `ws_zone_denied` row, through the `audit_log` alias first (as the SOFTECH gate does),
    then `default`. True when a row was saved. Never raises."""
    from apps.audit.models import AuditLog
    from apps.users.models import StaffProfile

    from .softech_gate import _audit_aliases
    for alias in _audit_aliases():
        try:
            staff = None
            if user_id is not None:
                staff = StaffProfile.objects.using(alias).filter(user_id=user_id).first()
            if AuditLog.log(AUDIT_ACTION, user=staff, note=note_text, extra=extra,
                            using=alias) is not None:
                return True
        except Exception as exc:
            if type(exc).__name__ != 'DatabaseOperationForbidden':
                log.warning('ws audit write on %s failed - trying the next', alias, exc_info=True)
    return False


def _note_refusal(scope, user_id, kind, v):
    """The deduplicated log line and (zone refusals only) AuditLog row of a refused verdict."""
    if v.close_code != CLOSE_ZONE:
        return                         # 4001 / 4002: an ordinary end of a session, no row
    key = f'access:ws:{user_id}:{kind}:{v.zone}:{v.reason}:{int(v.enforced)}'
    try:
        if not cache.add(key, 1, DEDUPE_SECONDS):
            return
    except Exception:
        pass
    log.warning('ws %s user=%s kind=%s zone=%s reason=%s',
                'denied' if v.enforced else 'would-deny', user_id, kind, v.zone, v.reason)
    ip = None
    try:
        ip = client_ip(ScopeRequest(scope))
    except Exception:
        pass
    extra = {'kind': kind, 'zone': v.zone, 'reason': v.reason, 'enforced': v.enforced,
             'mode': 'enforce' if v.enforced else 'log', 'ip': ip, 'path': scope.get('path')}
    if not _write_audit(user_id, f'{kind} / {v.reason} / {v.zone}'[:255], extra):
        log.error('ws audit row lost (%s %s %s)', user_id, kind, v.reason)
        try:
            cache.delete(key)          # retried by the next refusal, not silenced for 10 minutes
        except Exception:
            pass


def _check(scope, user_id, kind):
    """The verdict for the socket now, with its log line / audit row. Runs in a worker thread."""
    v = verdict(scope, _fresh_user(user_id), kind, token_exp=scope.get('token_exp'))
    if not v.allowed:
        _note_refusal(scope, user_id, kind, v)
    return v


class ZoneGuardMixin:
    """Account, device, token expiry and zone for a Channels consumer: at connect (zone_admit),
    every WS_RECHECK_SECONDS (zone_start's loop) and on an `access.recheck` push to the groups
    `access_user_<pk>` / `access_all`. Runs after the consumer's own "is authenticated" check and
    before its record checks (ruling F2)."""
    socket_kind: str = ''

    def _zone_user_id(self):
        return getattr(self.scope.get('user'), 'pk', None)

    async def _zone_verdict(self):
        from channels.db import database_sync_to_async
        return await database_sync_to_async(_check)(self.scope, self._zone_user_id(),
                                                    self.socket_kind)

    async def _zone_apply(self):
        """True when the socket may stay open; False after closing it."""
        v = await self._zone_verdict()
        if v.allowed or not v.enforced:
            return True
        self._zone_closed = True
        await self.close(code=v.close_code)
        return False

    async def zone_admit(self) -> bool:
        return await self._zone_apply()

    async def zone_start(self):
        user_id = self._zone_user_id()
        self._zone_groups = [f'access_user_{user_id}', 'access_all']
        for group in self._zone_groups:
            await self.channel_layer.group_add(group, self.channel_name)
        self._zone_task = asyncio.ensure_future(self._zone_loop())

    async def zone_stop(self):
        task = getattr(self, '_zone_task', None)
        if task is not None:
            task.cancel()
            self._zone_task = None
        for group in getattr(self, '_zone_groups', ()):
            await self.channel_layer.group_discard(group, self.channel_name)
        self._zone_groups = []

    async def _zone_loop(self):
        while True:
            await asyncio.sleep(WS_RECHECK_SECONDS)
            try:
                if not await self._zone_apply():
                    return
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning('ws re-check failed (%s)', self.socket_kind, exc_info=True)

    async def access_recheck(self, event):
        """`access.recheck` pushed to the user's or everyone's group: check once, now."""
        if getattr(self, '_zone_closed', False):
            return
        await self._zone_apply()
