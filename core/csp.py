"""
core/csp.py — POST /api/csp-report/ (security Batch 6, W-9).

The SPA ships Content-Security-Policy-Report-Only (deploy/nginx.conf): browsers report what the
policy WOULD block here, and we log it so the policy can be tuned before it is enforced. Public
(browsers send no credentials), throttled per IP, body capped, nothing stored — log only.
"""
import json
import logging

from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

logger = logging.getLogger('elrezeiky.csp')

MAX_REPORT_BYTES = 16 * 1024
_FIELDS = ('document-uri', 'violated-directive', 'effective-directive', 'blocked-uri',
           'source-file', 'line-number')


class CspReportThrottle(AnonRateThrottle):
    scope = 'csp_report'


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([CspReportThrottle])
def csp_report(request):
    body = request.body                           # raw: browsers send application/csp-report
    if len(body) > MAX_REPORT_BYTES:
        return Response(status=413)
    try:
        report = json.loads(body or b'{}')
        report = report.get('csp-report', report) if isinstance(report, dict) else {}
    except ValueError:
        report = {}
    if isinstance(report, dict) and report:
        logger.warning('CSP (report-only) %s', ' · '.join(
            f'{k}={str(report.get(k))[:200]}' for k in _FIELDS if report.get(k) is not None))
    return Response(status=204)
