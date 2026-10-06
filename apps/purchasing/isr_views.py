"""
apps/purchasing/isr_views.py — /supply workspace: ISR (طلب توريد) generation API.

proposed → approved (human review) → pushed (written to SOFTECH, stockisrm israpp=1
+ stockisr). Gated behind settings.ISR_WRITER_ENABLED (enforced in push_isr_record).

  GET  isr/pushes/           — recent ISR proposals (summary)
  GET  isr/pushes/<pk>/      — one proposal + its line snapshot
  POST isr/propose/         — build an ISR proposal for a branch (PG only, no SOFTECH)
  POST isr/pushes/<pk>/approve/  — reviewer signs off
  POST isr/pushes/<pk>/push/      — write the approved ISR to SOFTECH (gated, israpp=1)
"""
import logging

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status as http
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.purchasing.models import IsrPush
from apps.branches.models import Branch
from . import isr_writer

logger = logging.getLogger(__name__)
WRITE_ROLES = {'admin', 'supervisor', 'purchasing'}


def _staff(request):
    return getattr(request.user, 'staff_profile', None) or getattr(request.user, 'staffprofile', None)


def _can_write(request):
    """Roles above OR the SOFTECH groups in settings.SUPPLY_ERP_GROUPS (access.py)."""
    from apps.purchasing.access import can_supply_write
    return can_supply_write(request.user)


def _user_label(user, names):
    """Our usernames are SOFTECH user codes → '1509 · BASSEM' (code + SOFTECH userid)."""
    from apps.purchasing.isr_fulfillment import user_label
    return user_label(user.username, names) if user else None


def _summary(p, names=None):
    if names is None:
        from apps.purchasing.isr_fulfillment import user_names
        names = user_names(u.username for u in (p.created_by, p.approved_by) if u)
    return {
        'id': p.id, 'status': p.status, 'status_label': p.get_status_display(),
        'branchcode': p.branchcode, 'branch_name': (p.branch.name if p.branch_id else ''),
        'dest_branchcode': p.dest_branchcode, 'kind': p.kind, 'kind_label': p.get_kind_display(),
        'linked_push_id': p.linked_push_id,
        'run_id': p.run_id, 'isrdocnumber': p.isrdocnumber,
        'coverage_months': p.coverage_months,
        'line_count': p.line_count, 'docvalue': float(p.docvalue),
        'created_by': _user_label(p.created_by, names), 'created_at': p.created_at,
        'approved_by': _user_label(p.approved_by, names), 'approved_at': p.approved_at,
        'pushed_at': p.pushed_at, 'error': p.error,
        'origin_isr': p.origin_isr, 'notes': p.notes,
        'origin_request_id': p.origin_request_id, 'origin_donor': p.origin_donor,
    }


def _detail(p):
    d = _summary(p)
    d['lines'] = p.lines_snapshot or []
    return d


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def isr_list(request):
    from apps.purchasing.isr_fulfillment import user_names
    qs = list(IsrPush.objects.select_related('branch', 'created_by', 'approved_by').all()[:100])
    names = user_names(u.username for p in qs for u in (p.created_by, p.approved_by) if u)
    return Response({'results': [_summary(p, names) for p in qs],
                     'writer_enabled': isr_writer.writer_enabled(),
                     'can_write': _can_write(request)})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def isr_detail(request, pk):
    return Response(_detail(get_object_or_404(IsrPush, pk=pk)))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def isr_propose(request):
    """Build an ISR proposal for a branch (READ-ONLY vs SOFTECH — engine gaps + item
    master). Persists an IsrPush(proposed) with the reviewed line snapshot."""
    branchcode = str(request.data.get('branch') or '').strip()
    if not branchcode:
        return Response({'detail': 'حدد الفرع.'}, status=http.HTTP_400_BAD_REQUEST)
    max_lines = request.data.get('max_lines') or None
    from_hq = bool(request.data.get('from_hq'))   # HQ→branch vs branch self-request
    cov = request.data.get('coverage_months')
    try:
        cov = float(cov) if cov not in (None, '', 0, '0') else None
    except (TypeError, ValueError):
        cov = None
    try:
        p = isr_writer.create_proposal(branchcode, created_by=request.user, from_hq=from_hq,
                                       max_lines=(int(max_lines) if max_lines else None),
                                       coverage_months=cov)
    except ValueError as exc:
        return Response({'detail': str(exc)}, status=http.HTTP_400_BAD_REQUEST)
    if p is None:
        return Response({'detail': 'لا توجد أصناف ناقصة (gap>0) لهذا الفرع في آخر تشغيل.'},
                        status=http.HTTP_400_BAD_REQUEST)
    return Response(_detail(p), status=http.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def isr_transfer_preview(request):
    """Available (surplus A → deficit B) pairs from the latest transfer-recommendation
    run — for the /supply inter-branch picker. READ-ONLY."""
    from collections import defaultdict
    from apps.purchasing.models import TransferRecommendationRun, TransferRecommendation
    run = (TransferRecommendationRun.objects.filter(status='success').order_by('-id').first())
    if run is None:
        return Response({'run_id': None, 'pairs': []})
    agg = defaultdict(lambda: {'items': 0, 'qty': 0.0, 'value': 0.0})
    for r in (TransferRecommendation.objects.filter(run=run)
              .select_related('from_branch', 'to_branch')
              .only('quantity', 'estimated_value',
                    'from_branch__softech_branch_id', 'from_branch__name',
                    'to_branch__softech_branch_id', 'to_branch__name')):
        if not (r.from_branch_id and r.to_branch_id):
            continue
        k = (r.from_branch.softech_branch_id, r.from_branch.name,
             r.to_branch.softech_branch_id, r.to_branch.name)
        a = agg[k]
        a['items'] += 1
        a['qty'] += float(r.quantity or 0)
        a['value'] += float(r.estimated_value or 0)
    pairs = [{'from': k[0], 'from_name': k[1], 'to': k[2], 'to_name': k[3],
              'items': v['items'], 'qty': round(v['qty'], 1), 'value': round(v['value'], 0)}
             for k, v in agg.items()]
    pairs.sort(key=lambda p: -p['value'])
    return Response({'run_id': run.id, 'pairs': pairs})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def isr_transfer(request):
    """Create the two linked ISR proposals (A→HQ, HQ→B) for one or all deficit↔surplus
    pairs from the latest transfer-recommendation run."""
    if not _can_write(request):
        return Response({'detail': 'غير مصرح لك بتوليد التوزيعات.'}, status=http.HTTP_403_FORBIDDEN)
    try:
        created = isr_writer.generate_transfers_from_run(
            from_branch=(request.data.get('from') or None),
            to_branch=(request.data.get('to') or None),
            max_pairs=(int(request.data['max_pairs']) if request.data.get('max_pairs') else None),
            created_by=request.user)
    except ValueError as exc:
        return Response({'detail': str(exc)}, status=http.HTTP_400_BAD_REQUEST)
    return Response({'created': created, 'count': len(created)}, status=http.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def distribution_preview(request):
    """L3 توزيعة suggestions from the latest run: summary + sample. READ-ONLY."""
    from apps.purchasing import distribution
    cats = request.query_params.getlist('category') or None
    try:
        sugs = distribution.analyze(categories=cats, limit=int(request.query_params.get('limit', 300)))
        summ = distribution.summary()
    except ValueError as exc:
        return Response({'detail': str(exc)}, status=http.HTTP_400_BAD_REQUEST)
    return Response({'summary': summ, 'suggestions': sugs, 'can_write': _can_write(request)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def distribution_generate(request):
    """Turn توزيعة suggestions into ISR proposals (HQ→branch, or A→HQ→branch)."""
    if not _can_write(request):
        return Response({'detail': 'غير مصرح لك بتوليد التوزيعة.'}, status=http.HTTP_403_FORBIDDEN)
    cats = request.data.get('categories') or None
    limit = int(request.data['limit']) if request.data.get('limit') else None
    try:
        created = isr_writer.create_distribution_proposals(
            categories=cats, limit=limit, created_by=request.user)
    except ValueError as exc:
        return Response({'detail': str(exc)}, status=http.HTTP_400_BAD_REQUEST)
    return Response({'created': created, 'count': len(created)}, status=http.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def isr_approve(request, pk):
    if not _can_write(request):
        return Response({'detail': 'غير مصرح لك باعتماد طلبات التوريد.'}, status=http.HTTP_403_FORBIDDEN)
    p = get_object_or_404(IsrPush, pk=pk)
    if p.status != IsrPush.STATUS_PROPOSED:
        return Response({'detail': f'لا يمكن اعتماد طلب حالته {p.get_status_display()}.'},
                        status=http.HTTP_400_BAD_REQUEST)
    p.status = IsrPush.STATUS_APPROVED
    p.approved_by = request.user
    p.approved_at = timezone.now()
    p.notes = request.data.get('notes', p.notes)
    p.save(update_fields=['status', 'approved_by', 'approved_at', 'notes'])
    return Response(_summary(p))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def isr_push(request, pk):
    if not _can_write(request):
        return Response({'detail': 'غير مصرح لك بالترحيل إلى SOFTECH.'}, status=http.HTTP_403_FORBIDDEN)
    p = get_object_or_404(IsrPush, pk=pk)
    try:
        isr_writer.push_isr_record(p, executed_by=request.user)
    except isr_writer.WriterDisabled as exc:
        return Response({'detail': str(exc), 'gated': True}, status=http.HTTP_409_CONFLICT)
    except ValueError as exc:
        return Response({'detail': str(exc)}, status=http.HTTP_400_BAD_REQUEST)
    return Response(_detail(p))


# ── تلبية طلبات الفروع — ISR fulfilment plan (READ-ONLY, isr_fulfillment.py) ────────
FULFIL_CACHE_SECONDS = 60 * 60


def _can_view_fulfilment(request):
    from apps.purchasing.access import can_run_engine, can_supply_write
    return can_supply_write(request.user) or can_run_engine(request.user)


def _fulfil_inputs(request):
    """(isr_numbers, plan settings {months, fill, basis}) from the body — ValueError on bad input."""
    from apps.purchasing import isr_fulfillment as F
    numbers = F.parse_isr_numbers(request.data.get('isrs'))
    return numbers, F.plan_settings(request.data)


def _fulfil_snapshot(request, numbers):
    """Reuse the snapshot the screen already read (token) when it covers the same ISRs —
    re-planning at a new coverage then needs no SOFTECH round trip — else read fresh."""
    import uuid
    from django.core.cache import cache
    from apps.purchasing import isr_fulfillment as F
    token = str(request.data.get('token') or '')
    if token and not request.data.get('refresh'):
        snap = cache.get(f'isr_fulfil:{token}')
        if snap and snap.get('isr_numbers') == numbers:
            return token, snap
    snap = F.collect(numbers)
    token = uuid.uuid4().hex
    cache.set(f'isr_fulfil:{token}', snap, FULFIL_CACHE_SECONDS)
    logger.info('isr fulfilment read by %s: %s', request.user, ','.join(numbers))
    return token, snap


def _fulfil_error(exc):
    from apps.purchasing import isr_fulfillment as F
    if isinstance(exc, F.IsrNotFound):
        return Response({'detail': str(exc), 'missing': exc.missing}, status=http.HTTP_404_NOT_FOUND)
    return Response({'detail': str(exc)}, status=http.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def isr_fulfilment(request):
    """Body {isrs: '261609, 2615043' | [..], coverage: 1.5, token?, refresh?} → the plan."""
    from apps.purchasing import isr_fulfillment as F
    if not _can_view_fulfilment(request):
        return Response({'detail': 'غير مصرح لك.'}, status=http.HTTP_403_FORBIDDEN)
    try:
        numbers, cov = _fulfil_inputs(request)
        token, snap = _fulfil_snapshot(request, numbers)
    except ValueError as exc:
        return _fulfil_error(exc)
    plan = F.compute(snap, **cov)
    plan['token'] = token
    plan['returns'] = F.returns_for(numbers)
    plan['can_write'] = _can_write(request)
    return Response(plan)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def isr_fulfilment_recent(request):
    """Picker: ISRs raised by branches in the last ?days= (default 14, max 90)."""
    from apps.purchasing import isr_fulfillment as F
    if not _can_view_fulfilment(request):
        return Response({'detail': 'غير مصرح لك.'}, status=http.HTTP_403_FORBIDDEN)
    try:
        days = int(request.query_params.get('days') or 14)
    except (TypeError, ValueError):
        return Response({'detail': 'عدد الأيام غير صالح.'}, status=http.HTTP_400_BAD_REQUEST)
    try:
        rows = F.recent_branch_isrs(days)
    except Exception as exc:          # server 100 unreachable — screen falls back to typing
        logger.warning('isr fulfilment recent list failed: %s', exc)
        return Response({'detail': 'تعذّر الاتصال بسيرفر الرئيسي لقراءة الطلبات.'},
                        status=http.HTTP_503_SERVICE_UNAVAILABLE)
    return Response({'days': max(1, min(days, F.RECENT_MAX_DAYS)), 'results': rows})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def isr_fulfilment_proposals(request):
    """Body {isrs, coverage, isr?} → donor→HQ return proposals (PROPOSED, PG only) for the
    plan's «from branches» quantities. Always re-reads live stock first, so a proposal is
    never built from a stale screen. SOFTECH is written later by approve → push."""
    from apps.purchasing import isr_fulfillment as F
    if not _can_write(request):
        return Response({'detail': 'غير مصرح لك بإنشاء مقترحات التحويل.'}, status=http.HTTP_403_FORBIDDEN)
    try:
        numbers, cov = _fulfil_inputs(request)
    except ValueError as exc:
        return _fulfil_error(exc)
    only = str(request.data.get('isr') or '').strip() or None
    if only and only not in numbers:
        return Response({'detail': 'الطلب المحدد ليس ضمن الطلبات المعروضة.'}, status=http.HTTP_400_BAD_REQUEST)
    try:
        snap = F.collect(numbers)                       # fresh read — never a cached snapshot
    except ValueError as exc:
        return _fulfil_error(exc)
    import uuid
    from django.core.cache import cache
    token = uuid.uuid4().hex
    cache.set(f'isr_fulfil:{token}', snap, FULFIL_CACHE_SECONDS)
    result = F.create_donor_returns(snap, cov['months'], only_isr=only, created_by=request.user,
                                    fill=cov['fill'], basis=cov['basis'])
    logger.info('isr fulfilment returns by %s for %s: created=%s skipped=%s', request.user,
                only or ','.join(numbers), [c['id'] for c in result['created']], result['skipped'])
    plan = F.compute(snap, **cov)
    plan.update(token=token, returns=F.returns_for(numbers), can_write=True)
    return Response({**result, 'plan': plan},
                    status=http.HTTP_201_CREATED if result['created'] else http.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def isr_fulfilment_export(request):
    """Same body → the formula-driven Excel workbook (same snapshot as the screen)."""
    import io
    from django.http import HttpResponse
    from apps.purchasing import isr_fulfillment as F
    if not _can_view_fulfilment(request):
        return Response({'detail': 'غير مصرح لك.'}, status=http.HTTP_403_FORBIDDEN)
    try:
        numbers, cov = _fulfil_inputs(request)
        _, snap = _fulfil_snapshot(request, numbers)
    except ValueError as exc:
        return _fulfil_error(exc)
    buf = io.BytesIO()
    F.build_workbook(snap, **cov).save(buf)
    resp = HttpResponse(buf.getvalue(),
                        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = f'attachment; filename="{F.workbook_filename(snap)}"'
    return resp
