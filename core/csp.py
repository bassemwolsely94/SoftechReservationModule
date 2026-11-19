"""
core/csp.py — POST /api/csp-report/ (security Batch 6, W-9).

The SPA's Content-Security-Policy (deploy/nginx-csp.conf; enforced since D-04, one switch back to
report-only) has report-uri here: browsers report what the policy blocked (enforce) or would block
(report-only), and we log it as elrezeiky.csp — `manage.py csp_report_summary` groups the log.
Public (browsers send no credentials), throttled per IP, body capped, nothing stored — log only.
"""
import json
import logging
import re
from urllib.parse import urlsplit

from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from core.limits import limits_cache

logger = logging.getLogger('elrezeiky.csp')

MAX_REPORT_BYTES = 16 * 1024
_FIELDS = ('document-uri', 'violated-directive', 'effective-directive', 'blocked-uri',
           'source-file', 'line-number')
# The browser says whether it blocked ("enforce") or only reported ("report"); the log line says
# which, so a summary can tell real breakage from report-only noise.
_DISPOSITIONS = {'enforce': 'enforce', 'report': 'report-only'}


class CspReportThrottle(AnonRateThrottle):
    scope = 'csp_report'
    cache = limits_cache   # fail-closed security counters (core/limits.py)


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
        disposition = _DISPOSITIONS.get(str(report.get('disposition', '')).lower(), 'unknown')
        logger.warning('CSP (%s) %s', disposition, ' · '.join(
            f'{k}={str(report.get(k))[:200]}' for k in _FIELDS if report.get(k) is not None))
    return Response(status=204)


# ── Reading the log back (D-04): `manage.py csp_report_summary` ─────────────────────────────────
# One log line per report (settings.LOGGING 'verbose'): "WARNING 2026-11-19 10:00:00,123 csp CSP
# (enforce) document-uri=… · effective-directive=… · blocked-uri=…". A journalctl prefix is fine.
_LINE = re.compile(r'(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)[,.]\d+ \S+ CSP \(([^)]*)\) (.*)$')
# Sources a browser extension or the browser itself injects — not our page; never allow-listed.
NOISE_SCHEMES = frozenset({'chrome-extension', 'moz-extension', 'safari-extension', 'safari-web-extension',
                           'ms-browser-extension', 'webkit-masked-url', 'about'})


def parse_report_line(line):
    """One log line → {'at', 'mode', field: value…}, or None for any other line."""
    m = _LINE.search(line.rstrip('\r\n'))
    if not m:
        return None
    row = {'at': m.group(1), 'mode': m.group(2)}
    for part in m.group(3).split(' · '):
        key, sep, value = part.partition('=')
        if sep and key in _FIELDS:
            row[key] = value
    return row


def _blocked(uri):
    """Group key for the blocked source: an origin for URLs, the keyword otherwise (inline, eval, data…)."""
    uri = (uri or '').strip()
    parts = urlsplit(uri)
    if parts.scheme in ('http', 'https', 'ws', 'wss') and parts.netloc:
        return f'{parts.scheme}://{parts.netloc}'
    if parts.scheme and parts.scheme not in ('inline', 'eval'):
        return f'{parts.scheme}:'
    return uri or '(none)'


def _page(uri):
    """Group key for the page: its path with ids folded (/reservations/123 → /reservations/:id), no query."""
    path = urlsplit(uri or '').path or '/'
    return re.sub(r'/\d+(?=/|$)', '/:id', path)


def classify(row):
    """'ignore — extension' for what a browser extension injects; 'review' for everything else."""
    for key in ('blocked-uri', 'source-file'):
        value = (row.get(key) or '').strip().lower()
        if value.split(':', 1)[0] in NOISE_SCHEMES:
            return 'ignore — extension / browser'
    return 'review'


def summarize(lines):
    """Group report log lines by (directive, blocked source, page, mode): count, first and last seen."""
    groups = {}
    for line in lines:
        row = parse_report_line(line)
        if row is None:
            continue
        directive = (row.get('effective-directive') or row.get('violated-directive') or '?').split(' ')[0]
        key = (directive, _blocked(row.get('blocked-uri')), _page(row.get('document-uri')), row['mode'])
        g = groups.setdefault(key, {'directive': key[0], 'blocked': key[1], 'page': key[2], 'mode': key[3],
                                    'count': 0, 'first': row['at'], 'last': row['at'], 'verdict': classify(row)})
        g['count'] += 1
        g['first'] = min(g['first'], row['at'])
        g['last'] = max(g['last'], row['at'])
    return sorted(groups.values(), key=lambda g: (-g['count'], g['directive'], g['blocked'], g['page']))
