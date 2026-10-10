"""
B7 merge queue review API (apps/customers/duplicates.py). Roles: CUSTOMER_MERGE_ROLES (admin, supervisor,
call_center); maker-checker enforced in duplicates.approve. Nothing here writes SOFTECH.

  GET  /api/customers/merge-candidates/?status=proposed&strength=strong&q=07HD   summary + rows (≤ 200)
  POST /api/customers/merge-candidates/<id>/<mark|approve|reject|swap>/          reject needs {"reason"}
  POST /api/customers/merge-candidates/bulk/  {"action": "mark"|"approve", "strength": "strong", "limit": 100}
"""
from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from . import duplicates as DUP


def _profile(request):
    p = getattr(request.user, 'staff_profile', None)
    return p if (p and p.is_active) else None


class CanReviewMerges(BasePermission):
    def has_permission(self, request, view):
        p = _profile(request)
        return bool(p and p.role in DUP.roles())


def _row(r, names):
    return {'id': r.pk, 'old_pic': r.old_pic, 'main_pic': r.main_pic, 'main_auto_pic': r.main_auto_pic,
            'main_swapped': r.main_swapped, 'cluster': r.cluster, 'strength': r.strength,
            'strength_label': r.get_strength_display(), 'status': r.status, 'status_label': r.get_status_display(),
            'old_name': names.get(r.old_pic, ''), 'main_name': names.get(r.main_pic, ''), 'facts': r.facts,
            'marked_by': r.marked_by.full_name if r.marked_by_id else '', 'marked_by_id': r.marked_by_id,
            'approved_by': r.approved_by.full_name if r.approved_by_id else '',
            'rejected_by': r.rejected_by.full_name if r.rejected_by_id else '', 'reason': r.reason,
            'updated_at': r.updated_at.isoformat()}


@api_view(['GET'])
@permission_classes([CanReviewMerges])
def candidates(request):
    from .models import Customer, MergeCandidate as MC
    qs = MC.objects.select_related('marked_by', 'approved_by', 'rejected_by')
    st = request.query_params.get('status', 'proposed')
    if st != 'all':
        qs = qs.filter(status=st)
    if request.query_params.get('strength'):
        qs = qs.filter(strength=request.query_params['strength'])
    q = (request.query_params.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(old_pic__icontains=q) | Q(main_pic__icontains=q) | Q(cluster__icontains=q))
    rows = list(qs.order_by('cluster', 'old_pic')[:200])
    pics = {p for r in rows for p in (r.old_pic, r.main_pic)}
    names = dict(Customer.objects.filter(softech_pic__in=pics).values_list('softech_pic', 'name'))
    me = _profile(request)
    return Response({'summary': DUP.summary(), 'me': me.pk, 'total': qs.count(),
                     'rows': [_row(r, names) for r in rows]})


ACTIONS = {'mark': DUP.mark, 'approve': DUP.approve, 'swap': DUP.swap}


@api_view(['POST'])
@permission_classes([CanReviewMerges])
def act(request, pk, action):
    from .models import Customer
    user = _profile(request)
    try:
        if action == 'reject':
            r = DUP.reject(pk, user, request.data.get('reason'))
        elif action in ACTIONS:
            r = ACTIONS[action](pk, user)
        else:
            return Response({'detail': 'unknown action'}, status=status.HTTP_404_NOT_FOUND)
    except DUP.ReviewError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    names = dict(Customer.objects.filter(softech_pic__in=[r.old_pic, r.main_pic]).values_list('softech_pic', 'name'))
    return Response(_row(r, names))


@api_view(['POST'])
@permission_classes([CanReviewMerges])
def bulk(request):
    user = _profile(request)
    strength = request.data.get('strength', 'strong')
    try:
        limit = min(500, int(request.data.get('limit', 100)))
    except (TypeError, ValueError):
        limit = 100
    fn = {'mark': DUP.bulk_mark, 'approve': DUP.bulk_approve}.get(request.data.get('action'))
    if fn is None:
        return Response({'detail': 'action: mark | approve'}, status=status.HTTP_400_BAD_REQUEST)
    return Response({'done': fn(user, strength=strength, limit=limit)})
