from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Sum, Count

from .models import Customer, CustomerNote, PurchaseHistory
from .serializers import (
    CustomerSerializer, CustomerListSerializer,
    CustomerCreateSerializer, CustomerUpdateSerializer,
    CustomerNoteSerializer, PurchaseHistorySerializer,
)


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


class CustomerViewSet(viewsets.ModelViewSet):
    permission_classes  = [IsAuthenticated]
    filter_backends     = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields    = ['softech_ptclassifcode', 'preferred_branch']
    search_fields       = ['name', 'phone', 'phone_alt', 'softech_id']
    ordering_fields     = ['name', 'created_at', 'updated_at']
    ordering            = ['name']

    def get_queryset(self):
        return Customer.objects.select_related(
            'preferred_branch', 'created_by__user',
        ).prefetch_related('notes__created_by__user')

    def get_serializer_class(self):
        if self.action == 'list':
            return CustomerListSerializer
        if self.action == 'create':
            return CustomerCreateSerializer
        if self.action in ('update', 'partial_update'):
            return CustomerUpdateSerializer
        return CustomerSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=_profile(self.request))

    # ── GET /api/customers/{id}/purchases/ ────────────────────────────────────

    @action(detail=True, methods=['get'])
    def purchases(self, request, pk=None):
        """
        Returns last 60 purchase invoices for this customer,
        with line items, branch name, and return flag.
        Query params:
          ?doc_code=115   — filter sales only
          ?doc_code=30    — filter returns only
        """
        customer = self.get_object()
        qs = PurchaseHistory.objects.filter(customer=customer) \
            .select_related('branch') \
            .prefetch_related('lines__item') \
            .order_by('-invoice_date')

        doc_code = request.query_params.get('doc_code')
        if doc_code:
            qs = qs.filter(doc_code=doc_code)

        return Response(
            PurchaseHistorySerializer(qs[:60], many=True).data
        )

    # ── GET /api/customers/{id}/reservations/ ─────────────────────────────────

    @action(detail=True, methods=['get'])
    def reservations(self, request, pk=None):
        customer = self.get_object()
        from apps.reservations.models import Reservation
        from apps.reservations.serializers import ReservationListSerializer
        qs = Reservation.objects.filter(customer=customer) \
            .select_related('item', 'branch', 'assigned_to__user') \
            .order_by('-created_at')
        return Response(
            ReservationListSerializer(qs, many=True, context={'request': request}).data
        )

    # ── GET /api/customers/{id}/top_items/ ────────────────────────────────────

    @action(detail=True, methods=['get'], url_path='top_items')
    def top_items(self, request, pk=None):
        """Top 10 items this customer has purchased most, by quantity."""
        customer = self.get_object()
        from apps.customers.models import PurchaseHistoryLine
        items = (
            PurchaseHistoryLine.objects
            .filter(purchase__customer=customer, item__isnull=False)
            .values('item__id', 'item__name', 'item__softech_id')
            .annotate(
                total_qty   = Sum('quantity'),
                total_spent = Sum('line_total'),
                tx_count    = Count('id'),
            )
            .order_by('-total_qty')[:10]
        )
        return Response([
            {
                'item_id':    row['item__id'],
                'item_name':  row['item__name'],
                'softech_id': row['item__softech_id'],
                'total_qty':  float(row['total_qty'] or 0),
                'total_spent': float(row['total_spent'] or 0),
                'tx_count':   row['tx_count'],
            }
            for row in items
        ])

    # ── PATCH /api/customers/{id}/update_conditions/ ─────────────────────────

    @action(detail=True, methods=['patch'], url_path='update_conditions')
    def update_conditions(self, request, pk=None):
        """Quick-patch chronic_conditions field only."""
        customer = self.get_object()
        conditions = request.data.get('chronic_conditions', '')
        customer.chronic_conditions = conditions
        customer.save(update_fields=['chronic_conditions', 'updated_at'])
        return Response({'chronic_conditions': customer.chronic_conditions})

    # ── POST /api/customers/{id}/notes/ ──────────────────────────────────────

    @action(detail=True, methods=['post'])
    def notes(self, request, pk=None):
        customer = self.get_object()
        staff = _profile(request)
        s = CustomerNoteSerializer(data=request.data)
        if s.is_valid():
            s.save(customer=customer, created_by=staff)
            return Response(s.data, status=status.HTTP_201_CREATED)
        return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)

    # ── DELETE /api/customers/{id}/notes/{note_id}/ ───────────────────────────

    @action(detail=True, methods=['delete'], url_path='notes/(?P<note_id>[0-9]+)')
    def delete_note(self, request, pk=None, note_id=None):
        customer = self.get_object()
        try:
            note = CustomerNote.objects.get(pk=note_id, customer=customer)
        except CustomerNote.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        note.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
