"""
apps/purchasing/branch_request_views.py — /supply «طلبات واتساب» API.

Branch requests pasted from WhatsApp groups → reviewed item lines → (a) the same
availability analysis + Excel as «تلبية طلبات الفروع», (b) the branch shortage list.
Logic lives in apps/supply/branch_requests.py; nothing here writes SOFTECH.

  GET   isr/branch-requests/                      list (+ branches for the picker)
  POST  isr/branch-requests/                      {branch, group_name, text} → parse + match
  GET   isr/branch-requests/<pk>/                 request + lines
  POST  isr/branch-requests/<pk>/text/            {text} → append more messages
  POST  isr/branch-requests/<pk>/ocr/             multipart image → OCR lines (flagged)
  PATCH isr/branch-requests/<pk>/lines/<lid>/     {item_id|qty|qty_unit|kind|all_variants|confirmed}
  GET   isr/branch-requests/<pk>/lines/<lid>/search/?q=  other catalog items for that line
  POST  isr/branch-requests/<pk>/confirm-safe/    confirm every unflagged, well-scored line
  POST  isr/branch-requests/<pk>/confirm/         → branch shortage list (+ teach the matcher)
  POST  isr/branch-requests/<pk>/cancel/
  POST  isr/branch-requests/<pk>/analysis/        {coverage, token?, refresh?} → plan
  POST  isr/branch-requests/<pk>/analysis/export/ → xlsx

View: supply writers + engine runners. Change: supply writers (purchasing/access.py).
"""
import io
import logging
import uuid
from decimal import Decimal, InvalidOperation

from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status as http
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

logger = logging.getLogger(__name__)
CACHE_SECONDS = 60 * 60
# informational — never block «تأكيد الآمنة» (a remembered match was confirmed by a person
# before; close-spelling memories require identical numbers)
SAFE_FLAGS = {'urgent', 'learned_group', 'learned_fuzzy'}


def _can_view(request):
    from apps.purchasing.access import can_run_engine, can_supply_write
    return can_supply_write(request.user) or can_run_engine(request.user)


def _can_write(request):
    from apps.purchasing.access import can_supply_write
    return can_supply_write(request.user)


def _deny():
    return Response({'detail': 'غير مصرح لك.'}, status=http.HTTP_403_FORBIDDEN)


def _branches():
    from apps.purchasing.rate_writer import _eligible_branches
    return [{'code': b.softech_branch_id, 'name': b.name}
            for b in sorted(_eligible_branches(), key=lambda b: b.softech_branch_id)]


def _summary(req, names=None):
    from apps.purchasing.isr_fulfillment import user_label, user_names
    from apps.supply.models import BranchRequestLine as L
    if names is None:
        names = user_names([getattr(req.created_by, 'username', '')])
    items = [l for l in req.lines.all() if l.kind == L.KIND_ITEM]      # prefetched in the list
    return {
        'id': req.id, 'branch': req.branch.softech_branch_id, 'branch_name': req.branch.name,
        'group_name': req.group_name, 'status': req.status, 'status_label': req.get_status_display(),
        'items': len(items), 'confirmed': sum(1 for l in items if l.confirmed),
        'need_review': sum(1 for l in items if not l.confirmed),
        'shortage_list_id': req.shortage_list_id,
        'created_by': user_label(req.created_by.username, names) if req.created_by else None,
        'created_at': req.created_at,
    }


def _line(ln, stock, rate):
    from apps.supply.branch_requests import pack_hint, packs, strips_per_pack
    it = ln.item
    return {
        'id': ln.id, 'position': ln.position, 'msg_index': ln.msg_index, 'msg_sender': ln.msg_sender,
        'msg_time': ln.msg_time, 'from_ocr': ln.from_ocr, 'raw_text': ln.raw_text,
        'match_text': ln.match_text, 'kind': ln.kind, 'qty': float(ln.qty), 'qty_unit': ln.qty_unit,
        'qty_source': ln.qty_source, 'packs': packs(ln) if it else None,
        'strips_per_pack': strips_per_pack(it.name) if it else None,
        'pack_hint': pack_hint(ln.match_text, it.name) if it else None,
        'all_variants': ln.all_variants, 'score': ln.score, 'flags': ln.flags or [],
        'candidates': ln.candidates or [], 'confirmed': ln.confirmed, 'picked_by_user': ln.picked_by_user,
        'item': ({'id': it.id, 'code': it.softech_id, 'name': it.name,
                  'branch_stock': stock.get(it.id), 'network_rate': rate.get(it.id, 0.0)} if it else None),
        # every hand-picked item of the line (the item first), each with the line's qty
        'picks': ([{'id': p.id, 'code': p.softech_id, 'name': p.name, 'branch_stock': stock.get(p.id),
                    'network_rate': rate.get(p.id, 0.0)}
                   for p in [it] + [x for x in ln.extra_items.all() if x.id != it.id]] if it else []),
    }


def _detail(req, request=None):
    from apps.supply.branch_requests import _stock_and_rate
    lines = list(req.lines.select_related('item').prefetch_related('extra_items').order_by('position'))
    ids = [l.item_id for l in lines if l.item_id] + [x.id for l in lines for x in l.extra_items.all()]
    stock, rate = _stock_and_rate(ids, req.branch) if ids else ({}, {})
    d = _summary(req)
    d.update(lines=[_line(l, stock, rate) for l in lines], raw_text=req.raw_text,
             can_write=_can_write(request) if request is not None else False)
    return d


def _get(pk):
    from apps.supply.models import BranchRequest
    return get_object_or_404(BranchRequest.objects.select_related('branch', 'created_by'), pk=pk)


def _draft_or_400(req):
    from apps.supply.models import BranchRequest
    if req.status != BranchRequest.STATUS_DRAFT:
        return Response({'detail': f'الطلب {req.get_status_display()} — لا يمكن تعديله.'},
                        status=http.HTTP_400_BAD_REQUEST)
    return None


# ── list / create ───────────────────────────────────────────────────────────────
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def branch_requests(request):
    from apps.branches.models import Branch
    from apps.purchasing.isr_fulfillment import user_names
    from apps.supply import branch_requests as W
    from apps.supply.models import BranchRequest
    if request.method == 'GET':
        if not _can_view(request):
            return _deny()
        qs = list(BranchRequest.objects.select_related('branch', 'created_by')
                  .prefetch_related('lines')[:60])
        names = user_names(r.created_by.username for r in qs if r.created_by)
        return Response({'results': [_summary(r, names) for r in qs], 'branches': _branches(),
                         'can_write': _can_write(request)})
    if not _can_write(request):
        return _deny()
    code = str(request.data.get('branch') or '').strip()
    text = str(request.data.get('text') or '')
    if code not in {b['code'] for b in _branches()}:
        return Response({'detail': 'اختر الفرع.'}, status=http.HTTP_400_BAD_REQUEST)
    if not text.strip():
        return Response({'detail': 'الصق رسائل المجموعة أولاً.'}, status=http.HTTP_400_BAD_REQUEST)
    if len(text) > 60000:
        return Response({'detail': 'النص طويل جداً — الصق دفعات أصغر.'}, status=http.HTTP_400_BAD_REQUEST)
    req = BranchRequest.objects.create(
        branch=Branch.objects.get(softech_branch_id=code), raw_text=text,
        group_name=str(request.data.get('group_name') or '')[:200], created_by=request.user)
    n = W.build_lines(req, text)
    logger.info('branch request %s created by %s: %s lines', req.pk, request.user, n)
    return Response(_detail(req, request), status=http.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def branch_request_detail(request, pk):
    if not _can_view(request):
        return _deny()
    return Response(_detail(_get(pk), request))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def branch_request_text(request, pk):
    from apps.supply import branch_requests as W
    if not _can_write(request):
        return _deny()
    req = _get(pk)
    bad = _draft_or_400(req)
    if bad:
        return bad
    text = str(request.data.get('text') or '')
    if not text.strip():
        return Response({'detail': 'لا يوجد نص.'}, status=http.HTTP_400_BAD_REQUEST)
    W.build_lines(req, text)
    req.raw_text = (req.raw_text + '\n\n' + text).strip()
    req.save(update_fields=['raw_text'])
    return Response(_detail(req, request))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def branch_request_ocr(request, pk):
    from django.conf import settings
    from apps.supply import branch_requests as W
    from apps.vision.ocr import pick_primary, run_engines
    if not _can_write(request):
        return _deny()
    req = _get(pk)
    bad = _draft_or_400(req)
    if bad:
        return bad
    image = request.FILES.get('image')
    if image is None:
        return Response({'detail': 'لم يتم رفع صورة.'}, status=http.HTTP_400_BAD_REQUEST)
    readings = run_engines(image, api_key=getattr(settings, 'GEMINI_API_KEY', '') or '')
    engine, primary = pick_primary(readings)
    if not primary:
        return Response({'detail': 'تعذّرت قراءة الصورة — لا يوجد محرك OCR متاح.'},
                        status=http.HTTP_503_SERVICE_UNAVAILABLE)
    rows = [((r.get('readings') or [''])[0] + ' ' + (r.get('strength') or '')).strip() for r in primary]
    n = W.add_ocr_lines(req, [r for r in rows if r])
    logger.info('branch request %s OCR (%s) by %s: %s lines', req.pk, engine, request.user, n)
    return Response(_detail(req, request))


# ── line review ────────────────────────────────────────────────────────────────
@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def branch_request_line(request, pk, lid):
    from apps.catalog.models import Item
    from apps.supply.models import BranchRequestLine as L
    if not _can_write(request):
        return _deny()
    req = _get(pk)
    bad = _draft_or_400(req)
    if bad:
        return bad
    ln = get_object_or_404(L, pk=lid, request=req)
    d = request.data
    fields = set()
    # what the MACHINE had proposed, before this decision (for learning below)
    before_item = ln.item_id if not ln.picked_by_user else None
    before_group = ([ln.item_id] + list(ln.extra_items.values_list('id', flat=True))
                    if 'learned_group' in (ln.flags or []) else [])
    if 'item_ids' in d:
        # several picks for one line: the first is the line's item, the rest extra_items
        ids = [int(i) for i in (d.get('item_ids') or []) if str(i).isdigit()]
        ids = list(dict.fromkeys(ids))[:30]
        found = {i.id: i for i in Item.objects.filter(id__in=ids)}
        if len(found) != len(ids):
            return Response({'detail': 'صنف غير موجود.'}, status=http.HTTP_400_BAD_REQUEST)
        if ids:
            d = {**{k: v for k, v in d.items() if k != 'item_ids'}, 'item_id': ids[0]}
            ln.extra_items.set([found[i] for i in ids[1:]])
            if len(ids) > 1 and ln.all_variants:
                ln.all_variants = False                  # hand-picked versions replace «كل الأنواع»
                fields.add('all_variants')
        else:
            ln.extra_items.clear()
            d = {**{k: v for k, v in d.items() if k != 'item_ids'}, 'item_id': None}
    if 'item_id' in d:
        if 'item_ids' not in request.data:               # a single pick replaces any multi-pick
            ln.extra_items.clear()
        if d['item_id'] in (None, ''):
            ln.item, ln.score, ln.confirmed, ln.picked_by_user = None, None, False, False
        else:
            ln.item = get_object_or_404(Item, pk=d['item_id'])
            ln.picked_by_user, ln.confirmed = True, True
            # picked outside the suggested versions → «كل الأنواع» follows the NEW product
            if not any(c.get('id') == ln.item.id and c.get('variant') for c in ln.candidates or []):
                ln.candidates = [{**c, 'variant': False} for c in ln.candidates or []]
                fields.add('candidates')
            ln.flags = [f for f in (ln.flags or []) if f in ('urgent', 'ocr', 'strips', 'qty_large',
                                                            'qty_maybe_strength', 'pack_not_found')]
            # (a person chose → 'learned_group' / 'learned_fuzzy' no longer describe the line)
        fields |= {'item', 'score', 'confirmed', 'picked_by_user', 'flags'}
    if 'qty' in d:
        try:
            q = Decimal(str(d['qty']))
        except (InvalidOperation, TypeError):
            return Response({'detail': 'كمية غير صالحة.'}, status=http.HTTP_400_BAD_REQUEST)
        if q <= 0 or q > 10000:
            return Response({'detail': 'الكمية بين 1 و 10000.'}, status=http.HTTP_400_BAD_REQUEST)
        ln.qty, ln.qty_source = q, 'manual'
        ln.flags = [f for f in (ln.flags or []) if f not in ('qty_large', 'qty_maybe_strength')]
        fields |= {'qty', 'qty_source', 'flags'}
    if 'qty_unit' in d:
        if d['qty_unit'] not in (L.UNIT_PACK, L.UNIT_STRIP):
            return Response({'detail': 'وحدة غير صالحة.'}, status=http.HTTP_400_BAD_REQUEST)
        ln.qty_unit = d['qty_unit']
        fields.add('qty_unit')
    if 'kind' in d:
        if d['kind'] not in (L.KIND_ITEM, L.KIND_NOTE):
            return Response({'detail': 'نوع غير صالح.'}, status=http.HTTP_400_BAD_REQUEST)
        ln.kind = d['kind']
        if ln.kind == L.KIND_NOTE:
            ln.confirmed = False
        fields |= {'kind', 'confirmed'}
    if 'all_variants' in d:
        ln.all_variants = bool(d['all_variants'])
        fields.add('all_variants')
    if 'confirmed' in d:
        if d['confirmed'] and (ln.item is None or ln.kind != L.KIND_ITEM):
            return Response({'detail': 'اختر الصنف قبل التأكيد.'}, status=http.HTTP_400_BAD_REQUEST)
        ln.confirmed = bool(d['confirmed'])
        if ln.confirmed and ln.score is not None and ln.score < 1.0:
            ln.picked_by_user = True              # a person vouched for this suggestion
            fields.add('picked_by_user')
        fields.add('confirmed')
    if fields:
        ln.save(update_fields=sorted(fields))
    # Learning from a correction: the machine's replaced suggestion is rejected for this
    # spelling, a changed remembered group is weakened (apps/shortage/learning).
    if ('item_ids' in request.data or 'item_id' in request.data) and ln.match_text:
        from apps.shortage import learning
        now = ([ln.item_id] + list(ln.extra_items.values_list('id', flat=True))) if ln.item_id else []
        try:
            if before_item and before_item not in now:
                learning.record_rejection(ln.match_text, before_item, source='whatsapp')
            if before_group and set(before_group) != set(now):
                learning.unlearn_alias_group(ln.match_text, before_group)
        except Exception:
            logger.warning('learning from correction failed for line %s', ln.pk, exc_info=True)
    return Response(_detail(req, request))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def branch_request_search(request, pk, lid):
    from apps.catalog.models import Item
    from apps.shortage.matching import find_best_matches
    from apps.supply.branch_requests import _cand, _stock_and_rate
    from apps.supply.models import BranchRequestLine as L
    if not _can_view(request):
        return _deny()
    req = _get(pk)
    ln = get_object_or_404(L, pk=lid, request=req)
    q = str(request.query_params.get('q') or ln.match_text or ln.raw_text).strip()[:120]
    ms = find_best_matches(q, top_n=15, min_score=0.25) if q else []
    by_code = list(Item.objects.filter(is_active=True, softech_id=q)) if q.isdigit() else []
    ids = list(dict.fromkeys([i.id for i in by_code] + [m['item_id'] for m in ms]))
    items = {i.id: i for i in Item.objects.filter(id__in=ids)}
    stock, rate = _stock_and_rate(ids, req.branch)
    sc = {m['item_id']: m['score'] for m in ms}
    return Response({'q': q, 'results': [_cand(items[i], sc.get(i, 1.0), stock, rate) for i in ids if i in items]})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def branch_request_confirm_safe(request, pk):
    from apps.supply.branch_requests import AUTO_SCORE
    from apps.supply.models import BranchRequestLine as L
    if not _can_write(request):
        return _deny()
    req = _get(pk)
    bad = _draft_or_400(req)
    if bad:
        return bad
    n = 0
    for ln in req.lines.filter(kind=L.KIND_ITEM, confirmed=False, item__isnull=False, from_ocr=False):
        if set(ln.flags or []) - SAFE_FLAGS or (ln.score or 0) < AUTO_SCORE:
            continue
        ln.confirmed = True
        ln.save(update_fields=['confirmed'])
        n += 1
    d = _detail(req, request)
    d['confirmed_now'] = n
    return Response(d)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def branch_request_confirm(request, pk):
    from apps.supply import branch_requests as W
    if not _can_write(request):
        return _deny()
    req = _get(pk)
    try:
        sl = W.confirm(req, request.user)
    except ValueError as exc:
        return Response({'detail': str(exc)}, status=http.HTTP_400_BAD_REQUEST)
    logger.info('branch request %s confirmed by %s → shortage list %s', req.pk, request.user, sl.pk)
    req.refresh_from_db()
    d = _detail(req, request)
    d['shortage_list_items'] = sl.items.count()
    return Response(d)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def branch_request_cancel(request, pk):
    from apps.supply.models import BranchRequest
    if not _can_write(request):
        return _deny()
    req = _get(pk)
    bad = _draft_or_400(req)
    if bad:
        return bad
    req.status = BranchRequest.STATUS_CANCELLED
    req.save(update_fields=['status'])
    return Response(_detail(req, request))


# ── availability analysis (the ISR-fulfilment engine) ─────────────────────────
def _analysis_snapshot(request, req):
    from apps.purchasing import isr_fulfillment as F
    from apps.supply.branch_requests import pseudo_isr
    pi = pseudo_isr(req)
    if not pi['lines']:
        raise ValueError('لا توجد أصناف مطابَقة لتحليلها بعد.')
    sig = sorted((l['code'], l['qty']) for l in pi['lines'])
    token = str(request.data.get('token') or '')
    if token and not request.data.get('refresh'):
        snap = cache.get(f'branch_req:{token}')
        if snap and snap.get('sig') == sig:            # same lines → reuse the SOFTECH read
            return token, snap
    user = getattr(req.created_by, 'username', '')
    pi['user_name'] = F.user_names([user]).get(user, '')
    snap = F.collect_requests([pi])
    snap['sig'] = sig
    token = uuid.uuid4().hex
    cache.set(f'branch_req:{token}', snap, CACHE_SECONDS)
    return token, snap


def _coverage(request):
    """{months, fill, basis} — the three plan factors (isr_fulfillment.plan_settings)."""
    from apps.purchasing import isr_fulfillment as F
    return F.plan_settings(request.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def branch_request_analysis(request, pk):
    from apps.purchasing import isr_fulfillment as F
    if not _can_view(request):
        return _deny()
    req = _get(pk)
    try:
        cov = _coverage(request)
        token, snap = _analysis_snapshot(request, req)
    except ValueError as exc:
        return Response({'detail': str(exc)}, status=http.HTTP_400_BAD_REQUEST)
    plan = F.compute(snap, **cov)
    plan.update(token=token, returns={}, can_write=False,   # no SOFTECH ISR → no return legs
                transfers=F.transfers_for(req), can_transfer=_can_write(request))
    return Response(plan)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def branch_request_transfers(request, pk):
    """{coverage} → two linked PROPOSED transfer ISRs per donor (donor → 100 → branch) for
    the plan's «from other branches» quantities. Only CONFIRMED lines move, and live stock
    is always re-read first (never a cached snapshot). SOFTECH is written later by the
    usual approve → push in the ISR tab."""
    from apps.purchasing import isr_fulfillment as F
    from apps.supply.branch_requests import pseudo_isr
    from apps.supply.models import BranchRequest
    if not _can_write(request):
        return Response({'detail': 'غير مصرح لك بإنشاء مقترحات التحويل.'}, status=http.HTTP_403_FORBIDDEN)
    req = _get(pk)
    if req.status == BranchRequest.STATUS_CANCELLED:
        return Response({'detail': 'الطلب ملغى.'}, status=http.HTTP_400_BAD_REQUEST)
    try:
        cov = _coverage(request)
    except ValueError as exc:
        return Response({'detail': str(exc)}, status=http.HTTP_400_BAD_REQUEST)
    pi = pseudo_isr(req, confirmed_only=True)
    if not pi['lines']:
        return Response({'detail': 'أكِّد الأصناف أولاً — التحويلات تُنشأ من الأسطر المؤكَّدة فقط.'},
                        status=http.HTTP_400_BAD_REQUEST)
    user = getattr(req.created_by, 'username', '')
    pi['user_name'] = F.user_names([user]).get(user, '')
    snap = F.collect_requests([pi])                     # fresh read
    snap['sig'] = sorted((l['code'], l['qty']) for l in pi['lines'])
    token = uuid.uuid4().hex
    cache.set(f'branch_req:{token}', snap, CACHE_SECONDS)
    result = F.create_request_transfers(snap, cov['months'], req, created_by=request.user,
                                        fill=cov['fill'], basis=cov['basis'])
    logger.info('branch request %s transfers by %s: created=%s skipped=%s', req.pk, request.user,
                [(c['leg1_id'], c['leg2_id']) for c in result['created']], result['skipped'])
    plan = F.compute(snap, **cov)
    plan.update(token=token, returns={}, can_write=False, transfers=F.transfers_for(req), can_transfer=True)
    return Response({**result, 'plan': plan},
                    status=http.HTTP_201_CREATED if result['created'] else http.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def branch_request_analysis_export(request, pk):
    from apps.purchasing import isr_fulfillment as F
    if not _can_view(request):
        return _deny()
    req = _get(pk)
    try:
        cov = _coverage(request)
        _, snap = _analysis_snapshot(request, req)
    except ValueError as exc:
        return Response({'detail': str(exc)}, status=http.HTTP_400_BAD_REQUEST)
    buf = io.BytesIO()
    F.build_workbook(snap, **cov).save(buf)
    resp = HttpResponse(buf.getvalue(),
                        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = (f'attachment; filename="whatsapp_request_{req.pk}_br'
                                   f'{req.branch.softech_branch_id}_{snap["taken_at"][:10]}.xlsx"')
    return resp
