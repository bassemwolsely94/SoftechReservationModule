"""
Outbound call lists (campaigns) API — /api/followups/call-lists/.
Reads: the followups module view permission. Create/close: followups create/edit AND
role admin / supervisor / call_center (owner decision 2026-11-09). Branch scope applies
to the customers selected (core.branch_scope).
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import call_lists
from .models import CallList
from .views import FOLLOWUPS


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


def _can_create(request):
    p = _profile(request)
    return bool(p and p.is_active and p.role in call_lists.CREATOR_ROLES)


def _clean_criteria(data) -> dict:
    c = data.get('criteria') or {}
    out = {}
    segs = c.get('segments') or []
    if isinstance(segs, list) and segs:
        out['segments'] = [str(s)[:15] for s in segs if s][:10]
    for key in ('branch_id', 'inactive_days_min', 'inactive_days_max'):
        v = c.get(key)
        if v not in (None, ''):
            out[key] = max(0, int(v))
    return out


def _row(cl, prog):
    p = prog.get(cl.pk, {})
    total = p.get('total', 0)
    finished = p.get('done', 0) + p.get('missed', 0)
    return {
        'id': cl.id, 'name': cl.name, 'script': cl.script, 'status': cl.status,
        'criteria': cl.criteria, 'size': cl.size, 'created_at': cl.created_at,
        'created_by': cl.created_by.full_name if cl.created_by else None,
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
        return Response([_row(cl, prog) for cl in lists])

    def post(self, request):
        from apps.users.models import StaffProfile
        if not _can_create(request):
            return Response({'detail': 'إنشاء قوائم الاتصال للمدير والمشرف وموظفي الكول سنتر'}, status=403)
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
            return Response({**_row(cl, {}), 'detail': 'لا يوجد عملاء مطابقون'}, status=201)
        return Response(_row(cl, call_lists.progress([cl])), status=201)


class CallListPreviewView(APIView):
    """POST {criteria} → how many customers match (before creating)."""
    permission_classes = [IsAuthenticated, FOLLOWUPS]

    def post(self, request):
        try:
            criteria = _clean_criteria(request.data)
        except (TypeError, ValueError):
            return Response({'detail': 'معايير غير صحيحة'}, status=400)
        return Response(call_lists.preview(criteria, request.user))


class CallListCloseView(APIView):
    permission_classes = [IsAuthenticated, FOLLOWUPS]

    def post(self, request, pk):
        if not _can_create(request):
            return Response({'detail': 'غير مسموح'}, status=403)
        cl = CallList.objects.filter(pk=pk, status='active').first()
        if cl is None:
            return Response({'detail': 'القائمة غير موجودة أو مغلقة'}, status=404)
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
