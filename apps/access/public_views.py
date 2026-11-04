"""Public (anonymous) endpoints under /api/public/ (security N6)."""
from django.conf import settings
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from core.public_guard import FORMS, issue_challenge


class ChallengeThrottle(AnonRateThrottle):
    """Per client IP: a person filling a form needs one or two challenges."""
    scope = 'public_challenge'

    def get_rate(self):
        return '60/hour'


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([ChallengeThrottle])
def challenge(request):
    """Proof-of-work challenge for a public form (core/public_guard.py)."""
    form = request.query_params.get('form', '')
    if form not in FORMS:
        return Response({'detail': 'نموذج غير معروف'}, status=400)
    data = issue_challenge(form)
    # the browser waits this long after fetching before it submits (frontend/src/utils/publicGuard.js)
    data['min_fill_seconds'] = int(settings.PUBLIC_MIN_FILL_SECONDS)
    return Response(data)


class HealthThrottle(AnonRateThrottle):
    """Per client IP: an uptime monitor pings every minute or five."""
    scope = 'public_health'

    def get_rate(self):
        return '300/hour'


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([HealthThrottle])
def health(request):
    """Liveness for nginx / release.sh / an external uptime monitor: 200 when this process can
    reach PostgreSQL, else 503. Says nothing else (no version, no scheduler, no SOFTECH)."""
    from django.db import connection
    try:
        with connection.cursor() as cur:
            cur.execute('SELECT 1')
            cur.fetchone()
    except Exception:
        resp = Response({'status': 'error'}, status=503)
    else:
        resp = Response({'status': 'ok'})
    resp['Cache-Control'] = 'no-store'
    return resp
