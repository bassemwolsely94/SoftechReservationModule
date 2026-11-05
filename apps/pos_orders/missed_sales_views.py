"""
apps/pos_orders/missed_sales_views.py — Project 3 (a): the «مبيعات فائتة» inbox.

GET  /api/pos-orders/missed-sales/              list (branch-scoped, sortable, paginated)
GET  /api/pos-orders/missed-sales/<id>/         one suggestion (prefill for the reservation form)
POST /api/pos-orders/missed-sales/<id>/reject/  {reason, note} — reason required, audited

CONFIRM is not here on purpose: it goes through the normal POST /api/reservations/ with
`missed_sale=<id>` so every reservation check (duplicate, closed file, branch scope) applies.
Permissions = the `reservations` matrix module (view to read; create to decide) + branch scope.
"""
from django.db import transaction
from django.utils import timezone
from rest_framework import generics, serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from core import branch_scope
from core.sort_ordering import NullsLastOrderingFilter

from .missed_sales import enabled
from .models import MissedSaleSuggestion

DISABLED = {'detail': 'ميزة المبيعات الفائتة غير مفعّلة.'}


class MissedSalesPermission(BasePermission):
    message = 'ليس لديك صلاحية لهذا الإجراء'

    def has_permission(self, request, view):
        from rest_framework.permissions import SAFE_METHODS
        from core.permissions import matrix_allows
        p = getattr(request.user, 'staff_profile', None)
        needed = ('view',) if request.method in SAFE_METHODS else ('create',)
        return matrix_allows(p, 'reservations', *needed)


class MissedSaleSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    customer_phone = serializers.SerializerMethodField()
    customer_pic = serializers.CharField(source='customer.softech_pic', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    reject_reason_label = serializers.CharField(source='get_reject_reason_display', read_only=True)
    selected_by_name = serializers.SerializerMethodField()
    decided_by_name = serializers.SerializerMethodField()
    bought_in_cart = serializers.SerializerMethodField()

    class Meta:
        model = MissedSaleSuggestion
        fields = ['id', 'branch', 'branch_name', 'customer', 'customer_name', 'customer_phone',
                  'customer_pic', 'item', 'item_code', 'item_name', 'qty', 'value', 'seen_at',
                  'seller_usercode', 'selected_by_name', 'status', 'status_label',
                  'reject_reason', 'reject_reason_label', 'reject_note', 'decided_by_name',
                  'decided_at', 'reservation', 'bought_in_cart']

    def get_customer_phone(self, o):
        """The number serves this branch's own record (D2), masked for staff who may not see phones
        (D3 / D4) — round 2 R4 phone canary."""
        from apps.customers.access import record_phone
        value = getattr(o.customer, 'phone', '') if o.customer_id else ''
        request = self.context.get('request')
        return record_phone(request.user, value) if (value and request is not None) else value

    def get_selected_by_name(self, o):
        return o.selected_by.full_name if o.selected_by_id else ''

    def get_decided_by_name(self, o):
        return o.decided_by.full_name if o.decided_by_id else ''

    def get_bought_in_cart(self, o):
        """What the customer DID buy on that cart — helps judge a real miss from a correction."""
        sold = (self.context.get('sold_by_cart') or {}).get(o.cart_token)
        return sold or []


def _sold_by_cart(tokens):
    from .models import SoftechSalesOrder
    out = {}
    for o in (SoftechSalesOrder.objects.filter(client_token__in=[t for t in tokens if t])
              .exclude(status=SoftechSalesOrder.STATUS_CANCELLED).prefetch_related('lines')):
        out[o.client_token] = [l.item_name or l.softech_itemcode for l in o.lines.all()]
    return out


class MissedSaleList(generics.ListAPIView):
    permission_classes = [IsAuthenticated, MissedSalesPermission]
    serializer_class = MissedSaleSerializer
    filter_backends = [NullsLastOrderingFilter]
    ordering_fields = ['seen_at', 'value', 'qty', 'item_name', 'customer__name', 'branch__name',
                       'status', 'decided_at']
    ordering = ['-seen_at']

    def list(self, request, *args, **kwargs):
        if not enabled():
            return Response(DISABLED, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        qs = (MissedSaleSuggestion.objects
              .select_related('customer', 'branch', 'selected_by__user', 'decided_by__user'))
        qs = branch_scope.scope(qs, self.request.user)
        st = self.request.query_params.get('status', 'new')
        if st and st != 'all':
            qs = qs.filter(status=st)
        br = self.request.query_params.get('branch')
        if br and str(br).isdigit():
            qs = qs.filter(branch_id=int(br))
        return qs

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        page = getattr(self, '_page_tokens', None)
        ctx['sold_by_cart'] = _sold_by_cart(page) if page else {}
        return ctx

    def paginate_queryset(self, queryset):
        page = super().paginate_queryset(queryset)
        self._page_tokens = {o.cart_token for o in (page or [])}
        return page


@api_view(['GET'])
@permission_classes([IsAuthenticated, MissedSalesPermission])
def missed_sale_detail(request, pk):
    if not enabled():
        return Response(DISABLED, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    o = branch_scope.get_or_404(MissedSaleSuggestion.objects.select_related('customer', 'branch'),
                                request.user, pk=pk)
    return Response(MissedSaleSerializer(o, context={'sold_by_cart': _sold_by_cart({o.cart_token}), 'request': request}).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated, MissedSalesPermission])
def missed_sale_reject(request, pk):
    from apps.audit.models import AuditLog
    if not enabled():
        return Response(DISABLED, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    reason = str(request.data.get('reason') or '').strip()
    note = str(request.data.get('note') or '').strip()[:255]
    if reason not in dict(MissedSaleSuggestion.REJECT_REASONS):
        return Response({'reason': 'اختر سبب الرفض.'}, status=status.HTTP_400_BAD_REQUEST)
    if reason == 'other' and not note:
        return Response({'note': 'اكتب السبب.'}, status=status.HTTP_400_BAD_REQUEST)
    profile = getattr(request.user, 'staff_profile', None)
    with transaction.atomic():
        o = branch_scope.get_or_404(MissedSaleSuggestion.objects.select_for_update(),
                                    request.user, pk=pk)
        if o.status != MissedSaleSuggestion.STATUS_NEW:
            return Response({'detail': 'تم البت في هذا الاقتراح بالفعل.'}, status=status.HTTP_409_CONFLICT)
        o.status = MissedSaleSuggestion.STATUS_REJECTED
        o.reject_reason, o.reject_note = reason, note
        o.decided_by, o.decided_at = profile, timezone.now()
        o.save(update_fields=['status', 'reject_reason', 'reject_note', 'decided_by', 'decided_at'])
    AuditLog.log('missed_sale_rejected', user=profile, obj=o, request=request,
                 changes={'status': ['new', 'rejected']},
                 note=f'{o.get_reject_reason_display()}{" — " + note if note else ""}')
    return Response(MissedSaleSerializer(o, context={'request': request}).data)
