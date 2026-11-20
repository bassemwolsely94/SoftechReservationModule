"""
Outbound call lists (campaigns) API — /api/followups/call-lists/.
Reads: the followups module view permission. Create/close: the followups:create grant
(role review 2026-11-20; was a named role list); close also needs the list's creator, an
all-branch user, or branches covering the list's (final review I3). Branch scope applies
to the customers selected (core.branch_scope).
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.multi_filter import multi_values

from . import call_lists
from .models import CallList
from .views import FOLLOWUPS


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


def _can_create(request):
    from core.permissions import matrix_allows   # owner decision 6 (role review 2026-11-20): the matrix
    p = _profile(request)
    return bool(p and p.is_active and matrix_allows(p, 'followups', 'create'))


def _clean_criteria(data) -> dict:
    c = data.get('criteria') or {}
    out = {}
    if c.get('refill_due') in (True, 'true', '1', 1):
        # C08: due for a refill from their own buying interval — segment / inactive days do not apply
        out['refill_due'] = True
        c = {k: v for k, v in c.items() if k in ('branch_ids', 'branch_id')}
    segs = c.get('segments') or []
    if isinstance(segs, list) and segs:
        out['segments'] = [str(s)[:15] for s in segs if s][:10]
    # branches: several (branch_ids: [3, 7]) or the old single branch_id; junk is an error (400),
    # never silently dropped — a dropped branch would widen the list to every allowed branch
    raw = multi_values(c, 'branch_ids') + multi_values(c, 'branch_id')
    if raw:
        if not all(v.isdigit() for v in raw):
            raise ValueError('branch')
        out['branch_ids'] = sorted({int(v) for v in raw})[:50]
    for key in ('inactive_days_min', 'inactive_days_max'):
        v = c.get(key)
        if v not in (None, ''):
            out[key] = max(0, int(v))
    return out


def _row(cl, prog, request=None, may_create=None):
    p = prog.get(cl.pk, {})
    total = p.get('total', 0)
    finished = p.get('done', 0) + p.get('missed', 0)
    return {
        'id': cl.id, 'name': cl.name, 'script': cl.script, 'status': cl.status,
        'criteria': cl.criteria, 'size': cl.size, 'created_at': cl.created_at,
        'created_by': cl.created_by.full_name if cl.created_by else None,
        # the server's close rule, so the screen shows «إغلاق» only where it works (final review I3)
        'can_close': bool(request is not None and cl.status == 'active'
                          and (_can_create(request) if may_create is None else may_create)
                          and _can_close(request, cl)),
        'progress': {
            'total': total, 'open': p.get('open', 0), 'no_answer': p.get('no_answer', 0),
            'done': p.get('done', 0), 'closed': p.get('missed', 0),
            'pct': round(finished / total * 100) if total else 0,
        },
    }


class CallListView(APIView):
    """GET list (with progress) · POST create {name, script, criteria, agent_ids}."""
    permission_classes = [IsAuthenticated, FOLLOWUPS]

    def get(self, request):
        lists = list(CallList.objects.select_related('created_by__user')
                     .filter(status=request.query_params.get('status', 'active'))[:100])
        prog = call_lists.progress(lists)
        may_create = _can_create(request)          # once per request, not per row
        return Response([_row(cl, prog, request, may_create) for cl in lists])

    def post(self, request):
        from apps.users.models import StaffProfile
        if not _can_create(request):
            return Response({'detail': 'ليس لديك صلاحية إنشاء قوائم الاتصال'}, status=403)
        name = str(request.data.get('name', '')).strip()[:120]
        if not name:
            return Response({'detail': 'اسم القائمة مطلوب'}, status=400)
        try:
            criteria = _clean_criteria(request.data)
        except (TypeError, ValueError):
            return Response({'detail': 'معايير غير صحيحة'}, status=400)
        if not criteria:
            return Response({'detail': 'اختر شريحة أو فرعاً أو مدة انقطاع على الأقل'}, status=400)
        ids = request.data.get('agent_ids') or []
        agents = list(StaffProfile.objects.filter(pk__in=ids, is_active=True).order_by('pk'))
        if not agents:
            return Response({'detail': 'اختر موظفاً واحداً على الأقل'}, status=400)
        cl = call_lists.create_call_list(
            name=name, script=str(request.data.get('script', ''))[:2000], criteria=criteria,
            agents=agents, actor=_profile(request), user=request.user)
        if cl.size == 0:
            return Response({**_row(cl, {}, request, True), 'detail': 'لا يوجد عملاء مطابقون'}, status=201)
        return Response(_row(cl, call_lists.progress([cl]), request, True), status=201)


class CallListPreviewView(APIView):
    """POST {criteria} → how many customers match (before creating)."""
    permission_classes = [IsAuthenticated, FOLLOWUPS]

    def post(self, request):
        try:
            criteria = _clean_criteria(request.data)
        except (TypeError, ValueError):
            return Response({'detail': 'معايير غير صحيحة'}, status=400)
        return Response(call_lists.preview(criteria, request.user))


def _list_branch_ids(cl) -> set:
    c = cl.criteria or {}
    raw = multi_values(c, 'branch_ids') + multi_values(c, 'branch_id')
    return {int(v) for v in raw if str(v).isdigit()}


def _can_close(request, cl) -> bool:
    """Closing cancels every open task of the list (final review I3): its creator, an all-branch
    user (core.branch_scope), or a user whose branches cover every branch in its criteria. A list
    with no branch criteria spans every branch, so only the first two."""
    from core import branch_scope
    p = _profile(request)
    if p is not None and cl.created_by_id == p.pk:
        return True
    mine = branch_scope.branch_ids(request.user)
    if mine is None:
        return True
    wanted = _list_branch_ids(cl)
    return bool(wanted) and wanted <= mine


class CallListCloseView(APIView):
    permission_classes = [IsAuthenticated, FOLLOWUPS]

    def post(self, request, pk):
        if not _can_create(request):
            return Response({'detail': 'غير مسموح'}, status=403)
        cl = CallList.objects.filter(pk=pk, status='active').first()
        if cl is None:
            return Response({'detail': 'القائمة غير موجودة أو مغلقة'}, status=404)
        if not _can_close(request, cl):
            return Response({'detail': 'إغلاق هذه القائمة لمنشئها أو لمن يغطي كل فروعها'}, status=403)
        cancelled = call_lists.close_call_list(cl, _profile(request))
        return Response({'id': cl.id, 'status': cl.status, 'cancelled_tasks': cancelled})


class CallListAgentsView(APIView):
    """Staff who can work a call list (call center, supervisors, admins)."""
    permission_classes = [IsAuthenticated, FOLLOWUPS]

    def get(self, request):
        from apps.users.models import StaffProfile
        qs = (StaffProfile.objects.filter(is_active=True, user__is_active=True,
                                          role__in=('call_center', 'supervisor', 'admin'))
              .select_related('user').order_by('role', 'user__first_name'))
        return Response([{'id': s.id, 'name': s.full_name, 'role': s.role} for s in qs])
