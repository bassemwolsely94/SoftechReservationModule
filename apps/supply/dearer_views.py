"""
C17 «اشترينا أغلى» — GET /api/supply/bought-dearer/?month=YYYY-MM[&format=xlsx]

Purchasing grant (CanOperateSupply) AND an all-branch user: the report is company-level money
(HQ purchasing across every branch), so a branch-bound user is refused even with the grant.
Read-only; numbers from apps/supply/bought_dearer.py.
"""
import datetime as dt
import re

from django.core.cache import cache
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.branch_scope import sees_everything

from .permissions import CanOperateSupply

_MONTH = re.compile(r'^(\d{4})-(\d{2})$')
CACHE_SECONDS = 10 * 60


def _month(raw):
    """'YYYY-MM' → its 1st; empty → LAST month (the report is monthly and this month is still open)."""
    if not raw:
        return (timezone.localdate().replace(day=1) - dt.timedelta(days=1)).replace(day=1)
    m = _MONTH.match(str(raw).strip())
    if not m or not 1 <= int(m.group(2)) <= 12:
        return None
    return dt.date(int(m.group(1)), int(m.group(2)), 1)


@api_view(['GET'])
@permission_classes([IsAuthenticated, CanOperateSupply])
def bought_dearer(request):
    from apps.procurement import refresh
    from . import bought_dearer as BD
    if not sees_everything(request.user):
        return Response({'detail': 'التقرير على مستوى الشركة — لمستخدمي كل الفروع فقط.'},
                        status=status.HTTP_403_FORBIDDEN)
    month = _month(request.query_params.get('month'))
    if month is None:
        return Response({'detail': 'month must be YYYY-MM'}, status=status.HTTP_400_BAD_REQUEST)
    last = refresh.last_success()
    key = f'bought_dearer:{month:%Y-%m}:{last.pk if last else 0}'
    rep = cache.get(key)
    if rep is None:
        rep = BD.build(month)
        cache.set(key, rep, CACHE_SECONDS)
    if request.query_params.get('format') == 'xlsx':
        resp = HttpResponse(BD.to_excel(rep),
                            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        resp['Content-Disposition'] = f'attachment; filename="bought_dearer_{month:%Y-%m}.xlsx"'
        return resp
    return Response(rep)
