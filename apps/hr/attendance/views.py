"""
apps/hr/attendance/views.py — mounted at /api/hr-attendance/ (gated in access.py, not by the
module middleware; see EXEMPT_PREFIXES).
"""
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .access import Access


@api_view(['GET'])
def me(request):
    """The caller's attendance permissions; 403 unless they may open the module."""
    acc = Access(request)
    if not acc.can_view:
        return Response({'detail': 'غير مصرح'}, status=403)
    return Response(acc.as_dict())
