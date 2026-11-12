"""
apps/data_lifecycle/views.py — mounted at /api/data-health/ (design §6 Stage 5, §7)

  GET   growth/                    sizes, forecast, tables, upload types, folders, measures      viewers
  GET   problems/                  open data problems: counts only                                  viewers
  POST  refresh/                   one background snapshot (tables included); 202                   viewers
  GET   rules/                     the whole register with modes, periods, last runs                admin
  PATCH rules/<key>/               {mode?, keep_days?, reason} through policy.set_policy            admin
  POST  rules/<key>/preview/       runner.preview_rule; changes nothing but its own line           admin
  GET   held/?state=held|all       held files, newest first, at most 500                            admin
  GET   held/<id>/thumbnail/       a small JPEG, item images only; 404 otherwise                    admin
  POST  held/<id>/restore/         holding.restore                                                  admin

Viewers = `data_health` view in the matrix (admin, supervisor, quality manager). Admin-only routes are checked
here with IsAdminRole, not by a hidden button. Company-level by nature, no branch scoping (models.py). No SOFTECH.
Payloads are built in reports.py. Restore must not run inside an outer transaction (holding uses durable=True);
ATOMIC_REQUESTS is off.
"""
import io
import logging

from django.core.cache import cache
from django.db import connection
from django.http import Http404, HttpResponse
from PIL import Image
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.errors import public_error
from core.permissions import IsAdminRole, matrix_permission
from core.threads import start_thread

from . import holding, reports, runner
from .health import take_snapshot
from .models import HeldFile
from .policy import PolicyRefused, set_policy
from .register import RULES

logger = logging.getLogger('elrezeiky.sync')

REFRESH_KEY = reports.REFRESH_KEY
REFRESH_TTL = 900
THUMB_SIZE = (160, 160)
STRANDED_AR = 'تعذر إكمال الاسترجاع وبقي الملف سليمًا. تم تسجيل التفاصيل؛ راجع مسؤول النظام.'

VIEWERS = [IsAuthenticated, matrix_permission('data_health', post=('view',))]
ADMIN = [IsAuthenticated, IsAdminRole]


def _staff(request):
    return getattr(request.user, 'staff_profile', None)


def _rule_or_404(key):
    if key not in RULES:
        raise Http404
    return key


@api_view(['GET'])
@permission_classes(VIEWERS)
def growth(request):
    return Response(reports.growth_payload())


@api_view(['GET'])
@permission_classes(VIEWERS)
def problems(request):
    return Response(reports.problems_payload())


def _refresh_job():
    try:
        take_snapshot(include_tables=True)
    finally:
        cache.delete(REFRESH_KEY)
        connection.close()


@api_view(['POST'])
@permission_classes(VIEWERS)
def refresh(request):
    """One computation at a time (Review Focus 5): a second press while one runs gets the same answer."""
    if cache.add(REFRESH_KEY, 1, REFRESH_TTL):
        start_thread(_refresh_job, name='data-health-refresh')
    return Response({'refreshing': True}, status=status.HTTP_202_ACCEPTED)


@api_view(['GET'])
@permission_classes(ADMIN)
def rules(request):
    return Response(reports.rules_payload())


@api_view(['PATCH'])
@permission_classes(ADMIN)
def rule_update(request, key):
    _rule_or_404(key)
    data = request.data
    try:
        set_policy(key, mode=data.get('mode'), keep_days=data.get('keep_days'), user=_staff(request),
                   reason=data.get('reason') or '')
    except PolicyRefused as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as exc:
        return Response({'detail': public_error(request, exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return Response(reports.rule_row(key))


@api_view(['POST'])
@permission_classes(ADMIN)
def rule_preview(request, key):
    _rule_or_404(key)
    try:
        runner.preview_rule(key)
    except ValueError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as exc:
        return Response({'detail': public_error(request, exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return Response(reports.rule_row(key))


@api_view(['GET'])
@permission_classes(ADMIN)
def held(request):
    state = 'all' if request.query_params.get('state') == 'all' else 'held'
    return Response(reports.held_payload(state))


@api_view(['GET'])
@permission_classes(ADMIN)
def held_thumbnail(request, pk):
    """Item images only (reports.can_thumbnail); any refusal or error is a plain 404."""
    held_file = HeldFile.objects.filter(pk=pk).first()
    if (held_file is None or not reports.can_thumbnail(held_file)
            or held_file.restored_at is not None or held_file.purged_at is not None):
        raise Http404
    try:
        path = holding._inside(holding._hold_root(), held_file.hold_path)
        with Image.open(path) as image:
            image.thumbnail(THUMB_SIZE)
            out = io.BytesIO()
            image.convert('RGB').save(out, 'JPEG', quality=80)
    except Exception as exc:
        logger.warning('[data-health] thumbnail for held %s failed: %s', pk, type(exc).__name__)
        raise Http404 from None
    response = HttpResponse(out.getvalue(), content_type='image/jpeg')
    response['Cache-Control'] = 'private, no-store'
    return response


@api_view(['POST'])
@permission_classes(ADMIN)
def held_restore(request, pk):
    try:
        restored = holding.restore(pk, _staff(request))
    except holding.FileStranded:
        return Response({'detail': STRANDED_AR}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except holding.HoldError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as exc:
        return Response({'detail': public_error(request, exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return Response(reports.held_row(restored))
