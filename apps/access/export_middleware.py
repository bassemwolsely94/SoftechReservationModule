"""
Every export is audited; Excel and Word files are stamped (N5).

A response is an export when the request is one (policy.is_export) and it answered 200, or when
it carries `Content-Disposition: attachment`. Each export gets one `export_taken` AuditLog row
(through the `audit_log` alias, so a rollback of the request cannot erase it), an
`X-ElR-Export-Id` header, and - for an in-memory xlsx / docx no larger than
EXPORT_STAMP_MAX_BYTES - the who / when / where stamp in its document properties.
Anonymous responses are skipped. Nothing here ever raises out of the middleware.
"""
import logging
import uuid

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from core.export_stamp import ExportMark, stamp_ooxml

from . import policy

log = logging.getLogger('elrezeiky.access')

AUDIT_ACTION = 'export_taken'
STAMP_WARN_SECONDS = 600
DEFAULT_MAX_BYTES = 50 * 1024 * 1024
STAMPABLE = {
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}


def _content_type(response):
    return (response.get('Content-Type') or '').split(';')[0].strip().lower()


def _is_export(request, response):
    if 'attachment' in (response.get('Content-Disposition') or '').lower():
        return True
    return response.status_code == 200 and policy.is_export(request.path, request.method,
                                                            request.GET)


def _write_audit(user, note_text, extra):
    """One `export_taken` row, through the `audit_log` alias first (as the SOFTECH gate does),
    then `default`. True when a row was saved. Never raises."""
    from apps.audit.models import AuditLog
    from apps.users.models import StaffProfile

    from .softech_gate import _audit_aliases
    for alias in _audit_aliases():
        try:
            staff = StaffProfile.objects.using(alias).filter(user_id=user.pk).first()
            if AuditLog.log(AUDIT_ACTION, user=staff, note=note_text, extra=extra,
                            using=alias) is not None:
                return True
        except Exception as exc:
            if type(exc).__name__ != 'DatabaseOperationForbidden':
                log.warning('export audit write on %s failed - trying the next', alias,
                            exc_info=True)
    return False


class ExportAuditMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            self._after(request, response)
        except Exception:
            log.error('export audit failed (%s)', getattr(request, 'path', '?'), exc_info=True)
        return response

    def _after(self, request, response):
        if not _is_export(request, response):
            return
        from .policy_middleware import _user
        user = _user(request)
        if user is None or not getattr(user, 'is_authenticated', False):
            return
        access = getattr(request, 'access', None)
        device = getattr(access, 'device', None)
        network = getattr(access, 'network', None)
        export_id = uuid.uuid4().hex[:16]
        streaming = getattr(response, 'streaming', False)
        content_type = _content_type(response)
        size = None if streaming else len(response.content)
        extra = {
            'export_id': export_id, 'path': request.path, 'zone': getattr(access, 'zone', None),
            'device_id': getattr(device, 'public_id', None), 'ip': getattr(network, 'ip', None),
            'content_type': content_type, 'bytes': size, 'username': user.get_username(),
        }
        response['X-ElR-Export-Id'] = export_id
        if not _write_audit(user, f'{export_id} {request.path}'[:255], extra):
            log.error('export audit row lost (%s %s %s)', user.pk, export_id, request.path)
        max_bytes = getattr(settings, 'EXPORT_STAMP_MAX_BYTES', DEFAULT_MAX_BYTES)
        if streaming or content_type not in STAMPABLE or size > max_bytes:
            return
        device_label = ''
        if device is not None:
            device_label = f'{device.name} ({device.public_id})'
        mark = ExportMark(export_id=export_id, username=user.get_username(),
                          at=timezone.localtime().isoformat(timespec='seconds'),
                          device=device_label, zone=extra['zone'] or '', ip=extra['ip'] or '')
        try:
            response.content = stamp_ooxml(response.content, mark)
        except ValueError:
            try:
                first = cache.add(f'access:export-stamp-fail:{content_type}', 1,
                                  STAMP_WARN_SECONDS)
            except Exception:
                first = True
            if first:
                log.warning('export stamp skipped: malformed %s (%s)', content_type, request.path)
            return
        response['Content-Length'] = str(len(response.content))
