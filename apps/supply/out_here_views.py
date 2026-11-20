"""
apps/supply/out_here_views.py

C06: /supply «ناقص هنا · موجود هناك» — A/B items at zero at a retail branch today while another live branch holds
stock above its safety level (apps/purchasing/out_here.py). Read-only: no transfer, ISR or SOFTECH call is made here;
the transfer itself is made on the transfers screen.

  GET /api/supply/out-here/?branch=130,140&abc=A,B[&format=xlsx]

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


@api_view(['GET'])
@permission_classes([IsAuthenticated, CanOperateSupply])
def out_here(request):
    from apps.branches.models import Branch
    from apps.purchasing import out_here as oh
    requested = multi_values(request.query_params, 'branch')
    codes = branch_scope.narrow_codes(request.user, requested)
    asked = [c.upper() for c in multi_values(request.query_params, 'abc')]
    classes = tuple(c for c in oh.CLASSES if c in asked) or oh.CLASSES
    report = oh.build(dest_codes=codes, classes=classes)
    if (request.query_params.get('format') or '').lower() == 'xlsx':
        names = {b.softech_branch_id: (b.name_ar or b.name or '') for b in Branch.objects.only(
            'softech_branch_id', 'name', 'name_ar')}
        label = lambda c: f'{c} · {names[c]}' if names.get(c) else c          # never a bare code when named
        buf = io.BytesIO()
        neutralise_formulas(oh.workbook(report, label=label)).save(buf)
        resp = HttpResponse(buf.getvalue(),
                            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        resp['Content-Disposition'] = f'attachment; filename="out-here-in-stock-there-{timezone.localdate()}.xlsx"'
        return resp
    report['classes'] = list(classes)
    return Response(report)
