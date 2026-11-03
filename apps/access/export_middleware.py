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
from django.http import JsonResponse
from django.utils import timezone

from core.export_stamp import ExportMark, stamp_ooxml

from . import bulk_read, policy
from .audit import write_access_audit

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


def _is_attachment(response):
    value = response.get('Content-Disposition') or ''
    return value.split(';')[0].strip().lower() == 'attachment'


def _is_export(request, response, body):
    """2xx only (a 304 / 206 / 4xx carrying the header is not a download), HEAD never."""
    if request.method == 'HEAD' or not 200 <= response.status_code < 300:
        return False
    if _is_attachment(response):
        return True
    return response.status_code == 200 and policy.is_export(request.path, request.method,
                                                            request.GET, body)


class ExportAuditMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        state = None
        try:
            state = self._before(request)
        except Exception:
            log.error('export audit: before-view step failed (%s)', getattr(request, 'path', '?'),
                      exc_info=True)
        if state and state.get('deny') is not None:
            return state['deny']
        response = self.get_response(request)
        try:
            self._after(request, response, state or {})
        except Exception:
            log.error('export audit failed (%s)', getattr(request, 'path', '?'), exc_info=True)
        return response

    def _before(self, request):
        """What has to be read before the view runs: the body of a body-selected export (the
        view consumes the stream). The same parse the zone policy uses (fails closed)."""
        from .policy_middleware import _json_body
        state = {'body': _json_body(request)}
        state['deny'] = self._bulk_block(request, state['body'])
        return state

    def _bulk_block(self, request, body):
        """A user blocked for bulk reading (enforce only) gets no customer reads and no exports."""
        if bulk_read.mode() != 'enforce':
            return None
        reads = request.method in ('GET', 'HEAD', 'OPTIONS') and bulk_read.is_bulk_path(request.path)
        if not (reads or policy.is_export(request.path, request.method, request.GET, body)):
            return None
        from .policy_middleware import _user
        user = _user(request)
        if user is None or not getattr(user, 'is_authenticated', False) or not bulk_read.blocked(user):
            return None
        return JsonResponse({'detail': bulk_read.BLOCK_MESSAGE, 'reason': 'bulk_read'}, status=403)

    def _count_bulk(self, request, response, user, export):
        if bulk_read.mode() == 'off':
            return
        rows = 0
        if (request.method == 'GET' and bulk_read.is_bulk_path(request.path)
                and 200 <= response.status_code < 300):
            rows = bulk_read.rows_in(response)
        if not (rows or export):
            return
        kind, count = bulk_read.record_counted(user, rows=rows, export=export)
        if kind:
            bulk_read.alert(user, kind, request, count)

    def _after(self, request, response, state):
        export = _is_export(request, response, state.get('body'))
        from .policy_middleware import _user
        user = _user(request)
        if user is None or not getattr(user, 'is_authenticated', False):
            return
        try:
            self._count_bulk(request, response, user, export)
        except Exception:
            log.error('bulk read count failed (%s)', request.path, exc_info=True)
        if not export:
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
        if not write_access_audit(AUDIT_ACTION, user.pk, f'{export_id} {request.path}'[:255],
                                  extra, label='export'):
            log.error('export audit row lost (%s %s %s)', user.pk, export_id, request.path)
        max_bytes = getattr(settings, 'EXPORT_STAMP_MAX_BYTES', DEFAULT_MAX_BYTES)
        if streaming or content_type not in STAMPABLE or size > max_bytes:
            return
        device_label = ''
        if device is not None:
            name = getattr(device, 'name', None)
            device_label = f'{name} ({device.public_id})' if name else str(device.public_id or '')
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
