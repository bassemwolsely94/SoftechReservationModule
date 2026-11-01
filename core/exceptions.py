"""
DRF exception handler (REST_FRAMEWORK['EXCEPTION_HANDLER']).

N4: a SOFTECH gate refusal that no view caught answers 403 with its fixed Arabic copy and
code 'softech_zone' (the frontend can tell it from an ordinary 403 / a 500). Everything
else goes to DRF's default handler, unchanged.
"""
import sys

from rest_framework.response import Response
from rest_framework.views import exception_handler


def is_softech_refusal(exc) -> bool:
    """True for a gate refusal. config.sybase is not imported here: if it was never loaded,
    no refusal can exist (and a 404 must not start loading jpype)."""
    sybase = sys.modules.get('config.sybase')
    return sybase is not None and isinstance(
        exc, (sybase.SoftechAccessDenied, sybase.SoftechZoneWriteDenied))


def api_exception_handler(exc, context):
    if is_softech_refusal(exc):
        return Response({'detail': str(exc), 'code': 'softech_zone'}, status=403)
    return exception_handler(exc, context)
