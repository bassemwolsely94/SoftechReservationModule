"""
SOFTECH gate decision (N4): may this request open a SOFTECH connection, and may it write?

`decide()` is pure apart from the cached policy lookup. `check()` is what the connection layer
calls before every connect: it adds the mode (SOFTECH_GATE_ENFORCEMENT: off / log / enforce), the
subject lookup, and the log line + AuditLog row. Nothing here imports config.sybase.

System scopes (anything not starting with `web`: job:*, cmd:*) are always FULL. The global kill
switch SOFTECH_READ_ONLY and writers.writer_allowed() stay in force on top of this: the gate
never widens anything.
"""
import contextvars
import logging
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

from . import context as access_context
from . import policy, session_policy
from .network import INTERNAL
from .zones import Z1, Z2, Z4

log = logging.getLogger('elrezeiky.access')

FULL = 'full'
READ = 'read'
NONE = 'none'

AUDIT_ACTION = 'softech_gate_denied'
LOG_DEDUPE_SECONDS = 600

DENY_MESSAGE = 'SOFTECH غير متاح لدورك من هذا المكان'
WRITE_DENY_MESSAGE = 'الكتابة في SOFTECH غير متاحة لدورك من هذا المكان'

_subject_var = contextvars.ContextVar('softech_gate_subject', default=None)


@dataclass(frozen=True)
class GateDecision:
    grant: str
    reason: str | None
    scope: str
    zone: str | None


def mode():
    """off / log / enforce. An unknown value is log; enforce on an unsafe setup is log + ERROR."""
    from .policy_middleware import _log_unsafe, enforce_problem
    value = str(getattr(settings, 'SOFTECH_GATE_ENFORCEMENT', 'log') or 'log').lower()
    if value not in ('off', 'log', 'enforce'):
        return 'log'
    if value == 'enforce':
        problem = enforce_problem()
        if problem:
            _log_unsafe(problem)
            return 'log'
    return value


def decide(scope, ctx, profile):
    """The grant for one scope / context / policy subject. Order: system scope, no context,
    failed context, anonymous, policy row."""
    if not str(scope or '').startswith('web'):
        return GateDecision(FULL, None, scope, None)
    if ctx is None:
        return GateDecision(NONE, 'no_context', scope, None)
    zone = ctx.zone
    if ctx.failed:
        # F3 parity: a failed context is let through inside the network, refused outside
        if ctx.network.zone == INTERNAL:
            return GateDecision(FULL, 'context_failed', scope, zone)
        return GateDecision(NONE, 'context_failed', scope, zone)
    if ctx.user_id is None or profile is None:
        return GateDecision(NONE, 'anonymous', scope, zone)
    zone = zone or Z4
    pol = policy.policy_for(profile.role, zone)
    if pol is None:
        # a role without rows: open inside, closed outside (as softech_write_allowed)
        if zone in (Z1, Z2):
            return GateDecision(FULL, None, scope, zone)
        return GateDecision(NONE, 'zone_no_read', scope, zone)
    if not pol.softech_read:
        return GateDecision(NONE, 'zone_no_read', scope, zone)
    if not policy.softech_write_allowed(profile, zone):
        return GateDecision(READ, 'zone_no_write', scope, zone)
    return GateDecision(FULL, None, scope, zone)


def _subject(ctx):
    """The policy subject of the context's user, memoised for the request's context."""
    cached = _subject_var.get()
    if cached is not None and cached[0] is ctx:
        return cached[1]
    profile = None
    if ctx.user_id is not None:
        from django.contrib.auth import get_user_model
        user = (get_user_model().objects.select_related('staff_profile')
                .filter(pk=ctx.user_id).first())
        profile = session_policy.subject(user) if user is not None else None
    _subject_var.set((ctx, profile))
    return profile


def check(label=''):
    """The effective decision for the current scope and context, after the mode."""
    from apps.sync.softech_load import current_scope
    scope = current_scope()
    current_mode = mode()
    if current_mode == 'off':
        return GateDecision(FULL, None, scope, None)
    ctx = access_context.current()
    profile = None
    if str(scope).startswith('web') and ctx is not None and not ctx.failed:
        try:
            profile = _subject(ctx)
        except Exception:
            log.error('softech gate: subject lookup failed', exc_info=True)
            profile = None
    decision = decide(scope, ctx, profile)
    if decision.reason == 'context_failed' and decision.grant == FULL:
        log.error('softech gate: access context failed inside the network - allowed (%s)', label)
    if decision.grant == NONE:
        enforced = current_mode == 'enforce'
        note(decision, label, enforced=enforced)
        if not enforced:
            return GateDecision(FULL, decision.reason, scope, decision.zone)
    return decision


def note(decision, label, *, enforced):
    """One deduplicated log line and AuditLog row for a refusal (or would-refuse). Never raises."""
    try:
        ctx = access_context.current()
        user_id = ctx.user_id if ctx is not None else None
        current_mode = mode()
        key = f'access:softech-gate:{user_id}:{decision.zone}:{decision.reason}:{current_mode}'
        try:
            if not cache.add(key, 1, LOG_DEDUPE_SECONDS):
                return
        except Exception:
            pass
        ip = ctx.network.ip if ctx is not None else None
        device_id = ctx.device.public_id if ctx is not None and ctx.device is not None else None
        log.warning('softech gate %s: grant=%s reason=%s scope=%s zone=%s user=%s label=%s',
                    'denied' if enforced else 'would-deny', decision.grant, decision.reason,
                    decision.scope, decision.zone, user_id, label)
        from apps.audit.models import AuditLog
        staff = None
        if ctx is not None and ctx.user_id is not None:
            from apps.users.models import StaffProfile
            staff = StaffProfile.objects.filter(user_id=ctx.user_id).first()
        AuditLog.log(AUDIT_ACTION, user=staff,
                     note=f'{decision.reason} / {decision.zone}'[:255],
                     extra={'scope': decision.scope, 'zone': decision.zone,
                            'reason': decision.reason, 'label': label, 'mode': current_mode,
                            'ip': ip, 'device_id': device_id, 'enforced': enforced})
    except Exception:
        log.error('softech gate: audit row lost (%s %s)', decision, label, exc_info=True)
