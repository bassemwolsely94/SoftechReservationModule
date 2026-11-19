"""
apps/insights/hq_exceptions_views.py

C32 «💰 استثناءات الأسبوع» — the same top list the Sunday digest sends, with links.

  GET /api/insights/exceptions/            the top 10 by EGP across the engines (cached 15 min)
  GET /api/insights/exceptions/?refresh=1  rebuild now (the screen's refresh button)

Read-only. Company-level money from every branch: the analytics grant AND an all-branch user
(core.branch_scope.sees_everything) — a branch-bound user gets 403 even with the grant.
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.permissions import matrix_permission

from . import hq_exceptions as HX


def _company_only(perm):
    from core.branch_scope import sees_everything

    class CompanyLevel(perm):
        message = 'استثناءات الأسبوع لمستخدمي كل الفروع (الإدارة والمركز الرئيسي) فقط.'

        def has_permission(self, request, view):
            return sees_everything(request.user) and super().has_permission(request, view)

    return CompanyLevel


HQ_EXCEPTIONS = _company_only(matrix_permission('analytics'))


@api_view(['GET'])
@permission_classes([IsAuthenticated, HQ_EXCEPTIONS])
def hq_exceptions(request):
    refresh = request.query_params.get('refresh') in ('1', 'true')
    return Response(HX.cached(refresh=refresh))
