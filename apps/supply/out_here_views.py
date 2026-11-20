"""
apps/supply/out_here_views.py

C06: /supply «ناقص هنا · موجود هناك» — A/B items at zero at a retail branch today while another live branch holds
stock above its safety level (apps/purchasing/out_here.py). Read-only: no transfer, ISR or SOFTECH call is made here;
the transfer itself is made on the transfers screen.

  GET  /api/supply/out-here/?branch=130,140&abc=A,B      the list (JSON)
  GET  /api/supply/out-here/export/?…                     the same list as Excel
  POST /api/supply/out-here/export/jobs/?…                that Excel as a background job (performance Stage 4,
                                                          export_jobs.view_kinds 'v:supply_out_here') — the screen
                                                          uses this one

Supply view rights (CanOperateSupply = purchasing/view). Destinations are narrowed to the user's branches
(core.branch_scope); the sources shown may be any live branch — that is the point of the list.
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


def _report(request):
    from apps.purchasing import out_here as oh
    qp = request.query_params
    codes = branch_scope.narrow_codes(request.user, multi_values(qp, 'branch'))
    asked = [c.upper() for c in multi_values(qp, 'abc')]
    classes = tuple(c for c in oh.CLASSES if c in asked) or oh.CLASSES
    report = oh.build(dest_codes=codes, classes=classes)
    report['classes'] = list(classes)
    return report


def branch_labeller():
    """code → «code · name» from the live table (never a bare code when the branch has a name)."""
    from apps.branches.models import Branch
    names = {b.softech_branch_id: (b.name_ar or b.name or '')
             for b in Branch.objects.only('softech_branch_id', 'name', 'name_ar')}

    def label(code):
        return f'{code} · {names[code]}' if names.get(code) else code
    return label


@api_view(['GET'])
@permission_classes([IsAuthenticated, CanOperateSupply])
def out_here(request):
    return Response(_report(request))


@api_view(['GET'])
@permission_classes([IsAuthenticated, CanOperateSupply])
def out_here_export(request):
    from apps.purchasing import out_here as oh
    buf = io.BytesIO()
    neutralise_formulas(oh.workbook(_report(request), label=branch_labeller())).save(buf)
    resp = HttpResponse(buf.getvalue(), content_type=XLSX)
    resp['Content-Disposition'] = f'attachment; filename="out-here-in-stock-there-{timezone.localdate()}.xlsx"'
    return resp
