"""
One AuditLog row for an access event (socket refusal, export, bulk read), written through the
`audit_log` alias first - its own connection, so a rollback of the caller's transaction cannot
erase the row - then `default` (as the SOFTECH gate does). Never raises.
"""
import logging

log = logging.getLogger('elrezeiky.access')


def write_access_audit(action, user_id, note, extra, label='access'):
    """True when a row was saved on some alias, False when none took it."""
    from apps.audit.models import AuditLog
    from apps.users.models import StaffProfile

    from .softech_gate import _audit_aliases
    try:
        aliases = _audit_aliases()
    except Exception:
        log.warning('%s audit: no alias list', label, exc_info=True)
        return False
    for alias in aliases:
        try:
            staff = None
            if user_id is not None:
                staff = StaffProfile.objects.using(alias).filter(user_id=user_id).first()
            if AuditLog.log(action, user=staff, note=note, extra=extra, using=alias) is not None:
                return True
        except Exception as exc:
            # a test that does not list `audit_log` refuses it: the test's choice, quiet
            if type(exc).__name__ != 'DatabaseOperationForbidden':
                log.warning('%s audit write on %s failed - trying the next', label, alias,
                            exc_info=True)
    return False
