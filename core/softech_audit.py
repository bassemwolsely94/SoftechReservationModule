"""
core/softech_audit.py

One AuditLog row for every write that reaches SOFTECH — who, what, when, before → after
(CLAUDE.md rule 8; Batch 2, P-16).

    audit_softech_write('softech_posdiscp_written', actor=request.user, obj=offer,
                        before={'91001': 5.0}, after={'91001': 10.0}, usercode='19')

Actions are 'softech_*' strings. Like the ISR guards' actions they are not in
AuditLog.ACTION_CHOICES yet — the labels are one state-only migration, to be made together
with the audit app's owner. AuditLog.log swallows its own failures; this helper never raises
either (the write already landed in SOFTECH) but a lost row is logged as an ERROR, not dropped.
"""
import json
import logging

logger = logging.getLogger(__name__)


def _staff(actor):
    """AuditLog.user is a StaffProfile; views hold a django User."""
    if actor is None:
        return None
    if hasattr(actor, 'full_name') and hasattr(actor, 'role'):
        return actor
    return getattr(actor, 'staff_profile', None)


def _plain(value):
    """JSON-safe copy (Decimal, dates → str) for the JSONFields."""
    if value is None:
        return None
    return json.loads(json.dumps(value, default=str))


def audit_softech_write(action, *, actor=None, obj=None, before=None, after=None, note='', **extra):
    try:
        from apps.audit.models import AuditLog
        staff = _staff(actor)
        if actor is not None and staff is None:      # still say who, even without a profile
            extra.setdefault('actor', str(getattr(actor, 'username', actor)))
        row = AuditLog.log(action, user=staff, obj=obj, old_data=_plain(before),
                           new_data=_plain(after), note=str(note or '')[:255],
                           extra=_plain(extra) or None)
    except Exception:
        row = None
    if row is None:
        logger.error('[softech_audit] %s NOT audited (obj=%r before=%r after=%r extra=%r)',
                     action, obj, before, after, extra)
    return row
