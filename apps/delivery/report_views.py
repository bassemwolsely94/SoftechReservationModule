"""
C20 — GET /api/delivery/small-orders/?date_from=&date_to=&branch=[&format=xlsx]

Delivery module (route check, like the other delivery reports) AND the analytics view grant: it is a
money report for branch managers / supervisors, not a rider screen. Branch-scoped (core.branch_scope);
?branch= narrows within the user's branches. Read-only; numbers from apps/delivery/small_orders.py.
"""
import datetime as dt

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core import branch_scope
from core.permissions import RouteModulePermission, matrix_permission

from . import small_orders as SO
from .views import _filter_branches

ANALYTICS_VIEW = matrix_permission('analytics')


def _dates(params):
    """(start, end) — default the last 7 full days; at most MAX_DAYS; None on a bad value."""
    today = timezone.localdate()
    try:
        end = dt.date.fromisoformat(params['date_to']) if params.get('date_to') else today - dt.timedelta(days=1)
        start = (dt.date.fromisoformat(params['date_from']) if params.get('date_from')
                 else end - dt.timedelta(days=6))
    except ValueError:
        return None
    if start > end:
        return None
    return max(start, end - dt.timedelta(days=SO.MAX_DAYS - 1)), end


@api_view(['GET'])
@permission_classes([IsAuthenticated, RouteModulePermission, ANALYTICS_VIEW])
def small_orders_report(request):
    from apps.customers.models import PurchaseHistory
    dates = _dates(request.query_params)
    if dates is None:
        return Response({'detail': 'date_from / date_to must be YYYY-MM-DD, from ≤ to'},
                        status=status.HTTP_400_BAD_REQUEST)
    qs = branch_scope.scope(PurchaseHistory.objects.all(), request.user)
    qs = _filter_branches(qs, request.query_params)
    rep = SO.build(qs, *dates)
    if request.query_params.get('format') == 'xlsx':
        resp = HttpResponse(SO.to_excel(rep),
                            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        resp['Content-Disposition'] = f'attachment; filename="delivery_small_orders_{dates[0]}_{dates[1]}.xlsx"'
        return resp
    return Response(rep)
