"""
Access context and verdict for WebSocket connections (N5).

A Channels `scope` is turned into a request-shaped object so the same network / device / zone
code that serves HTTP serves sockets. `verdict` is the outer gate: account, device, token expiry,
then the zone rules. Consumers run their own record checks after it.
"""
import logging
from dataclasses import dataclass
from http.cookies import SimpleCookie

from apps.users.sessions import account_active
from core.client_ip import peer_meta

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
