from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Sum, Count

from .models import Customer, CustomerNote, CustomerHealthProfile, PurchaseHistory
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
    filterset_fields    = ['softech_ptclassifcode', 'preferred_branch', 'segment', 'churn_segment']
    search_fields       = ['name', 'phone', 'phone_alt', 'softech_id', 'softech_pic']
    ordering_fields     = ['name', 'created_at', 'updated_at', 'churn_score', 'ltv',
                           'days_since_last_visit', 'last_visit_date']
    ordering            = ['name']

    def get_queryset(self):
        return Customer.objects.select_related(
            'preferred_branch', 'created_by__user',
            'health_profile',       # prevents N+1 on is_chronic / detected_conditions
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

    # ── GET /api/customers/{id}/unmet-demand/ ─────────────────────────────────
    # Phase 4 — everything this customer asked for and didn't get (CRM context).

    @action(detail=True, methods=['get'], url_path='unmet-demand')
    def unmet_demand(self, request, pk=None):
        customer = self.get_object()
        from collections import Counter
        from django.db.models import Q, F, Sum
        from apps.demand.models import DemandItem

        # Match by FK OR phcode OR phone — demands aren't always FK-linked.
        match = Q(demand__customer=customer)
        if customer.softech_pic:
            match |= Q(demand__phcode=customer.softech_pic)
        phones = [p for p in (customer.phone, customer.phone_alt) if p]
        if phones:
            match |= Q(demand__phone__in=phones)

        base = (
            DemandItem.objects.filter(match, item__isnull=False)
            .select_related('demand', 'demand__branch', 'item')
        )

        UNMET = ('pending', 'sourcing', 'available_again', 'lost')
        status_labels = dict(DemandItem.ITEM_STATUS_CHOICES)

        items = []
        for di in base.filter(item_status__in=UNMET).order_by('-demand__created_at')[:50]:
            branch = di.demand.branch
            items.append({
                'id':            di.id,
                'demand_id':     di.demand_id,
                'demand_number': di.demand.demand_number,
                'item_id':       di.item_id,
                'item_name':     di.item.name,
                'softech_id':    di.item.softech_id,
                'quantity':      float(di.quantity),
                'item_status':   di.item_status,
                'status_label':  status_labels.get(di.item_status, di.item_status),
                'line_value':    di.line_value,
                'branch_name':   (branch.name_ar or branch.name) if branch else '',
                'created_at':    di.demand.created_at.isoformat(),
                'days_waiting':  di.days_waiting,
            })

        counts = Counter(base.values_list('item_status', flat=True))
        total_unmet_value = float(
            base.filter(item_status__in=UNMET, unit_price_snapshot__isnull=False)
            .annotate(v=F('quantity') * F('unit_price_snapshot'))
            .aggregate(s=Sum('v'))['s'] or 0
        )

        return Response({
            'customer_id': customer.id,
            'summary': {
                'open':              counts.get('pending', 0) + counts.get('sourcing', 0),
                'available_again':   counts.get('available_again', 0),
                'lost':              counts.get('lost', 0),
                'recovered':         counts.get('recovered', 0),
                'total_unmet_value': total_unmet_value,
            },
            'items': items,
        })

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

    # ── GET /api/customers/{id}/patient-profile/ ──────────────────────────────

    @action(detail=True, methods=['get'], url_path='patient-profile')
    def patient_profile(self, request, pk=None):
        """
        GET /api/customers/{id}/patient-profile/
        Returns a fully aggregated patient profile including:
          - chronic medications + refill timeline
          - purchase summary + ERP sales
          - active follow-ups
          - reservations history
          - demand history
          - tags + locations
        """
        customer = self.get_object()
        from .patient_profile import build_patient_profile
        return Response(build_patient_profile(customer, request_user=request.user))

    # ── GET /api/customers/{id}/timeline/ ────────────────────────────────────

    @action(detail=True, methods=['get'], url_path='timeline')
    def timeline(self, request, pk=None):
        """
        GET /api/customers/{id}/timeline/?limit=50
        Returns chronological event list for the customer.
        """
        customer = self.get_object()
        limit = min(int(request.query_params.get('limit', 50)), 200)
        from .patient_profile import build_timeline
        return Response(build_timeline(customer, limit=limit))

    # ── GET /api/customers/{id}/health-profile/ ───────────────────────────────

    @action(detail=True, methods=['get', 'patch'], url_path='health-profile')
    def health_profile_view(self, request, pk=None):
        """
        GET  /api/customers/{id}/health-profile/
             Returns the structured CustomerHealthProfile.

        PATCH /api/customers/{id}/health-profile/
             Allows pharmacist to manually set pregnancy_flag, lactation_flag,
             pediatric_patient, known_allergies, declared_allergies_text.
             Sets manually_overridden=True so the nightly engine won't overwrite.
        """
        customer = self.get_object()

        if request.method == 'PATCH':
            hp, _ = CustomerHealthProfile.objects.get_or_create(customer=customer)
            allowed = {
                'pregnancy_flag', 'lactation_flag', 'pediatric_patient',
                'known_allergies', 'declared_allergies_text',
            }
            update_fields = []
            for field in allowed:
                if field in request.data:
                    setattr(hp, field, request.data[field])
                    update_fields.append(field)

            if update_fields:
                hp.manually_overridden = True
                hp.updated_by = _profile(request)
                update_fields += ['manually_overridden', 'updated_by']
                hp.save(update_fields=update_fields)

            from .patient_profile import _structured_health_profile
            return Response(_structured_health_profile(customer))

        from .patient_profile import _structured_health_profile
        return Response(_structured_health_profile(customer))

    # ── POST /api/customers/{id}/refresh-health/ ──────────────────────────────

    @action(detail=True, methods=['post'], url_path='refresh-health')
    def refresh_health(self, request, pk=None):
        """
        POST /api/customers/{id}/refresh-health/
        Triggers an immediate rebuild of the CustomerHealthProfile for this customer.
        Useful after adding new item→ingredient mappings.
        """
        customer = self.get_object()
        from apps.customers.health_engine import CustomerHealthEngine
        try:
            profile = CustomerHealthEngine(customer).build()
            from .patient_profile import _structured_health_profile
            return Response({
                'rebuilt': True,
                'health_profile': _structured_health_profile(customer),
            })
        except Exception as exc:
            return Response({'rebuilt': False, 'error': str(exc)}, status=500)

    # ── GET /api/customers/{id}/recommendations/ ──────────────────────────────

    @action(detail=True, methods=['get'], url_path='recommendations')
    def recommendations(self, request, pk=None):
        """
        GET /api/customers/{id}/recommendations/?limit=8&clinical_filter=true
        Returns personalized FBT recommendations with optional clinical safety filter.
        """
        customer = self.get_object()
        limit          = min(int(request.query_params.get('limit', 8)), 20)
        clinical_filter = request.query_params.get('clinical_filter', 'true').lower() == 'true'
        from apps.recommendations.engine import get_customer_recs
        recs = get_customer_recs(
            customer_id          = customer.pk,
            limit                = limit,
            apply_clinical_filter = clinical_filter,
        )
        return Response({'customer_id': customer.pk, 'recommendations': recs})

    # ── GET /api/customers/churn-at-risk/ ────────────────────────────────────

    @action(detail=False, methods=['get'], url_path='churn-at-risk')
    def churn_at_risk(self, request):
        """
        GET /api/customers/churn-at-risk/?segment=high&limit=50&is_chronic=true
        Returns customers sorted by churn_score descending.
        """
        p       = request.query_params
        qs      = Customer.objects.filter(churn_score__gt=0).order_by('-churn_score')

        segment = p.get('segment')
        if segment:
            qs = qs.filter(churn_segment=segment)

        # is_chronic filter: look for customers who have at least one has_* = True
        # on their health_profile (db-level boolean fields, not the is_chronic property)
        if p.get('is_chronic') == 'true':
            from django.db.models import Q as _Q
            chronic_q = (
                _Q(health_profile__has_diabetes=True) |
                _Q(health_profile__has_hypertension=True) |
                _Q(health_profile__has_cardiovascular=True) |
                _Q(health_profile__has_thyroid=True) |
                _Q(health_profile__has_cholesterol=True) |
                _Q(health_profile__has_asthma=True) |
                _Q(health_profile__has_psychiatric=True) |
                _Q(health_profile__has_oncology=True) |
                _Q(health_profile__has_anticoagulant=True)
            )
            qs = qs.filter(chronic_q)

        # branch filter
        if p.get('branch'):
            qs = qs.filter(preferred_branch_id=p['branch'])

        limit = min(int(p.get('limit', 50)), 200)

        data = []
        for c in qs.select_related('preferred_branch')[:limit]:
            data.append({
                'id':                 c.pk,
                'name':               c.name,
                'phone':              c.phone,
                'whatsapp_phone':     c.whatsapp_phone or c.phone,
                'segment':            c.segment,
                'churn_score':        float(c.churn_score),
                'churn_score_pct':    round(float(c.churn_score) * 100, 1),
                'churn_segment':      c.churn_segment,
                'days_since_visit':   c.days_since_last_visit,
                'last_visit_date':    str(c.last_visit_date) if c.last_visit_date else None,
                'ltv':                float(c.ltv or 0),
                'preferred_branch':   c.preferred_branch.name_ar if c.preferred_branch else '',
                'purchase_count_90d': c.purchase_count_90d,
            })
        return Response({'count': len(data), 'results': data})
