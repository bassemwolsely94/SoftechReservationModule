"""
apps/insurance/audit.py

Thin, resilient helper for writing InsuranceAuditEvent rows.  Audit writes must
NEVER break the operation they record, so every call is wrapped — a failed audit
insert is logged, not raised.
"""
import logging

logger = logging.getLogger(__name__)


def _num(v):
    """JSON-safe number (Decimal → float), else pass through."""
    try:
        from decimal import Decimal
        if isinstance(v, Decimal):
            return float(v)
    except Exception:
        pass
    return v


def record_audit(claim, action, *, actor=None, summary='', target_type='',
                 target_ref='', reason='', before=None, after=None, meta=None):
    """
    Append one audit event.  `actor` is a users.StaffProfile (or None).
    before/after/meta are small JSON-serialisable dicts.  Returns the row or None.
    """
    from .models import InsuranceAuditEvent
    try:
        actor_name = ''
        if actor is not None:
            try:
                actor_name = str(actor)
            except Exception:
                actor_name = ''
        return InsuranceAuditEvent.objects.create(
            claim=claim,
            action=action,
            actor=actor,
            actor_name=actor_name[:150],
            summary=(summary or action)[:300],
            target_type=(target_type or '')[:30],
            target_ref=str(target_ref or '')[:60],
            reason=reason or '',
            before=before,
            after=after,
            meta=meta,
        )
    except Exception:
        logger.exception('[insurance-audit] failed to record %s on claim %s',
                         action, getattr(claim, 'pk', None))
        return None
