"""
apps/recommendations/views.py

Endpoints:
  GET  /api/recommendations/run/          — latest engine run metadata
  POST /api/recommendations/trigger/      — trigger FBT engine (admin/supervisor)
  GET  /api/recommendations/fbt/          — FBT pairs, filterable by item_a
  GET  /api/recommendations/fbt/for-item/ — ?item_id=X → top recs for item
  GET  /api/recommendations/customer/     — ?customer_id=X → customer recs
"""
from rest_framework import filters, generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from .models import RecommendationEngineRun, FrequentlyBoughtTogether, CustomerRecommendation
from .serializers import EngineRunSerializer, FBTPairSerializer, CustomerRecSerializer


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


# ── Latest run ────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def latest_run(request):
    """GET /api/recommendations/run/ — latest engine run metadata."""
    run = RecommendationEngineRun.objects.order_by('-started_at').first()
    if not run:
        return Response({'detail': 'لم يتم تشغيل المحرك بعد'}, status=404)
    return Response(EngineRunSerializer(run).data)


# ── Trigger ───────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def trigger_engine(request):
    """
    POST /api/recommendations/trigger/
    Body (optional): { lookback_days, min_support, min_confidence }
    Admin / supervisor only.
    """
    profile = _profile(request)
    if not profile or profile.role not in ('admin', 'supervisor'):
        return Response({'detail': 'يُسمح فقط للمدراء والمشرفين'}, status=403)

    # Check no run is already in progress
    if RecommendationEngineRun.objects.filter(status='running').exists():
        return Response({'detail': 'يوجد تشغيل جارٍ بالفعل'}, status=409)

    lookback_days  = int(request.data.get('lookback_days',  365))
    min_support    = float(request.data.get('min_support',   0.001))
    min_confidence = float(request.data.get('min_confidence', 0.05))

    from threading import Thread
    from apps.recommendations.engine import run_fbt_engine

    def _run():
        try:
            run_fbt_engine(lookback_days=lookback_days,
                           min_support=min_support,
                           min_confidence=min_confidence)
        except Exception:
            pass

    Thread(target=_run, daemon=True).start()

    return Response({'queued': True, 'message': 'محرك التوصيات يعمل في الخلفية'})


# ── FBT list ──────────────────────────────────────────────────────────────────

class FBTPairListView(generics.ListAPIView):
    """
    GET /api/recommendations/fbt/
    Params: item_a (filter), search (item name), ordering
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = FBTPairSerializer
    filter_backends    = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields   = ['item_a', 'item_b']
    search_fields      = ['item_a__name', 'item_b__name', 'item_a__softech_id', 'item_b__softech_id']
    ordering_fields    = ['score', 'confidence', 'co_occurrences', 'lift']
    ordering           = ['-score']

    def get_queryset(self):
        run = RecommendationEngineRun.objects.filter(status='success').order_by('-started_at').first()
        if not run:
            return FrequentlyBoughtTogether.objects.none()
        return (
            FrequentlyBoughtTogether.objects
            .filter(run=run)
            .select_related('item_a', 'item_b')
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def fbt_for_item(request):
    """
    GET /api/recommendations/fbt/for-item/?item_id=X[&limit=6]
    Returns top FBT recommendations for a single item — used by Call Workspace.
    """
    item_id = request.query_params.get('item_id')
    if not item_id:
        return Response({'detail': 'item_id مطلوب'}, status=400)

    limit = min(int(request.query_params.get('limit', 6)), 20)

    from apps.recommendations.engine import get_fbt_for_item
    recs = get_fbt_for_item(int(item_id), limit=limit)
    return Response(recs)


# ── Customer recommendations ──────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def customer_recs(request):
    """
    GET /api/recommendations/customer/?customer_id=X[&limit=8]
    Returns personalized recommendations for a customer — used by Call Workspace.
    """
    cid = request.query_params.get('customer_id')
    if not cid:
        return Response({'detail': 'customer_id مطلوب'}, status=400)

    limit = min(int(request.query_params.get('limit', 8)), 20)

    from apps.recommendations.engine import get_customer_recs
    recs = get_customer_recs(int(cid), limit=limit)
    return Response(recs)


# ── Engine runs history ───────────────────────────────────────────────────────

class EngineRunListView(generics.ListAPIView):
    """GET /api/recommendations/runs/ — list all engine runs."""
    permission_classes = [IsAuthenticated]
    serializer_class   = EngineRunSerializer
    queryset           = RecommendationEngineRun.objects.all()
