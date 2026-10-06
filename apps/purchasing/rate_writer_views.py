"""
apps/purchasing/rate_writer_views.py — /supply workspace: Sales-Rate writeback (Feature 1) API.

The proposed → approved → executed lifecycle over SalesRatePush, feeding the
«معدلات» area of the /supply screen. All writes to SOFTECH stay gated behind
settings.SALES_RATE_WRITER_ENABLED (enforced in rate_writer.execute_push).

  GET  rates/pushes/            — recent pushes (summary)
  GET  rates/pushes/<pk>/       — one push + its lines
  POST rates/propose/          — build a dry-run proposal from the latest engine run
  POST rates/pushes/<pk>/approve/  — sign off a proposal (reviewer)
  POST rates/pushes/<pk>/execute/  — write the approved snapshot to SOFTECH (gated)
"""
import logging

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status as http
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.purchasing.models import SalesRatePush
from . import rate_writer

logger = logging.getLogger(__name__)

# Roles allowed to approve / execute a live SOFTECH rate write.
WRITE_ROLES = {'admin', 'supervisor', 'purchasing'}


def _staff(request):
    return getattr(request.user, 'staff_profile', None) or getattr(request.user, 'staffprofile', None)


def _can_write(request):
    """Roles above OR the SOFTECH groups in settings.SUPPLY_ERP_GROUPS (access.py)."""
    from apps.purchasing.access import can_supply_write
    return can_supply_write(request.user)


def _push_summary(p, names=None):
    from apps.purchasing.isr_fulfillment import user_label, user_names
    users = [u for u in (p.created_by, p.approved_by) if u]
    if names is None:
        names = user_names(u.username for u in users)

    def who(u):                                # '1509 · BASSEM' (code + SOFTECH userid)
        return user_label(u.username, names) if u else None
    return {
        'id': p.id, 'status': p.status, 'status_label': p.get_status_display(),
        'run_id': p.run_id, 'scope': p.scope,
        'method': p.method, 'method_label': p.get_method_display(), 'method_params': p.method_params,
        'target': p.target, 'target_label': p.get_target_display(),
        'branches': p.branches_count, 'eligible': p.eligible_count, 'skipped': p.skipped_count,
        'unreachable': p.unreachable_count, 'written': p.written_count,
        'verified': p.verified_count, 'reverted': p.reverted_count,
        'created_by': who(p.created_by), 'created_at': p.created_at,
        'approved_by': who(p.approved_by), 'approved_at': p.approved_at,
        'executed_at': p.executed_at, 'notes': p.notes,
    }


def _line_dict(ln):
    return {
        'id': ln.id, 'itemcode': ln.itemcode, 'item_name': ln.item_name,
        'branchcode': ln.branchcode, 'storecode': ln.storecode,
        'old': (float(ln.old_rate) if ln.old_rate is not None else None),
        'old_hq': (float(ln.old_rate_hq) if ln.old_rate_hq is not None else None),
        'new': float(ln.new_rate), 'eligible': ln.eligible, 'reason': ln.reason,
        'written': ln.written, 'verified': ln.verified, 'error': ln.error,
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def pushes_list(request):
    from apps.purchasing.isr_fulfillment import user_names
    qs = list(SalesRatePush.objects.select_related('created_by', 'approved_by').all()[:100])
    names = user_names(u.username for p in qs for u in (p.created_by, p.approved_by) if u)
    return Response({'results': [_push_summary(p, names) for p in qs],
                     'writer_enabled': rate_writer.writer_enabled(),
                     'can_write': _can_write(request)})


def _detail_payload(p):
    data = _push_summary(p)
    data['lines'] = [_line_dict(ln) for ln in p.lines.all().order_by('branchcode', 'itemcode')]
    return data


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def push_detail(request, pk):
    return Response(_detail_payload(get_object_or_404(SalesRatePush, pk=pk)))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def propose(request):
    """Build a dry-run proposal (READ-ONLY against SOFTECH) and persist it as a
    SalesRatePush(status=proposed). Body: {branch: [...], item: [...]} — both optional."""
    branch = request.data.get('branch') or None
    item = request.data.get('item') or None
    if isinstance(branch, str):
        branch = [b.strip() for b in branch.split(',') if b.strip()]
    if isinstance(item, str):
        item = [i.strip() for i in item.split(',') if i.strip()]
    method = (request.data.get('method') or rate_writer.METHOD_PIVOT).strip().lower()
    method_params = request.data.get('method_params') or {}
    if not isinstance(method_params, dict):
        method_params = {}
    target = (request.data.get('target') or rate_writer.TARGET_BOTH).strip().lower()
    try:
        plan = rate_writer.push(branch_filter=branch, item_filter=item,
                                dry_run=True, persist=True, created_by=request.user,
                                method=method, method_params=method_params, target=target)
    except ValueError as exc:
        return Response({'detail': str(exc)}, status=http.HTTP_400_BAD_REQUEST)
    return Response(_detail_payload(get_object_or_404(SalesRatePush, pk=plan['push_id'])),
                    status=http.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def approve(request, pk):
    if not _can_write(request):
        return Response({'detail': 'غير مصرح لك باعتماد دفعات المعدلات.'}, status=http.HTTP_403_FORBIDDEN)
    p = get_object_or_404(SalesRatePush, pk=pk)
    if p.status != SalesRatePush.STATUS_PROPOSED:
        return Response({'detail': f'لا يمكن اعتماد دفعة حالتها {p.get_status_display()}.'},
                        status=http.HTTP_400_BAD_REQUEST)
    p.status = SalesRatePush.STATUS_APPROVED
    p.approved_by = request.user
    p.approved_at = timezone.now()
    p.notes = request.data.get('notes', p.notes)
    p.save(update_fields=['status', 'approved_by', 'approved_at', 'notes'])
    return Response(_push_summary(p))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def execute(request, pk):
    if not _can_write(request):
        return Response({'detail': 'غير مصرح لك بتنفيذ الكتابة إلى SOFTECH.'}, status=http.HTTP_403_FORBIDDEN)
    p = get_object_or_404(SalesRatePush, pk=pk)
    try:
        rate_writer.execute_push(p, executed_by=request.user)
    except rate_writer.WriterDisabled as exc:
        return Response({'detail': str(exc), 'gated': True}, status=http.HTTP_409_CONFLICT)
    except ValueError as exc:
        return Response({'detail': str(exc)}, status=http.HTTP_400_BAD_REQUEST)
    return Response(_detail_payload(p))
