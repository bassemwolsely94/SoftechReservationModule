"""
apps/supply/missing_bonus_views.py

C18: /supply «بونص ناقص» — paid doc-10 receipts that came with fewer free units than the same supplier's last 3
deliveries of the item gave (apps/procurement/missing_bonus.py). A read-only review list to claim the bonus before
paying; nothing is written, no SOFTECH call.

  GET  /api/supply/missing-bonus/?days=30&branch=130,140&changed=1   the list (JSON)
  GET  /api/supply/missing-bonus/export/?…                            the same list as Excel
  POST /api/supply/missing-bonus/export/jobs/?…                       that Excel as a background job (performance
                                                                      Stage 4, view_kinds 'v:supply_missing_bonus')

Supply view rights (CanOperateSupply = purchasing/view); receiving branches narrowed with core.branch_scope.
"""
import io

from django.http import HttpResponse
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core import branch_scope
from core.export_safety import neutralise_formulas
from core.multi_filter import multi_values

from .permissions import CanOperateSupply

XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def _days(raw):
    from apps.procurement.missing_bonus import LOOKBACK_DAYS
    try:
        return int(raw)
    except (TypeError, ValueError):
        return LOOKBACK_DAYS


def _report(request):
    from apps.procurement import missing_bonus as mb
    qp = request.query_params
    codes = branch_scope.narrow_codes(request.user, multi_values(qp, 'branch'))
    return mb.build(days=_days(qp.get('days')), branch_codes=codes, include_changed=qp.get('changed') == '1')


def _labeller():
    from apps.branches.models import Branch
    names = {b.softech_branch_id: (b.name_ar or b.name or '')
             for b in Branch.objects.only('softech_branch_id', 'name', 'name_ar')}

    def label(code):
        return f'{code} · {names[code]}' if names.get(code) else code
    return label


@api_view(['GET'])
@permission_classes([IsAuthenticated, CanOperateSupply])
def missing_bonus(request):
    return Response(_report(request))


@api_view(['GET'])
@permission_classes([IsAuthenticated, CanOperateSupply])
def missing_bonus_export(request):
    from apps.procurement import missing_bonus as mb
    buf = io.BytesIO()
    neutralise_formulas(mb.workbook(_report(request), label=_labeller())).save(buf)
    resp = HttpResponse(buf.getvalue(), content_type=XLSX)
    resp['Content-Disposition'] = f'attachment; filename="missing-bonus-{timezone.localdate()}.xlsx"'
    return resp
