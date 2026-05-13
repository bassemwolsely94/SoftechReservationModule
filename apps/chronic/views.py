from django.db.models import Count, Q
from django.db import transaction
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.catalog.models import Item
from apps.users.models import StaffProfile
from .models import (
    MedicationTag, ActiveIngredient, IngredientTag,
    ItemIngredientMap, FollowUpProtocol,
)
from .serializers import (
    MedicationTagSerializer,
    ActiveIngredientListSerializer, ActiveIngredientDetailSerializer,
    ActiveIngredientWriteSerializer,
    IngredientTagSerializer,
    ItemIngredientMapSerializer,
    FollowUpProtocolSerializer,
    ItemClassifierSerializer, ItemClassifySerializer,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_profile(request):
    try:
        return request.user.staffprofile
    except Exception:
        return None


class StandardPagination(PageNumberPagination):
    page_size            = 30
    page_size_query_param = 'page_size'
    max_page_size        = 200


# ─────────────────────────────────────────────────────────────────────────────
# MedicationTag
# ─────────────────────────────────────────────────────────────────────────────

class MedicationTagViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class   = MedicationTagSerializer
    queryset           = MedicationTag.objects.all().order_by('tag_type', 'name')

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get('active_only'):
            qs = qs.filter(is_active=True)
        tag_type = self.request.query_params.get('tag_type')
        if tag_type:
            qs = qs.filter(tag_type=tag_type)
        q = self.request.query_params.get('q')
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(name_ar__icontains=q))
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=_get_profile(self.request))


# ─────────────────────────────────────────────────────────────────────────────
# ActiveIngredient
# ─────────────────────────────────────────────────────────────────────────────

class ActiveIngredientViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = ActiveIngredient.objects.prefetch_related(
        'ingredient_tags__tag', 'item_maps', 'followup_protocols'
    ).all()

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return ActiveIngredientWriteSerializer
        if self.action == 'retrieve':
            return ActiveIngredientDetailSerializer
        return ActiveIngredientListSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.query_params.get('q')
        if q:
            qs = qs.filter(
                Q(name__icontains=q) | Q(name_ar__icontains=q) |
                Q(atc_code__icontains=q) | Q(atc_level4_name__icontains=q)
            )
        if self.request.query_params.get('chronic_only'):
            qs = qs.filter(is_chronic=True)
        chronic_class = self.request.query_params.get('chronic_class')
        if chronic_class:
            qs = qs.filter(chronic_class=chronic_class)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=_get_profile(self.request))

    # ── POST /api/chronic/ingredients/{id}/add_tag/ ───────────────────────────
    @action(detail=True, methods=['post'], url_path='add_tag')
    def add_tag(self, request, pk=None):
        ingredient = self.get_object()
        tag_id = request.data.get('tag_id')
        if not tag_id:
            return Response({'error': 'tag_id مطلوب'}, status=400)
        try:
            tag = MedicationTag.objects.get(pk=tag_id)
        except MedicationTag.DoesNotExist:
            return Response({'error': 'الوسم غير موجود'}, status=404)
        itag, created = IngredientTag.objects.get_or_create(
            active_ingredient=ingredient, tag=tag,
            defaults={'added_by': _get_profile(request)},
        )
        return Response(IngredientTagSerializer(itag).data,
                        status=201 if created else 200)

    # ── DELETE /api/chronic/ingredients/{id}/remove_tag/ ─────────────────────
    @action(detail=True, methods=['delete'], url_path='remove_tag')
    def remove_tag(self, request, pk=None):
        ingredient = self.get_object()
        tag_id = request.data.get('tag_id')
        deleted, _ = IngredientTag.objects.filter(
            active_ingredient=ingredient, tag_id=tag_id
        ).delete()
        if deleted:
            return Response(status=204)
        return Response({'error': 'الوسم غير مرتبط بهذه المادة'}, status=404)

    # ── GET /api/chronic/ingredients/{id}/items/ ─────────────────────────────
    @action(detail=True, methods=['get'])
    def items(self, request, pk=None):
        ingredient = self.get_object()
        maps = ingredient.item_maps.select_related('item', 'mapped_by__user').all()
        return Response(ItemIngredientMapSerializer(maps, many=True).data)

    # ── GET/POST /api/chronic/ingredients/{id}/protocols/ ────────────────────
    @action(detail=True, methods=['get', 'post'])
    def protocols(self, request, pk=None):
        ingredient = self.get_object()
        if request.method == 'GET':
            protocols = ingredient.followup_protocols.all()
            return Response(FollowUpProtocolSerializer(protocols, many=True).data)
        # POST — create new protocol
        data = request.data.copy()
        data['active_ingredient'] = ingredient.pk
        serializer = FollowUpProtocolSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save(created_by=_get_profile(request))
        return Response(serializer.data, status=201)


# ─────────────────────────────────────────────────────────────────────────────
# FollowUpProtocol
# ─────────────────────────────────────────────────────────────────────────────

class FollowUpProtocolViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class   = FollowUpProtocolSerializer
    queryset = FollowUpProtocol.objects.select_related(
        'active_ingredient', 'created_by__user'
    ).prefetch_related('applies_to_branches').all()

    def get_queryset(self):
        qs = super().get_queryset()
        ingredient_id = self.request.query_params.get('ingredient')
        if ingredient_id:
            qs = qs.filter(active_ingredient_id=ingredient_id)
        if self.request.query_params.get('active_only'):
            qs = qs.filter(is_active=True)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=_get_profile(self.request))


# ─────────────────────────────────────────────────────────────────────────────
# ItemIngredientMap
# ─────────────────────────────────────────────────────────────────────────────

class ItemIngredientMapViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class   = ItemIngredientMapSerializer
    queryset = ItemIngredientMap.objects.select_related(
        'item', 'active_ingredient', 'mapped_by__user'
    ).all()

    def get_queryset(self):
        qs = super().get_queryset()
        item_id = self.request.query_params.get('item')
        if item_id:
            qs = qs.filter(item_id=item_id)
        ingredient_id = self.request.query_params.get('ingredient')
        if ingredient_id:
            qs = qs.filter(active_ingredient_id=ingredient_id)
        return qs

    def perform_create(self, serializer):
        serializer.save(mapped_by=_get_profile(self.request))


# ─────────────────────────────────────────────────────────────────────────────
# Item Classifier — browse catalog.Item and classify as chronic
# ─────────────────────────────────────────────────────────────────────────────

class ItemClassifierViewSet(viewsets.ViewSet):
    """
    The main module-page endpoint.

    GET  /api/chronic/items/              — paginated item list with classification status
    GET  /api/chronic/items/{id}/         — single item detail
    POST /api/chronic/items/{id}/classify/ — link item to an ActiveIngredient
    GET  /api/chronic/items/summary/      — dashboard counts

    NOTE: stktransm.phcode = customer personcode (e.g. 04HD1006).
          Item classification is per-item via ItemIngredientMap.
    """
    permission_classes = [IsAuthenticated]
    pagination_class   = StandardPagination

    def _base_qs(self):
        return Item.objects.prefetch_related(
            'ingredient_maps__active_ingredient__ingredient_tags__tag'
        ).order_by('name')

    def _attach_prefetch(self, items):
        """Attach prefetched ingredient_maps to _prefetched_ingredient_maps attr."""
        for item in items:
            item._prefetched_ingredient_maps = list(item.ingredient_maps.all())
        return items

    # ── GET /api/chronic/items/ ───────────────────────────────────────────────
    def list(self, request):
        qs = self._base_qs()

        # ── Filters ──
        q = request.query_params.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(name__icontains=q) |
                Q(name_scientific__icontains=q) |
                Q(softech_id__icontains=q) |
                Q(barcode__icontains=q)
            )

        status_filter = request.query_params.get('status')
        if status_filter == 'classified':
            qs = qs.filter(ingredient_maps__isnull=False).distinct()
        elif status_filter == 'unclassified':
            qs = qs.filter(ingredient_maps__isnull=True)
        elif status_filter == 'chronic':
            qs = qs.filter(
                ingredient_maps__active_ingredient__is_chronic=True
            ).distinct()
        elif status_filter == 'non_chronic':
            qs = qs.filter(ingredient_maps__isnull=False).exclude(
                ingredient_maps__active_ingredient__is_chronic=True
            ).distinct()

        active_only = request.query_params.get('active_only', 'true').lower()
        if active_only != 'false':
            qs = qs.filter(is_active=True)

        family_code = request.query_params.get('family_code')
        if family_code:
            qs = qs.filter(family_code=family_code)

        # ── Pagination ──
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        self._attach_prefetch(page)
        serializer = ItemClassifierSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    # ── GET /api/chronic/items/{id}/ ─────────────────────────────────────────
    def retrieve(self, request, pk=None):
        try:
            item = self._base_qs().get(pk=pk)
        except Item.DoesNotExist:
            return Response({'error': 'الصنف غير موجود'}, status=404)
        self._attach_prefetch([item])
        return Response(ItemClassifierSerializer(item).data)

    # ── POST /api/chronic/items/{id}/classify/ ────────────────────────────────
    @action(detail=True, methods=['post'])
    def classify(self, request, pk=None):
        """
        Link this item to an ActiveIngredient (create or pick existing).
        Creates ItemIngredientMap. Optionally tags the ingredient.
        """
        try:
            item = Item.objects.get(pk=pk)
        except Item.DoesNotExist:
            return Response({'error': 'الصنف غير موجود'}, status=404)

        ser = ItemClassifySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data    = ser.validated_data
        profile = _get_profile(request)

        with transaction.atomic():
            # ── Resolve / create ActiveIngredient ─────────────────────────────
            if data.get('active_ingredient_id'):
                try:
                    ingredient = ActiveIngredient.objects.get(
                        pk=data['active_ingredient_id']
                    )
                except ActiveIngredient.DoesNotExist:
                    return Response({'error': 'المادة الفعّالة غير موجودة'}, status=404)
            else:
                ingredient = ActiveIngredient.objects.create(
                    name=data['ingredient_name'].strip(),
                    name_ar=data.get('ingredient_name_ar', ''),
                    atc_code=data.get('ingredient_atc_code', ''),
                    is_chronic=data.get('is_chronic', False),
                    chronic_class=data.get('chronic_class', ''),
                    created_by=profile,
                )

            # ── Update ingredient classification if specified ──────────────────
            update_fields = []
            if 'is_chronic' in data:
                ingredient.is_chronic = data['is_chronic']
                update_fields.append('is_chronic')
            if data.get('chronic_class'):
                ingredient.chronic_class = data['chronic_class']
                update_fields.append('chronic_class')
            if update_fields:
                update_fields.append('updated_at')
                ingredient.save(update_fields=update_fields)

            # ── Add tags ──────────────────────────────────────────────────────
            for tag_id in data.get('tag_ids', []):
                try:
                    tag = MedicationTag.objects.get(pk=tag_id, is_active=True)
                    IngredientTag.objects.get_or_create(
                        active_ingredient=ingredient, tag=tag,
                        defaults={'added_by': profile},
                    )
                except MedicationTag.DoesNotExist:
                    pass

            # ── Create / update ItemIngredientMap ─────────────────────────────
            imap, created = ItemIngredientMap.objects.update_or_create(
                item=item,
                active_ingredient=ingredient,
                defaults={
                    'concentration': data.get('concentration', ''),
                    'is_primary':    data.get('is_primary', True),
                    'mapped_by':     profile,
                },
            )

        # Re-fetch with prefetch for response
        item = self._base_qs().get(pk=pk)
        self._attach_prefetch([item])
        return Response(
            ItemClassifierSerializer(item).data,
            status=200,
        )

    # ── DELETE /api/chronic/items/{id}/unclassify/ ────────────────────────────
    @action(detail=True, methods=['delete'], url_path='unclassify')
    def unclassify(self, request, pk=None):
        """Remove a specific ingredient mapping from this item."""
        ingredient_id = request.query_params.get('ingredient_id') or \
                        request.data.get('ingredient_id')
        qs = ItemIngredientMap.objects.filter(item_id=pk)
        if ingredient_id:
            qs = qs.filter(active_ingredient_id=ingredient_id)
        deleted, _ = qs.delete()
        if deleted:
            return Response({'deleted': deleted})
        return Response({'error': 'لا يوجد ربط لحذفه'}, status=404)

    # ── GET /api/chronic/items/summary/ ──────────────────────────────────────
    @action(detail=False, methods=['get'])
    def summary(self, request):
        total        = Item.objects.filter(is_active=True).count()
        classified   = Item.objects.filter(
            is_active=True, ingredient_maps__isnull=False
        ).distinct().count()
        chronic      = Item.objects.filter(
            is_active=True,
            ingredient_maps__active_ingredient__is_chronic=True
        ).distinct().count()
        unclassified = total - classified

        return Response({
            'total_items':        total,
            'classified':         classified,
            'unclassified':       unclassified,
            'chronic':            chronic,
            'classification_pct': round(classified / total * 100, 1) if total else 0,
        })


# ─────────────────────────────────────────────────────────────────────────────
# Task Generator endpoint
# ─────────────────────────────────────────────────────────────────────────────

class TaskGeneratorViewSet(viewsets.ViewSet):
    """
    POST /api/chronic/task-generator/preview/  — dry-run, return counts
    POST /api/chronic/task-generator/generate/ — actually create tasks
    """
    permission_classes = [IsAuthenticated]

    def _run(self, request, dry_run: bool):
        from .task_generator import generate_tasks_for_period
        from datetime import date

        period_start   = request.data.get('period_start')
        period_end     = request.data.get('period_end')
        branch_ids     = request.data.get('branch_ids', [])
        customer_types = request.data.get('customer_types', ['all'])
        ingredient_ids = request.data.get('ingredient_ids', [])

        if not period_start or not period_end:
            return Response({'error': 'period_start و period_end مطلوبان'}, status=400)

        try:
            p_start = date.fromisoformat(period_start)
            p_end   = date.fromisoformat(period_end)
        except ValueError:
            return Response({'error': 'صيغة التاريخ غير صحيحة (YYYY-MM-DD)'}, status=400)

        result = generate_tasks_for_period(
            period_start=p_start,
            period_end=p_end,
            branch_ids=branch_ids or None,
            customer_types=customer_types,
            ingredient_ids=ingredient_ids or None,
            dry_run=dry_run,
            requested_by=_get_profile(request),
        )
        return Response(result)

    @action(detail=False, methods=['post'])
    def preview(self, request):
        return self._run(request, dry_run=True)

    @action(detail=False, methods=['post'])
    def generate(self, request):
        return self._run(request, dry_run=False)
