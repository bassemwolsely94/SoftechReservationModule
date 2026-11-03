"""Public (anonymous) endpoints under /api/public/ (security N6)."""
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
    return Response(issue_challenge(form))
