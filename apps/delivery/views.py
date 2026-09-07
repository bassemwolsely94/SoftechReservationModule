"""
apps/delivery/views.py

Delivery Management System — v2

Endpoints:
  Drivers:
    GET/POST   /api/delivery/drivers/
    GET/PATCH  /api/delivery/drivers/{id}/

  Customer Locations:
    GET/POST   /api/delivery/customers/{customer_id}/locations/
    GET/PATCH/DELETE  /api/delivery/locations/{id}/

  Orders:
    GET/POST   /api/delivery/
    GET/PATCH  /api/delivery/{id}/

  Order actions:
    POST  /api/delivery/{id}/assign/
    POST  /api/delivery/{id}/accept/
    POST  /api/delivery/{id}/dispatch/
    POST  /api/delivery/{id}/complete/
    POST  /api/delivery/{id}/partial/
    POST  /api/delivery/{id}/unavailable/
    POST  /api/delivery/{id}/fail/
    POST  /api/delivery/{id}/cancel/
    POST  /api/delivery/{id}/return/
    POST  /api/delivery/{id}/close/
    POST  /api/delivery/{id}/collect-cash/

  Analytics:
    GET  /api/delivery/summary/
    GET  /api/delivery/dashboard/
"""
from django.db.models import Avg, Count, F, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import filters, generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from .models import (
    CashCollection,
    CustomerLocation,
    DeliveryAreaFee,
    DeliveryAssignment,
    DeliveryCSAT,
    DeliveryDriver,
    DeliveryOrder,
    DeliveryStatusLog,
)
from .serializers import (
    CashCollectionSerializer,
    CustomerLocationSerializer,
    DeliveryAssignmentSerializer,
    DeliveryDriverSerializer,
    DeliveryOrderCreateSerializer,
    DeliveryOrderListSerializer,
    DeliveryOrderSerializer,
)


# ── Workflow engine ───────────────────────────────────────────────────────────

VALID_TRANSITIONS = {
    DeliveryOrder.STATUS_CREATED:             {DeliveryOrder.STATUS_PENDING_REVIEW, DeliveryOrder.STATUS_PREPARING, DeliveryOrder.STATUS_CANCELLED},
    DeliveryOrder.STATUS_PENDING_REVIEW:      {DeliveryOrder.STATUS_PREPARING, DeliveryOrder.STATUS_CANCELLED},
    DeliveryOrder.STATUS_PREPARING:           {DeliveryOrder.STATUS_READY, DeliveryOrder.STATUS_CANCELLED},
    DeliveryOrder.STATUS_READY:               {DeliveryOrder.STATUS_ASSIGNED, DeliveryOrder.STATUS_CANCELLED},
    DeliveryOrder.STATUS_ASSIGNED:            {DeliveryOrder.STATUS_DRIVER_ACCEPTED, DeliveryOrder.STATUS_CANCELLED},
    DeliveryOrder.STATUS_DRIVER_ACCEPTED:     {DeliveryOrder.STATUS_OUT, DeliveryOrder.STATUS_CANCELLED},
    DeliveryOrder.STATUS_OUT:                 {DeliveryOrder.STATUS_DELIVERED, DeliveryOrder.STATUS_PARTIAL, DeliveryOrder.STATUS_CUSTOMER_UNAVAILABLE, DeliveryOrder.STATUS_FAILED},
    DeliveryOrder.STATUS_PARTIAL:             {DeliveryOrder.STATUS_CLOSED},
    DeliveryOrder.STATUS_CUSTOMER_UNAVAILABLE: {DeliveryOrder.STATUS_OUT, DeliveryOrder.STATUS_FAILED, DeliveryOrder.STATUS_CANCELLED},
    DeliveryOrder.STATUS_FAILED:              {DeliveryOrder.STATUS_CREATED, DeliveryOrder.STATUS_RETURNED},
    DeliveryOrder.STATUS_RETURNED:            {DeliveryOrder.STATUS_CLOSED},
    DeliveryOrder.STATUS_DELIVERED:           {DeliveryOrder.STATUS_CLOSED},
    DeliveryOrder.STATUS_CANCELLED:           set(),
    DeliveryOrder.STATUS_CLOSED:              set(),
}


def _log_transition(order, from_status, to_status, user, notes='', source='manual'):
    DeliveryStatusLog.objects.create(
        order=order,
        from_status=from_status,
        to_status=to_status,
        source=source,
        notes=notes,
        recorded_by=user,
    )


def _assert_transition(order, target_status):
    allowed = VALID_TRANSITIONS.get(order.status, set())
    if target_status not in allowed:
        status_labels = dict(DeliveryOrder.STATUS_CHOICES)
        raise ValueError(
            f'الانتقال من "{status_labels.get(order.status, order.status)}" '
            f'إلى "{status_labels.get(target_status, target_status)}" غير مسموح به.'
        )


# ── Geofencing (pickup must be at branch · delivery must be at the address) ─────
import math as _math
from apps.config.services import get_setting as _get_setting


def _haversine_m(lat1, lng1, lat2, lng2):
    """Great-circle distance in metres between two lat/lng pairs."""
    R = 6371000.0
    p1, p2 = _math.radians(float(lat1)), _math.radians(float(lat2))
    dphi = _math.radians(float(lat2) - float(lat1))
    dlmb = _math.radians(float(lng2) - float(lng1))
    a = _math.sin(dphi / 2) ** 2 + _math.cos(p1) * _math.cos(p2) * _math.sin(dlmb / 2) ** 2
    return R * 2 * _math.atan2(_math.sqrt(a), _math.sqrt(1 - a))


def _geofence_on():
    return _get_setting('delivery_geofence_enabled', default='true').lower() in ('true', '1', 'yes')


def _geofence_radius(key, default):
    try:
        return float(_get_setting(key, default=str(default)))
    except (ValueError, TypeError):
        return float(default)


def _geofence_violation(actual_lat, actual_lng, target_lat, target_lng, radius_m,
                        missing_code, far_code, missing_msg, far_msg):
    """Return a Response (400) if the geofence is violated, else None."""
    if actual_lat in (None, '') or actual_lng in (None, ''):
        return Response({'detail': missing_msg, 'geofence': missing_code},
                        status=status.HTTP_400_BAD_REQUEST)
    try:
        dist = _haversine_m(actual_lat, actual_lng, target_lat, target_lng)
    except (ValueError, TypeError):
        return Response({'detail': 'إحداثيات غير صالحة', 'geofence': 'bad_coords'},
                        status=status.HTTP_400_BAD_REQUEST)
    if dist > radius_m:
        return Response({
            'detail': f'{far_msg} (تبعد {int(dist)} م، المسموح {int(radius_m)} م)',
            'geofence': far_code, 'distance_m': int(dist), 'allowed_m': int(radius_m),
        }, status=status.HTTP_400_BAD_REQUEST)
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Driver views
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DriverListView(generics.ListCreateAPIView):
    """GET/POST /api/delivery/drivers/"""
    permission_classes = [IsAuthenticated]
    serializer_class   = DeliveryDriverSerializer
    filter_backends    = [filters.SearchFilter, filters.OrderingFilter]
    search_fields      = ['full_name', 'mobile', 'national_id']
    ordering_fields    = ['full_name', 'created_at']
    ordering           = ['full_name']

    def get_queryset(self):
        qs = DeliveryDriver.objects.select_related('branch', 'staff_profile')
        status_param = self.request.query_params.get('status')
        branch_param = self.request.query_params.get('branch')
        if status_param:
            qs = qs.filter(status=status_param)
        if branch_param:
            qs = qs.filter(branch_id=branch_param)
        return qs


class DriverDetailView(generics.RetrieveUpdateAPIView):
    """GET/PATCH /api/delivery/drivers/{id}/"""
    permission_classes = [IsAuthenticated]
    serializer_class   = DeliveryDriverSerializer
    queryset = DeliveryDriver.objects.select_related('branch', 'staff_profile')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Customer location views
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class CustomerLocationListView(generics.ListCreateAPIView):
    """GET/POST /api/delivery/customers/{customer_id}/locations/"""
    permission_classes = [IsAuthenticated]
    serializer_class   = CustomerLocationSerializer

    def get_queryset(self):
        from apps.customers.models import Customer
        customer = get_object_or_404(Customer, pk=self.kwargs['customer_id'])
        return CustomerLocation.objects.filter(customer=customer).order_by('-is_default', 'label')

    def perform_create(self, serializer):
        from apps.customers.models import Customer
        customer = get_object_or_404(Customer, pk=self.kwargs['customer_id'])
        serializer.save(customer=customer, updated_by=self.request.user)


class CustomerLocationDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/delivery/locations/{id}/"""
    permission_classes = [IsAuthenticated]
    serializer_class   = CustomerLocationSerializer
    queryset = CustomerLocation.objects.all()

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Delivery Order CRUD
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DeliveryOrderListView(generics.ListCreateAPIView):
    """GET/POST /api/delivery/"""
    permission_classes = [IsAuthenticated]
    filter_backends    = [filters.SearchFilter, filters.OrderingFilter]
    search_fields      = ['order_number', 'customer_name', 'customer_phone',
                          'softech_doc_ref', 'softech_crm_order_no', 'softech_doc_number5']
    ordering_fields    = ['ordered_at', 'created_at', 'status', 'total_value']
    ordering           = ['-ordered_at']

    def get_queryset(self):
        qs = DeliveryOrder.objects.select_related(
            'branch', 'customer', 'assigned_driver', 'created_by',
        )
        p = self.request.query_params

        status_param  = p.get('status')
        branch_param  = p.get('branch')
        driver_param  = p.get('driver')
        source_param  = p.get('source_type')
        date_from     = p.get('date_from')
        date_to       = p.get('date_to')
        is_late       = p.get('is_late')
        crm_status    = p.get('softech_status')   # filter by raw SOFTECH status code

        if p.get('active') == 'true':
            # Live board: everything still in flight (excludes terminal statuses).
            qs = qs.exclude(status__in=DeliveryOrder.TERMINAL_STATUSES)
        if status_param:
            qs = qs.filter(status=status_param)
        if branch_param:
            qs = qs.filter(branch_id=branch_param)
        if driver_param:
            qs = qs.filter(assigned_driver_id=driver_param)
        if source_param:
            qs = qs.filter(source_type=source_param)
        if date_from:
            qs = qs.filter(ordered_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(ordered_at__date__lte=date_to)
        if is_late == 'true':
            qs = qs.filter(
                sla_due_at__lt=timezone.now()
            ).exclude(status__in=DeliveryOrder.TERMINAL_STATUSES)
        if crm_status:
            try:
                qs = qs.filter(softech_order_status=int(crm_status))
            except ValueError:
                pass

        return qs

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return DeliveryOrderCreateSerializer
        return DeliveryOrderListSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class DeliveryOrderDetailView(generics.RetrieveUpdateAPIView):
    """GET/PATCH /api/delivery/{id}/"""
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return DeliveryOrder.objects.select_related(
            'branch', 'customer', 'assigned_driver', 'created_by', 'location',
        ).prefetch_related('status_logs', 'items', 'assignments')

    def get_serializer_class(self):
        if self.request.method in ('PUT', 'PATCH'):
            return DeliveryOrderCreateSerializer
        return DeliveryOrderSerializer


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Workflow action views
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delivery_assign(request, pk):
    """
    POST /api/delivery/{id}/assign/
    Body: { driver_id (required or driver_name), vehicle (opt), notes (opt) }
    Assigns a driver and moves order to STATUS_ASSIGNED.
    Supersedes previous assignment (is_current=False on old one).
    """
    order = get_object_or_404(DeliveryOrder, pk=pk)
    try:
        _assert_transition(order, DeliveryOrder.STATUS_ASSIGNED)
    except ValueError as e:
        return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    driver_id   = request.data.get('driver_id')
    driver_name = request.data.get('driver_name', '').strip()
    vehicle     = request.data.get('vehicle', '')
    notes       = request.data.get('notes', '')

    driver_obj = None
    if driver_id:
        try:
            driver_obj = DeliveryDriver.objects.get(pk=driver_id)
            driver_name = driver_obj.full_name
        except DeliveryDriver.DoesNotExist:
            return Response({'detail': 'السائق غير موجود.'}, status=status.HTTP_400_BAD_REQUEST)

    if not driver_name and not driver_obj:
        return Response({'detail': 'يجب تحديد السائق.'}, status=status.HTTP_400_BAD_REQUEST)

    prev_status = order.status

    # Deactivate previous assignment
    order.assignments.filter(is_current=True).update(is_current=False)

    assignment = DeliveryAssignment.objects.create(
        order=order,
        driver=driver_obj,
        driver_name=driver_name,
        vehicle=vehicle,
        is_current=True,
        assigned_by=request.user,
        notes=notes,
    )

    order.status         = DeliveryOrder.STATUS_ASSIGNED
    order.assigned_at    = timezone.now()
    order.assigned_driver = driver_obj
    order.save(update_fields=['status', 'assigned_at', 'assigned_driver', 'updated_at'])

    _log_transition(order, prev_status, DeliveryOrder.STATUS_ASSIGNED,
                    request.user, notes=f'كُلِّف إلى: {driver_name}')

    return Response(DeliveryAssignmentSerializer(assignment).data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delivery_accept(request, pk):
    """POST /api/delivery/{id}/accept/ — driver accepts the assignment."""
    order = get_object_or_404(DeliveryOrder, pk=pk)
    try:
        _assert_transition(order, DeliveryOrder.STATUS_DRIVER_ACCEPTED)
    except ValueError as e:
        return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    prev_status = order.status
    order.status             = DeliveryOrder.STATUS_DRIVER_ACCEPTED
    order.driver_accepted_at = timezone.now()
    order.save(update_fields=['status', 'driver_accepted_at', 'updated_at'])

    _log_transition(order, prev_status, DeliveryOrder.STATUS_DRIVER_ACCEPTED,
                    request.user, notes=request.data.get('notes', ''))

    return Response(DeliveryOrderSerializer(order).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delivery_dispatch(request, pk):
    """POST /api/delivery/{id}/dispatch/ — driver is out for delivery."""
    order = get_object_or_404(DeliveryOrder, pk=pk)
    try:
        _assert_transition(order, DeliveryOrder.STATUS_OUT)
    except ValueError as e:
        return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    # Geofence: the driver must be within the branch vicinity to pick up.
    if _geofence_on():
        b = order.branch
        if b and b.latitude is not None and b.longitude is not None:
            viol = _geofence_violation(
                request.data.get('driver_lat'), request.data.get('driver_lng'),
                b.latitude, b.longitude, _geofence_radius('delivery_pickup_radius_m', 200),
                'pickup_location_required', 'pickup_too_far',
                'يجب تحديد موقعك الحالي لتأكيد الاستلام من الفرع',
                'يجب أن تكون داخل نطاق الفرع لاستلام الطلب',
            )
            if viol:
                return viol

    prev_status = order.status
    order.status        = DeliveryOrder.STATUS_OUT
    order.dispatched_at = timezone.now()
    order.save(update_fields=['status', 'dispatched_at', 'updated_at'])

    _log_transition(order, prev_status, DeliveryOrder.STATUS_OUT,
                    request.user, notes=request.data.get('notes', ''))

    return Response(DeliveryOrderSerializer(order).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delivery_complete(request, pk):
    """POST /api/delivery/{id}/complete/ — fully delivered."""
    order = get_object_or_404(DeliveryOrder, pk=pk)
    try:
        _assert_transition(order, DeliveryOrder.STATUS_DELIVERED)
    except ValueError as e:
        return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    # Geofence: if a delivery location was set on the order, the driver's current
    # position must match it (within the allowed margin) to confirm delivery.
    if _geofence_on() and order.delivery_lat is not None and order.delivery_lng is not None:
        viol = _geofence_violation(
            request.data.get('pod_lat'), request.data.get('pod_lng'),
            order.delivery_lat, order.delivery_lng, _geofence_radius('delivery_dropoff_radius_m', 300),
            'dropoff_location_required', 'dropoff_too_far',
            'يجب تحديد موقعك الحالي لتأكيد التسليم',
            'موقعك بعيد عن عنوان التسليم المسجَّل',
        )
        if viol:
            return viol

    collected = request.data.get('collected_amount')
    prev_status = order.status
    order.status       = DeliveryOrder.STATUS_DELIVERED
    order.delivered_at = timezone.now()
    if collected is not None:
        order.collected_amount = collected
    # ── Proof of delivery capture ─────────────────────────────────────────────
    pod_fields = ['status', 'delivered_at', 'collected_amount', 'updated_at']
    if request.data.get('pod_recipient_name'):
        order.pod_recipient_name = request.data['pod_recipient_name'][:120]
        pod_fields.append('pod_recipient_name')
    if request.data.get('pod_note'):
        order.pod_note = request.data['pod_note'][:500]
        pod_fields.append('pod_note')
    for f in ('pod_lat', 'pod_lng'):
        if request.data.get(f) not in (None, ''):
            try:
                setattr(order, f, float(request.data[f])); pod_fields.append(f)
            except (ValueError, TypeError):
                pass
    if request.FILES.get('pod_photo'):
        order.pod_photo = request.FILES['pod_photo']
        pod_fields.append('pod_photo')

    # Always log the confirmed delivery location (even if the order had none),
    # backfill the order's location from it, and record branch→drop distance for
    # delivery-time / driver-fee analytics.
    if order.pod_lat is not None and order.pod_lng is not None:
        if order.delivery_lat is None or order.delivery_lng is None:
            order.delivery_lat = order.pod_lat
            order.delivery_lng = order.pod_lng
            pod_fields += ['delivery_lat', 'delivery_lng']
        b = order.branch
        if b and b.latitude is not None and b.longitude is not None:
            try:
                order.delivery_distance_km = round(
                    _haversine_m(b.latitude, b.longitude, order.pod_lat, order.pod_lng) / 1000.0, 2)
                pod_fields.append('delivery_distance_km')
            except (ValueError, TypeError):
                pass
    order.save(update_fields=list(dict.fromkeys(pod_fields)))

    _log_transition(order, prev_status, DeliveryOrder.STATUS_DELIVERED,
                    request.user, notes=request.data.get('notes', ''))

    # Auto-create cash collection record if payment is cash
    if order.payment_method in (DeliveryOrder.PAY_CASH, DeliveryOrder.PAY_MIXED):
        expected = order.total_with_fees
        collected_val = order.collected_amount or expected
        cash_status = 'collected'
        variance = collected_val - expected
        if variance < 0:
            cash_status = 'shortage'
        elif variance > 0:
            cash_status = 'overage'
        CashCollection.objects.update_or_create(
            order=order,
            defaults={
                'expected_amount':  expected,
                'collected_amount': collected_val,
                'status':           cash_status,
                'collection_time':  timezone.now(),
                'collected_by':     request.user,
            },
        )

    return Response(DeliveryOrderSerializer(order).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delivery_partial(request, pk):
    """POST /api/delivery/{id}/partial/ — partially delivered."""
    order = get_object_or_404(DeliveryOrder, pk=pk)
    try:
        _assert_transition(order, DeliveryOrder.STATUS_PARTIAL)
    except ValueError as e:
        return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    prev_status = order.status
    order.status       = DeliveryOrder.STATUS_PARTIAL
    order.delivered_at = timezone.now()
    order.save(update_fields=['status', 'delivered_at', 'updated_at'])

    _log_transition(order, prev_status, DeliveryOrder.STATUS_PARTIAL,
                    request.user, notes=request.data.get('notes', ''))

    return Response(DeliveryOrderSerializer(order).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delivery_unavailable(request, pk):
    """POST /api/delivery/{id}/unavailable/ — customer not available."""
    order = get_object_or_404(DeliveryOrder, pk=pk)
    try:
        _assert_transition(order, DeliveryOrder.STATUS_CUSTOMER_UNAVAILABLE)
    except ValueError as e:
        return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    prev_status = order.status
    order.status    = DeliveryOrder.STATUS_CUSTOMER_UNAVAILABLE
    order.save(update_fields=['status', 'updated_at'])

    _log_transition(order, prev_status, DeliveryOrder.STATUS_CUSTOMER_UNAVAILABLE,
                    request.user, notes=request.data.get('notes', 'العميل غير متاح'))

    return Response(DeliveryOrderSerializer(order).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delivery_fail(request, pk):
    """POST /api/delivery/{id}/fail/ — Body: { reason (required), notes (opt) }"""
    order = get_object_or_404(DeliveryOrder, pk=pk)
    try:
        _assert_transition(order, DeliveryOrder.STATUS_FAILED)
    except ValueError as e:
        return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    reason = request.data.get('reason', '').strip()
    if not reason:
        return Response({'detail': 'سبب الفشل مطلوب.'}, status=status.HTTP_400_BAD_REQUEST)

    prev_status = order.status
    order.status         = DeliveryOrder.STATUS_FAILED
    order.failed_at      = timezone.now()
    order.failure_reason = reason
    order.save(update_fields=['status', 'failed_at', 'failure_reason', 'updated_at'])

    _log_transition(order, prev_status, DeliveryOrder.STATUS_FAILED,
                    request.user, notes=f'سبب: {reason}')

    return Response(DeliveryOrderSerializer(order).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delivery_cancel(request, pk):
    """POST /api/delivery/{id}/cancel/ — Body: { reason (required) }"""
    order = get_object_or_404(DeliveryOrder, pk=pk)
    try:
        _assert_transition(order, DeliveryOrder.STATUS_CANCELLED)
    except ValueError as e:
        return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    reason = request.data.get('reason', '').strip()
    if not reason:
        return Response({'detail': 'سبب الإلغاء مطلوب.'}, status=status.HTTP_400_BAD_REQUEST)

    prev_status = order.status
    order.status        = DeliveryOrder.STATUS_CANCELLED
    order.cancel_reason = reason
    order.save(update_fields=['status', 'cancel_reason', 'updated_at'])

    _log_transition(order, prev_status, DeliveryOrder.STATUS_CANCELLED,
                    request.user, notes=f'سبب: {reason}')

    return Response(DeliveryOrderSerializer(order).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delivery_return(request, pk):
    """POST /api/delivery/{id}/return/"""
    order = get_object_or_404(DeliveryOrder, pk=pk)
    try:
        _assert_transition(order, DeliveryOrder.STATUS_RETURNED)
    except ValueError as e:
        return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    prev_status = order.status
    order.status = DeliveryOrder.STATUS_RETURNED
    order.save(update_fields=['status', 'updated_at'])

    _log_transition(order, prev_status, DeliveryOrder.STATUS_RETURNED,
                    request.user, notes=request.data.get('notes', ''))

    return Response(DeliveryOrderSerializer(order).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delivery_close(request, pk):
    """POST /api/delivery/{id}/close/"""
    order = get_object_or_404(DeliveryOrder, pk=pk)
    try:
        _assert_transition(order, DeliveryOrder.STATUS_CLOSED)
    except ValueError as e:
        return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    prev_status = order.status
    order.status    = DeliveryOrder.STATUS_CLOSED
    order.closed_at = timezone.now()
    order.save(update_fields=['status', 'closed_at', 'updated_at'])

    _log_transition(order, prev_status, DeliveryOrder.STATUS_CLOSED,
                    request.user, notes=request.data.get('notes', ''))

    return Response(DeliveryOrderSerializer(order).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delivery_collect_cash(request, pk):
    """
    POST /api/delivery/{id}/collect-cash/
    Body: { collected_amount, notes (opt) }
    """
    order = get_object_or_404(DeliveryOrder, pk=pk)
    collected_amount = request.data.get('collected_amount')
    if collected_amount is None:
        return Response({'detail': 'المبلغ المحصَّل مطلوب.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        collected_amount = float(collected_amount)
    except (TypeError, ValueError):
        return Response({'detail': 'قيمة غير صالحة للمبلغ.'}, status=status.HTTP_400_BAD_REQUEST)

    expected = float(order.total_with_fees)
    variance = collected_amount - expected
    cash_status = 'collected'
    if variance < 0:
        cash_status = 'shortage'
    elif variance > 0:
        cash_status = 'overage'

    cash, _ = CashCollection.objects.update_or_create(
        order=order,
        defaults={
            'expected_amount':  expected,
            'collected_amount': collected_amount,
            'status':           cash_status,
            'collection_time':  timezone.now(),
            'collected_by':     request.user,
            'notes':            request.data.get('notes', ''),
        },
    )

    order.collected_amount = collected_amount
    order.save(update_fields=['collected_amount', 'updated_at'])

    return Response(CashCollectionSerializer(cash).data, status=status.HTTP_200_OK)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Analytics & Dashboard
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def delivery_order_items(request, pk):
    """
    GET /api/delivery/{id}/items/

    Returns line items for a delivery order.
    Checks DeliveryOrderItem table first (manually created orders).
    Falls back to SOFTECH piccrmitems via live query (SOFTECH-synced orders).
    """
    order = get_object_or_404(DeliveryOrder, pk=pk)

    # 1. Try local DeliveryOrderItem records first
    local_items = order.items.all()
    if local_items.exists():
        from .serializers import DeliveryOrderItemSerializer
        return Response(DeliveryOrderItemSerializer(local_items, many=True).data)

    # 2. Fall back to live SOFTECH piccrmitems query
    if not order.softech_crm_order_no:
        return Response([])

    try:
        from config.sybase import get_sybase_connection, get_branch_connection
        from apps.catalog.models import Item
        from apps.sync.sybase_queries import QUERY_PICCRMITEMS_FOR_ORDER

        # Choose connection: branch DB or HQ
        branch = order.branch
        if branch and branch.db_host and order.softech_crm_branch != '100':
            conn = get_branch_connection(branch.db_host, branch.db_port, branch.db_name)
        else:
            conn = get_sybase_connection()

        cursor = conn.cursor()
        cursor.execute('SET ROWCOUNT 0')

        # piccrmitems uses branchcode and crmorderno
        crm_branch = order.softech_crm_branch or '100'
        crm_no     = order.softech_crm_order_no

        # For HQ, query SOFTECHDB9.dbo.piccrmitems directly
        if crm_branch == '100':
            cursor.execute('''
                SELECT i.itemcode, i.itemqty, i.itemsaleprice, i.unitsaleprice,
                       i.transprice, i.custdiscp, i.itemsalestax, i.sitemqty
                FROM SOFTECHDB9.dbo.piccrmitems i
                WHERE i.branchcode = ? AND i.crmorderno = ?
                ORDER BY i.trans_time
            ''', [crm_branch, crm_no])
        else:
            cursor.execute('''
                SELECT i.itemcode, i.itemqty, i.itemsaleprice, i.unitsaleprice,
                       i.transprice, i.custdiscp, i.itemsalestax, i.sitemqty
                FROM piccrmitems i
                WHERE i.branchcode = ? AND i.crmorderno = ?
                ORDER BY i.trans_time
            ''', [crm_branch, crm_no])

        rows = cursor.fetchall()
        conn.close()

        # Resolve item names from local catalog
        item_codes = [str(r[0]) for r in rows if r[0]]
        catalog = {
            i.softech_id: i
            for i in Item.objects.filter(softech_id__in=item_codes).only(
                'id', 'softech_id', 'name', 'name_scientific', 'pack_price', 'unit_price'
            )
        }

        items = []
        for r in rows:
            item_code   = str(r[0]) if r[0] else ''
            qty         = float(r[1]) if r[1] else 0
            sale_price  = float(r[2]) if r[2] else 0
            unit_price  = float(r[3]) if r[3] else 0
            trans_price = float(r[4]) if r[4] else 0
            discount    = float(r[5]) if r[5] else 0
            tax         = float(r[6]) if r[6] else 0
            supplied_qty = float(r[7]) if r[7] else None

            catalog_item = catalog.get(item_code)
            line_total   = round(trans_price * qty, 2)
            saved        = round((sale_price - trans_price) * qty, 2) if discount > 0 else 0

            items.append({
                'item_code':     item_code,
                'item_name':     catalog_item.name if catalog_item else f'كود {item_code}',
                'item_id':       catalog_item.id if catalog_item else None,
                'quantity':      qty,
                'supplied_qty':  supplied_qty,
                'sale_price':    sale_price,
                'unit_price':    unit_price,
                'trans_price':   trans_price,
                'discount_pct':  discount,
                'tax_amount':    tax,
                'line_total':    line_total,
                'amount_saved':  saved,
            })

        return Response(items)

    except Exception as e:
        import logging
        logging.getLogger('elrezeiky.delivery').warning(f'items fetch failed for order {pk}: {e}')
        return Response([])


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def delivery_whatsapp_message(request, pk):
    """
    GET /api/delivery/{id}/whatsapp/
    Returns the pre-formatted WhatsApp URL + message text for the order's current status.
    """
    order = get_object_or_404(DeliveryOrder, pk=pk)

    phone = order.customer_phone or order.customer_phone_alt
    if not phone:
        return Response(
            {'detail': 'لا يوجد رقم هاتف مسجل لهذا الطلب.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Normalise Egyptian phone to international format
    clean = phone.strip().replace(' ', '').replace('-', '').replace('+', '')
    if clean.startswith('0'):
        clean = '20' + clean[1:]
    elif not clean.startswith('20'):
        clean = '20' + clean

    pharmacy_name = 'صيدليات الرزيقي'

    STATUS_MESSAGES = {
        DeliveryOrder.STATUS_PREPARING: (
            f'عزيزنا العميل\n'
            f'طلبكم رقم {order.order_number} من {pharmacy_name} '
            f'قيد التجهيز الآن 🔧\n'
            f'سنُخطركم فور خروجه للتوصيل.'
        ),
        DeliveryOrder.STATUS_READY: (
            f'عزيزنا العميل\n'
            f'طلبكم رقم {order.order_number} من {pharmacy_name} '
            f'جاهز للتوصيل 📦\n'
            f'سيصل إليكم في أقرب وقت.'
        ),
        DeliveryOrder.STATUS_ASSIGNED: (
            f'عزيزنا العميل\n'
            f'طلبكم رقم {order.order_number} من {pharmacy_name} '
            f'تم تكليف السائق لتوصيله 👤\n'
            f'سيتواصل معكم قريباً.'
        ),
        DeliveryOrder.STATUS_DRIVER_ACCEPTED: (
            f'عزيزنا العميل\n'
            f'طلبكم رقم {order.order_number} من {pharmacy_name} '
            f'السائق في طريقه إليكم 🛵\n'
            f'يرجى التواجد لاستلام الطلب.'
        ),
        DeliveryOrder.STATUS_OUT: (
            f'عزيزنا العميل\n'
            f'طلبكم رقم {order.order_number} من {pharmacy_name} '
            f'في الطريق إليكم الآن 🚚\n'
            f'قيمة الطلب: {order.total_with_fees:.2f} ج.م\n'
            f'يرجى الاستعداد للاستلام والدفع.'
        ),
        DeliveryOrder.STATUS_DELIVERED: (
            f'عزيزنا العميل\n'
            f'تم تسليم طلبكم رقم {order.order_number} من {pharmacy_name} بنجاح ✅\n'
            f'شكراً لثقتكم بنا. نتمنى لكم الشفاء العاجل 💊'
        ),
        DeliveryOrder.STATUS_CUSTOMER_UNAVAILABLE: (
            f'عزيزنا العميل\n'
            f'حاولنا توصيل طلبكم رقم {order.order_number} من {pharmacy_name} '
            f'ولم نتمكن من الوصول إليكم 📵\n'
            f'يرجى التواصل معنا لإعادة جدولة التوصيل.\n'
            f'📞 خدمة العملاء متاحة لمساعدتكم.'
        ),
        DeliveryOrder.STATUS_FAILED: (
            f'عزيزنا العميل\n'
            f'نعتذر، لم نتمكن من تسليم طلبكم رقم {order.order_number} ❌\n'
            f'يرجى التواصل معنا لمعرفة التفاصيل وإعادة الترتيب.'
        ),
        DeliveryOrder.STATUS_CANCELLED: (
            f'عزيزنا العميل\n'
            f'تم إلغاء طلبكم رقم {order.order_number} من {pharmacy_name} 🚫\n'
            f'إذا كان لديكم أي استفسار يرجى التواصل معنا.'
        ),
    }

    message = STATUS_MESSAGES.get(
        order.status,
        f'مرحباً من {pharmacy_name}، '
        f'طلبكم رقم {order.order_number} — {order.get_status_display()}'
    )

    import urllib.parse
    whatsapp_url = f'https://wa.me/{clean}?text={urllib.parse.quote(message)}'

    return Response({
        'phone':         phone,
        'phone_intl':    clean,
        'whatsapp_url':  whatsapp_url,
        'message':       message,
        'order_number':  order.order_number,
        'status':        order.status,
        'status_label':  order.get_status_display(),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def delivery_summary(request):
    """GET /api/delivery/summary/ — quick KPI card data."""
    today  = timezone.localdate()
    all_qs = DeliveryOrder.objects.all()
    today_qs = all_qs.filter(ordered_at__date=today)

    delivered_today = today_qs.filter(status=DeliveryOrder.STATUS_DELIVERED).count()
    failed_today    = today_qs.filter(status=DeliveryOrder.STATUS_FAILED).count()
    completed_today = delivered_today + failed_today
    success_rate    = round(delivered_today / completed_today * 100, 1) if completed_today else 0.0

    # Average delivery minutes (dispatched → delivered)
    delivered_qs = today_qs.filter(
        status=DeliveryOrder.STATUS_DELIVERED,
        dispatched_at__isnull=False,
        delivered_at__isnull=False,
    )
    avg_minutes = 0.0
    if delivered_qs.exists():
        total_secs = sum(
            (o.delivered_at - o.dispatched_at).total_seconds()
            for o in delivered_qs
        )
        avg_minutes = round(total_secs / 60 / delivered_qs.count(), 1)

    # Cash outstanding (cash orders not yet collected)
    cash_outstanding = all_qs.filter(
        payment_method__in=[DeliveryOrder.PAY_CASH, DeliveryOrder.PAY_MIXED],
        status__in=[DeliveryOrder.STATUS_OUT, DeliveryOrder.STATUS_DELIVERED],
        collected_amount__isnull=True,
    ).aggregate(total=Sum('total_value'))['total'] or 0

    return Response({
        'total_today':          today_qs.count(),
        'pending':              all_qs.filter(status=DeliveryOrder.STATUS_CREATED).count(),
        'assigned':             all_qs.filter(status=DeliveryOrder.STATUS_ASSIGNED).count(),
        'out_for_delivery':     all_qs.filter(status=DeliveryOrder.STATUS_OUT).count(),
        'delivered_today':      delivered_today,
        'failed_today':         failed_today,
        'cancelled_today':      today_qs.filter(status=DeliveryOrder.STATUS_CANCELLED).count(),
        'success_rate_today':   success_rate,
        'avg_delivery_minutes': avg_minutes,
        'cash_outstanding':     float(cash_outstanding),
        'late_orders':          all_qs.filter(
            sla_due_at__lt=timezone.now()
        ).exclude(status__in=DeliveryOrder.TERMINAL_STATUSES).count(),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def delivery_dashboard(request):
    """
    GET /api/delivery/dashboard/
    Query params: date_from, date_to, branch
    Full analytics payload.
    """
    p = request.query_params
    date_from = p.get('date_from')
    date_to   = p.get('date_to')
    branch_id = p.get('branch')

    qs = DeliveryOrder.objects.all()
    if date_from:
        qs = qs.filter(ordered_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(ordered_at__date__lte=date_to)
    if branch_id:
        qs = qs.filter(branch_id=branch_id)

    total = qs.count()

    # By status
    by_status = list(
        qs.values('status')
          .annotate(count=Count('id'))
          .order_by('status')
    )

    # By branch
    by_branch = list(
        qs.values('branch__name')
          .annotate(count=Count('id'), revenue=Sum('total_value'))
          .order_by('-count')[:10]
    )

    # By source type
    by_source = list(
        qs.values('source_type')
          .annotate(count=Count('id'))
    )

    # By driver
    by_driver = list(
        qs.filter(assigned_driver__isnull=False)
          .values('assigned_driver__full_name')
          .annotate(count=Count('id'), delivered=Count('id', filter=Q(status=DeliveryOrder.STATUS_DELIVERED)))
          .order_by('-count')[:10]
    )

    # By area
    by_area = list(
        qs.exclude(delivery_area='')
          .values('delivery_area')
          .annotate(count=Count('id'))
          .order_by('-count')[:15]
    )

    # Revenue
    financials = qs.aggregate(
        total_value=Sum('total_value'),
        total_fees=Sum('delivery_fees'),
        total_collected=Sum('collected_amount'),
    )

    # SLA compliance
    sla_total = qs.filter(sla_due_at__isnull=False).count()
    sla_ok = qs.filter(
        sla_due_at__isnull=False,
        delivered_at__isnull=False,
    ).filter(delivered_at__lte=F('sla_due_at')).count()
    sla_pct = round(sla_ok / sla_total * 100, 1) if sla_total else None

    return Response({
        'total': total,
        'by_status': by_status,
        'by_branch': by_branch,
        'by_source': by_source,
        'by_driver': by_driver,
        'by_area': by_area,
        'financials': {
            'total_value':     float(financials['total_value'] or 0),
            'delivery_fees':   float(financials['total_fees'] or 0),
            'total_collected': float(financials['total_collected'] or 0),
        },
        'sla_compliance_pct': sla_pct,
    })


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# F4 — Free Delivery Threshold check
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def delivery_threshold_check(request):
    """
    GET /api/delivery/threshold/?value=450&branch=1&area=Nasr+City&governorate=Cairo
    Returns fee, free_above, amount_needed, is_free_eligible.
    """
    from apps.config.models import SystemSetting
    try:
        value = float(request.query_params.get('value', 0))
    except (ValueError, TypeError):
        value = 0.0

    branch_id   = request.query_params.get('branch')
    area        = request.query_params.get('area', '')
    governorate = request.query_params.get('governorate', '')

    # Look up area-specific fee first
    fee_amount = None
    free_above  = None
    area_fee_obj = None

    if branch_id:
        qs = DeliveryAreaFee.objects.filter(branch_id=branch_id, is_active=True)
        # Most specific match: branch + governorate + area
        for attempt in [
            Q(governorate__iexact=governorate, area__iexact=area),
            Q(governorate__iexact=governorate, area=''),
            Q(governorate='', area=''),
        ]:
            obj = qs.filter(attempt).first()
            if obj:
                area_fee_obj = obj
                fee_amount   = float(obj.fee_amount)
                free_above   = float(obj.free_above)
                break

    # Fall back to system defaults
    if fee_amount is None:
        try:
            fee_amount = float(SystemSetting.objects.get(key='delivery_default_fee').value or 20)
        except SystemSetting.DoesNotExist:
            fee_amount = 20.0

    if free_above is None:
        try:
            free_above = float(SystemSetting.objects.get(key='delivery_free_above').value or 500)
        except SystemSetting.DoesNotExist:
            free_above = 500.0

    is_free = free_above > 0 and value >= free_above
    amount_needed = max(0, free_above - value) if free_above > 0 else None

    return Response({
        'value':          value,
        'fee_amount':     0.0 if is_free else fee_amount,
        'original_fee':   fee_amount,
        'free_above':     free_above,
        'is_free':        is_free,
        'amount_needed':  round(amount_needed, 2) if amount_needed else None,
        'area_fee_id':    area_fee_obj.id if area_fee_obj else None,
        'message':        f'أضف {round(amount_needed, 2)} ج.م للحصول على توصيل مجاني! 🎁' if amount_needed and amount_needed > 0 else ('التوصيل مجاني 🎉' if is_free else None),
    })


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# F5 — Route Optimization
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def delivery_route_plan(request):
    """
    GET /api/delivery/route-plan/?branch=X&driver=Y&date=YYYY-MM-DD
    Returns orders grouped by area with suggested delivery sequence.
    Prioritises: SLA urgency → area clustering → order value (high value first).
    """
    branch_id = request.query_params.get('branch')
    driver_id = request.query_params.get('driver')
    date_str  = request.query_params.get('date', timezone.localdate().isoformat())

    qs = DeliveryOrder.objects.filter(
        ordered_at__date=date_str,
    ).exclude(
        status__in=list(DeliveryOrder.TERMINAL_STATUSES) + [DeliveryOrder.STATUS_DELIVERED]
    ).select_related('customer', 'assigned_driver')

    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    if driver_id:
        qs = qs.filter(assigned_driver_id=driver_id)

    orders = list(qs.order_by(
        F('sla_due_at').asc(nulls_last=True),
        '-total_value',
    ))

    # Group by area
    from collections import defaultdict
    area_groups = defaultdict(list)
    for o in orders:
        key = o.delivery_governorate or o.delivery_area or 'غير محدد'
        area_groups[key].append({
            'id':            o.id,
            'order_number':  o.order_number,
            'customer_name': o.customer_name,
            'customer_phone':o.customer_phone,
            'address':       o.delivery_address,
            'area':          o.delivery_area,
            'governorate':   o.delivery_governorate,
            'landmark':      o.delivery_landmark,
            'lat':           float(o.delivery_lat) if o.delivery_lat else None,
            'lng':           float(o.delivery_lng) if o.delivery_lng else None,
            'google_maps':   o.google_maps_url,
            'total':         float(o.total_with_fees),
            'payment':       o.payment_method,
            'status':        o.status,
            'status_label':  o.get_status_display(),
            'sla_due':       o.sla_due_at.isoformat() if o.sla_due_at else None,
            'is_late':       o.is_late,
            'driver':        o.assigned_driver.full_name if o.assigned_driver else None,
        })

    # Build trips list ordered by area
    trips = [
        {
            'area':       area,
            'stop_count': len(stops),
            'total_cash': round(sum(s['total'] for s in stops if s['payment'] in ('cash', 'mixed')), 2),
            'stops':      stops,
        }
        for area, stops in sorted(area_groups.items(), key=lambda x: -len(x[1]))
    ]

    # Build WhatsApp-ready driver brief
    driver_brief_lines = [f'📦 خطة التوصيل — {date_str}\n']
    seq = 1
    for trip in trips:
        driver_brief_lines.append(f'\n📍 {trip["area"]} ({trip["stop_count"]} طلب)')
        for stop in trip['stops']:
            driver_brief_lines.append(
                f'  {seq}. {stop["customer_name"]} — {stop["total"]} ج.م ({stop["payment"]})'
                + (f'\n     📞 {stop["customer_phone"]}' if stop['customer_phone'] else '')
                + (f'\n     🏠 {stop["address"]}' if stop['address'] else '')
            )
            seq += 1

    return Response({
        'date':         date_str,
        'total_orders': len(orders),
        'total_areas':  len(trips),
        'total_cash':   round(sum(t['total_cash'] for t in trips), 2),
        'trips':        trips,
        'driver_brief': '\n'.join(driver_brief_lines),
    })


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# F6 — Driver App API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def driver_app_my_orders(request):
    """
    GET /api/delivery/app/my-orders/
    Returns orders assigned to the current driver (via StaffProfile → DeliveryDriver).
    Used by the driver mobile app.
    """
    driver = getattr(getattr(request.user, 'staff_profile', None), 'driver_profile', None)
    if not driver:
        return Response({'detail': 'ليس لديك ملف سائق مرتبط.'}, status=status.HTTP_403_FORBIDDEN)

    orders = DeliveryOrder.objects.filter(
        assigned_driver=driver,
    ).exclude(
        status__in=list(DeliveryOrder.TERMINAL_STATUSES)
    ).select_related('branch', 'customer').order_by('ordered_at')

    from .serializers import DeliveryOrderListSerializer
    return Response(DeliveryOrderListSerializer(orders, many=True).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def driver_app_update_location(request, pk):
    """
    POST /api/delivery/app/orders/{id}/location/
    Body: { lat, lng, accuracy (optional) }
    Driver reports current GPS position while on delivery.
    """
    driver = getattr(getattr(request.user, 'staff_profile', None), 'driver_profile', None)
    if not driver:
        return Response({'detail': 'ليس لديك ملف سائق مرتبط.'}, status=status.HTTP_403_FORBIDDEN)
    order = get_object_or_404(DeliveryOrder, pk=pk)
    if order.assigned_driver_id != driver.pk:
        return Response({'detail': 'هذا الطلب غير مسند إليك.'}, status=status.HTTP_403_FORBIDDEN)
    lat = request.data.get('lat')
    lng = request.data.get('lng')
    if not lat or not lng:
        return Response({'detail': 'الإحداثيات مطلوبة.'}, status=status.HTTP_400_BAD_REQUEST)
    # Store latest driver location on the order (can be extended to a tracking table later)
    order.delivery_lat = lat
    order.delivery_lng = lng
    order.save(update_fields=['delivery_lat', 'delivery_lng', 'updated_at'])
    return Response({'status': 'ok', 'lat': lat, 'lng': lng})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Customer-facing live tracking link (tokenized, no login)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_TRACK_SALT    = 'delivery-track'
_TRACK_MAX_AGE = 14 * 24 * 3600   # link valid 14 days


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def delivery_tracking_link(request, pk):
    """Staff: get a shareable tracking link (+ WhatsApp share URL) for an order."""
    from django.core import signing
    from django.conf import settings as dj_settings
    import urllib.parse
    order = get_object_or_404(DeliveryOrder, pk=pk)
    token = signing.dumps({'oid': order.pk}, salt=_TRACK_SALT)
    base  = (getattr(dj_settings, 'FRONTEND_BASE_URL', '') or '').rstrip('/')
    url   = f'{base}/track/{token}'
    wa = None
    phone = (order.customer_phone or '').strip()
    if phone:
        digits = ''.join(ch for ch in phone if ch.isdigit())
        if digits.startswith('0'):
            digits = '2' + digits   # Egypt country code
        msg = f'تابع طلب التوصيل {order.order_number}: {url}'
        wa = f'https://wa.me/{digits}?text={urllib.parse.quote(msg)}'
    return Response({'url': url, 'token': token, 'whatsapp_url': wa})


@api_view(['GET'])
@permission_classes([AllowAny])
def delivery_public_track(request, token):
    """Public (no auth): minimal live status for a tokenized order-tracking link."""
    from django.core import signing
    try:
        data = signing.loads(token, salt=_TRACK_SALT, max_age=_TRACK_MAX_AGE)
    except signing.BadSignature:
        return Response({'detail': 'رابط غير صالح أو منتهي الصلاحية'}, status=status.HTTP_404_NOT_FOUND)

    order = (DeliveryOrder.objects
             .select_related('branch', 'assigned_driver')
             .filter(pk=data.get('oid')).first())
    if not order:
        return Response({'detail': 'الطلب غير موجود'}, status=status.HTTP_404_NOT_FOUND)

    out    = order.status == DeliveryOrder.STATUS_OUT
    driver = order.assigned_driver
    loc = None
    if out and order.delivery_lat and order.delivery_lng:
        loc = {'lat': float(order.delivery_lat), 'lng': float(order.delivery_lng)}

    return Response({
        'order_number':   order.order_number,
        'status':         order.status,
        'status_label':   order.get_status_display(),
        'branch_name':    order.branch.name if order.branch else '',
        'driver_name':    driver.full_name if driver else None,
        'driver_vehicle': driver.get_vehicle_type_display() if driver else None,
        'location':       loc,
        'maps_url':       (f"https://www.google.com/maps?q={loc['lat']},{loc['lng']}" if loc else None),
        'ordered_at':     order.ordered_at,
        'dispatched_at':  order.dispatched_at,
        'delivered_at':   order.delivered_at,
        'is_delivered':   order.status == DeliveryOrder.STATUS_DELIVERED,
        'is_terminal':    order.status in DeliveryOrder.TERMINAL_STATUSES,
    })


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# F9 — Delivery Fee CRUD
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DeliveryAreaFeeListView(generics.ListCreateAPIView):
    """GET/POST /api/delivery/area-fees/"""
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = DeliveryAreaFee.objects.select_related('branch')
        branch = self.request.query_params.get('branch')
        if branch:
            qs = qs.filter(branch_id=branch)
        return qs.filter(is_active=True)

    def get_serializer_class(self):
        from rest_framework import serializers
        class FeeSerializer(serializers.ModelSerializer):
            branch_name = serializers.CharField(source='branch.name', read_only=True)
            class Meta:
                model = DeliveryAreaFee
                fields = '__all__'
                read_only_fields = ['updated_at']
        return FeeSerializer


class DeliveryAreaFeeDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/delivery/area-fees/{id}/"""
    permission_classes = [IsAuthenticated]
    queryset = DeliveryAreaFee.objects.all()

    def get_serializer_class(self):
        from rest_framework import serializers
        class FeeSerializer(serializers.ModelSerializer):
            class Meta:
                model = DeliveryAreaFee
                fields = '__all__'
                read_only_fields = ['updated_at']
        return FeeSerializer


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# F10 — Driver Performance Dashboard
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def driver_performance(request):
    """
    GET /api/delivery/driver-performance/?date_from=&date_to=&branch=
    Returns per-driver KPIs: orders, delivered, failed, avg_time, cash_collected.
    """
    p = request.query_params
    date_from = p.get('date_from', timezone.localdate().isoformat())
    date_to   = p.get('date_to',   timezone.localdate().isoformat())
    branch_id = p.get('branch')

    qs = DeliveryOrder.objects.filter(
        ordered_at__date__gte=date_from,
        ordered_at__date__lte=date_to,
        assigned_driver__isnull=False,
    )
    if branch_id:
        qs = qs.filter(branch_id=branch_id)

    # Per-driver aggregation
    by_driver_raw = list(
        qs.values('assigned_driver', 'assigned_driver__full_name', 'assigned_driver__mobile')
          .annotate(
              total=Count('id'),
              delivered=Count('id', filter=Q(status=DeliveryOrder.STATUS_DELIVERED)),
              partial=Count('id', filter=Q(status=DeliveryOrder.STATUS_PARTIAL)),
              failed=Count('id', filter=Q(status=DeliveryOrder.STATUS_FAILED)),
              cancelled=Count('id', filter=Q(status=DeliveryOrder.STATUS_CANCELLED)),
              cash_collected=Sum('collected_amount', filter=Q(payment_method__in=['cash', 'mixed'])),
              total_value=Sum('total_value'),
          )
          .order_by('-delivered')
    )

    # Compute avg delivery time per driver
    avg_times = {}
    for driver_id in [r['assigned_driver'] for r in by_driver_raw]:
        times = list(
            DeliveryOrder.objects.filter(
                assigned_driver_id=driver_id,
                status=DeliveryOrder.STATUS_DELIVERED,
                dispatched_at__isnull=False,
                delivered_at__isnull=False,
                ordered_at__date__gte=date_from,
                ordered_at__date__lte=date_to,
            ).values_list('dispatched_at', 'delivered_at')
        )
        if times:
            avg_secs = sum((d - s).total_seconds() for s, d in times) / len(times)
            avg_times[driver_id] = round(avg_secs / 60, 1)

    drivers = []
    for r in by_driver_raw:
        total = r['total'] or 0
        delivered = r['delivered'] or 0
        drivers.append({
            'driver_id':     r['assigned_driver'],
            'driver_name':   r['assigned_driver__full_name'],
            'driver_mobile': r['assigned_driver__mobile'],
            'total':         total,
            'delivered':     delivered,
            'partial':       r['partial'] or 0,
            'failed':        r['failed'] or 0,
            'cancelled':     r['cancelled'] or 0,
            'success_rate':  round(delivered / total * 100, 1) if total else 0,
            'avg_mins':      avg_times.get(r['assigned_driver']),
            'cash_collected':round(float(r['cash_collected'] or 0), 2),
            'total_value':   round(float(r['total_value'] or 0), 2),
        })

    return Response({
        'date_from': date_from,
        'date_to':   date_to,
        'drivers':   drivers,
    })


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# F11 — Area Heatmap
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def delivery_area_heatmap(request):
    """
    GET /api/delivery/area-heatmap/?date_from=&date_to=&branch=
    Returns order density per governorate and area for map visualisation.
    """
    p = request.query_params
    date_from = p.get('date_from', _thirty_days_ago())
    date_to   = p.get('date_to',   timezone.localdate().isoformat())
    branch_id = p.get('branch')

    qs = DeliveryOrder.objects.filter(ordered_at__date__gte=date_from, ordered_at__date__lte=date_to)
    if branch_id:
        qs = qs.filter(branch_id=branch_id)

    # By governorate
    by_gov = list(
        qs.exclude(delivery_governorate='')
          .values('delivery_governorate')
          .annotate(
              orders=Count('id'),
              delivered=Count('id', filter=Q(status=DeliveryOrder.STATUS_DELIVERED)),
              revenue=Sum('total_value'),
              avg_value=Avg('total_value'),
          )
          .order_by('-orders')
    )

    # By area (top 20)
    by_area = list(
        qs.exclude(delivery_area='')
          .values('delivery_area', 'delivery_governorate')
          .annotate(
              orders=Count('id'),
              revenue=Sum('total_value'),
          )
          .order_by('-orders')[:20]
    )

    return Response({
        'date_from':     date_from,
        'date_to':       date_to,
        'by_governorate': [
            {
                'governorate': r['delivery_governorate'],
                'orders':      r['orders'],
                'delivered':   r['delivered'],
                'revenue':     round(float(r['revenue'] or 0), 2),
                'avg_value':   round(float(r['avg_value'] or 0), 2),
                'success_rate': round(r['delivered'] / r['orders'] * 100, 1) if r['orders'] else 0,
            }
            for r in by_gov
        ],
        'by_area': [
            {
                'area':        r['delivery_area'],
                'governorate': r['delivery_governorate'],
                'orders':      r['orders'],
                'revenue':     round(float(r['revenue'] or 0), 2),
            }
            for r in by_area
        ],
    })


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# F12 — Shift-Based Reporting
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SHIFTS = [
    {'name': 'الفجر',   'label': '🌙 فجر',   'start': 0,  'end': 8  },
    {'name': 'الصباح',  'label': '🌅 صباح',  'start': 8,  'end': 14 },
    {'name': 'الظهر',   'label': '☀️ ظهر',   'start': 14, 'end': 18 },
    {'name': 'المساء',  'label': '🌇 مساء',  'start': 18, 'end': 22 },
    {'name': 'الليل',   'label': '🌙 ليل',   'start': 22, 'end': 24 },
]


def _thirty_days_ago():
    from django.utils import timezone as tz
    import datetime
    return (tz.localdate() - datetime.timedelta(days=30)).isoformat()


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def delivery_shift_report(request):
    """
    GET /api/delivery/shift-report/?date_from=&date_to=&branch=
    Breaks down orders by time-of-day shift.
    """
    p = request.query_params
    date_from = p.get('date_from', timezone.localdate().isoformat())
    date_to   = p.get('date_to',   timezone.localdate().isoformat())
    branch_id = p.get('branch')

    qs = DeliveryOrder.objects.filter(ordered_at__date__gte=date_from, ordered_at__date__lte=date_to)
    if branch_id:
        qs = qs.filter(branch_id=branch_id)

    # Cairo is UTC+2 (or UTC+3 in summer) — use the local hour
    # We annotate with the hour of ordered_at
    from django.db.models.functions import ExtractHour
    hourly = dict(
        qs.annotate(h=ExtractHour('ordered_at'))
          .values('h')
          .annotate(n=Count('id'), rev=Sum('total_value'))
          .values_list('h', 'n')
    )
    hourly_rev = dict(
        qs.annotate(h=ExtractHour('ordered_at'))
          .values('h')
          .annotate(rev=Sum('total_value'))
          .values_list('h', 'rev')
    )

    result = []
    for shift in SHIFTS:
        hours = range(shift['start'], shift['end'])
        orders = sum(hourly.get(h, 0) for h in hours)
        revenue = sum(float(hourly_rev.get(h, 0) or 0) for h in hours)
        result.append({
            'shift':      shift['name'],
            'label':      shift['label'],
            'hours':      f'{shift["start"]}:00 – {shift["end"]}:00',
            'orders':     orders,
            'revenue':    round(revenue, 2),
            'avg_value':  round(revenue / orders, 2) if orders else 0,
        })

    peak = max(result, key=lambda x: x['orders'], default=None)
    return Response({
        'date_from': date_from,
        'date_to':   date_to,
        'shifts':    result,
        'peak_shift': peak['shift'] if peak else None,
        'hourly':    [{'hour': h, 'orders': hourly.get(h, 0)} for h in range(24)],
    })


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# F13 — Customer Location Memory
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def customer_delivery_profile(request):
    """
    GET /api/delivery/customer-profile/?phone=01012345678
    Returns customer's saved locations + order history summary for fast order entry.
    Falls back to SOFTECH dm_picsloc for GPS if no local records exist.
    """
    phone = request.query_params.get('phone', '').strip()
    if not phone:
        return Response({'detail': 'رقم الهاتف مطلوب.'}, status=status.HTTP_400_BAD_REQUEST)

    from apps.customers.models import Customer
    from .serializers import CustomerLocationSerializer

    # Find customer by phone (tail match for Egyptian numbers)
    tail = phone.replace(' ', '').replace('-', '')[-9:]
    customer = (
        Customer.objects.filter(phone__endswith=tail).first()
        or Customer.objects.filter(phone_alt__endswith=tail).first()
    )

    locations = []
    order_history = {}
    softech_gps = None

    if customer:
        # Saved locations
        locs = CustomerLocation.objects.filter(customer=customer).order_by('-is_default', 'label')
        locations = CustomerLocationSerializer(locs, many=True).data

        # Order history summary
        history_qs = DeliveryOrder.objects.filter(customer=customer)
        order_history = {
            'total':          history_qs.count(),
            'delivered':      history_qs.filter(status=DeliveryOrder.STATUS_DELIVERED).count(),
            'last_order_date': history_qs.order_by('-ordered_at').values_list('ordered_at', flat=True).first(),
            'last_address':   history_qs.exclude(delivery_address='').order_by('-ordered_at').values_list('delivery_address', flat=True).first(),
            'preferred_payment': (
                history_qs.values('payment_method')
                .annotate(n=Count('id'))
                .order_by('-n')
                .values_list('payment_method', flat=True)
                .first()
            ),
        }

        # Fall back to SOFTECH dm_picsloc if no local GPS
        if not any(l.get('latitude') for l in locations) and customer.softech_pic:
            try:
                from apps.branches.models import Branch
                from config.sybase import get_branch_connection
                for branch in Branch.objects.filter(db_host__gt='').order_by('softech_branch_id')[:1]:
                    conn = get_branch_connection(branch.db_host, branch.db_port, branch.db_name)
                    cursor = conn.cursor()
                    cursor.execute(
                        'SELECT latitude_x, longitude_y FROM dm_picsloc WHERE phcode = ?',
                        [customer.softech_pic]
                    )
                    row = cursor.fetchone()
                    if row and row[0] and row[1]:
                        softech_gps = {'lat': float(row[0]), 'lng': float(row[1])}
                    conn.close()
                    break
            except Exception:
                pass

    return Response({
        'found':         customer is not None,
        'customer': {
            'id':      customer.id if customer else None,
            'name':    customer.name if customer else None,
            'phone':   customer.phone if customer else phone,
            'phone_alt': customer.phone_alt if customer else None,
            'softech_pic': customer.softech_pic if customer else None,
        },
        'locations':      locations,
        'softech_gps':    softech_gps,
        'order_history':  order_history,
    })


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# F14 — CSAT Collection
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delivery_submit_csat(request, pk):
    """
    POST /api/delivery/{id}/csat/
    Body: { score: 1-5, feedback: '' }
    Staff enters customer rating; also creates/updates CSAT record.
    """
    order = get_object_or_404(DeliveryOrder, pk=pk)
    score    = request.data.get('score')
    feedback = request.data.get('feedback', '').strip()
    channel  = request.data.get('channel', 'manual')

    try:
        score = int(score)
        if not 1 <= score <= 5:
            raise ValueError()
    except (TypeError, ValueError):
        return Response({'detail': 'التقييم يجب أن يكون بين 1 و 5.'}, status=status.HTTP_400_BAD_REQUEST)

    csat, _ = DeliveryCSAT.objects.update_or_create(
        order=order,
        defaults={
            'score':        score,
            'feedback':     feedback,
            'channel':      channel,
            'responded_at': timezone.now(),
        },
    )

    # Update customer profile complaint risk if low score
    if score <= 2 and order.customer:
        try:
            from apps.customers.models import Customer
            c = order.customer
            current = c.complaint_risk_score or 0
            c.complaint_risk_score = min(100, current + 15)
            c.save(update_fields=['complaint_risk_score'])
        except Exception:
            pass

    return Response({
        'id':           csat.id,
        'score':        csat.score,
        'feedback':     csat.feedback,
        'responded_at': csat.responded_at,
        'order_number': order.order_number,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def delivery_csat_report(request):
    """
    GET /api/delivery/csat-report/?date_from=&date_to=&branch=
    Returns CSAT summary: avg score, distribution, low-score orders.
    """
    p = request.query_params
    date_from = p.get('date_from', _thirty_days_ago())
    date_to   = p.get('date_to',   timezone.localdate().isoformat())
    branch_id = p.get('branch')

    qs = DeliveryCSAT.objects.filter(
        order__ordered_at__date__gte=date_from,
        order__ordered_at__date__lte=date_to,
        score__isnull=False,
    )
    if branch_id:
        qs = qs.filter(order__branch_id=branch_id)

    from django.db.models import Avg as DjAvg
    agg = qs.aggregate(avg=DjAvg('score'), total=Count('id'))

    dist = {str(i): qs.filter(score=i).count() for i in range(1, 6)}

    low_scores = list(
        qs.filter(score__lte=2)
          .select_related('order', 'order__customer')
          .order_by('-order__ordered_at')[:10]
          .values(
              'order__order_number', 'order__customer_name',
              'order__customer_phone', 'score', 'feedback',
              'responded_at',
          )
    )

    return Response({
        'date_from':   date_from,
        'date_to':     date_to,
        'total':       agg['total'] or 0,
        'avg_score':   round(float(agg['avg'] or 0), 2),
        'distribution':dist,
        'low_scores':  low_scores,
        'wa_pending':  DeliveryCSAT.objects.filter(wa_sent=False, order__status=DeliveryOrder.STATUS_DELIVERED).count(),
    })


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Route batching (persisted runs) + dispatch
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
from .models import DeliveryRoute  # noqa: E402
from .serializers import DeliveryRouteSerializer  # noqa: E402


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def delivery_routes(request):
    """GET list (?date=&driver=&status=) · POST create {driver_id, route_date?, order_ids:[ordered], notes?}."""
    if request.method == 'GET':
        qs = DeliveryRoute.objects.select_related('driver', 'branch').all()
        if request.query_params.get('date'):
            qs = qs.filter(route_date=request.query_params['date'])
        if request.query_params.get('driver'):
            qs = qs.filter(driver_id=request.query_params['driver'])
        if request.query_params.get('status'):
            qs = qs.filter(status=request.query_params['status'])
        return Response(DeliveryRouteSerializer(qs[:200], many=True).data)

    driver_id = request.data.get('driver_id')
    order_ids = request.data.get('order_ids') or []
    if not driver_id or not isinstance(order_ids, list) or not order_ids:
        return Response({'detail': 'حدد السائق والطلبات'}, status=status.HTTP_400_BAD_REQUEST)
    driver = DeliveryDriver.objects.filter(pk=driver_id).first()
    if not driver:
        return Response({'detail': 'السائق غير موجود'}, status=status.HTTP_400_BAD_REQUEST)

    route = DeliveryRoute.objects.create(
        branch=driver.branch, driver=driver,
        route_date=request.data.get('route_date') or timezone.localdate(),
        notes=request.data.get('notes', ''), created_by=request.user,
    )
    seq, added = 1, 0
    for oid in order_ids:
        o = DeliveryOrder.objects.filter(pk=oid).first()
        if not o:
            continue
        o.route = route
        o.route_sequence = seq
        # Assign the driver if the order can still be assigned (READY → ASSIGNED).
        if o.status == DeliveryOrder.STATUS_READY:
            o.assignments.filter(is_current=True).update(is_current=False)
            DeliveryAssignment.objects.create(
                order=o, driver=driver, driver_name=driver.full_name,
                is_current=True, assigned_by=request.user, notes='ضمن مسار')
            prev = o.status
            o.status = DeliveryOrder.STATUS_ASSIGNED
            o.assigned_at = timezone.now()
            o.assigned_driver = driver
            _log_transition(o, prev, DeliveryOrder.STATUS_ASSIGNED, request.user, notes=f'مسار ROUTE-{route.pk}')
        else:
            o.assigned_driver = o.assigned_driver or driver
        o.save()
        seq += 1
        added += 1
    return Response({**DeliveryRouteSerializer(route).data, 'added': added}, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def delivery_route_detail(request, pk):
    route = get_object_or_404(DeliveryRoute, pk=pk)
    return Response(DeliveryRouteSerializer(route).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delivery_route_dispatch(request, pk):
    """Dispatch the whole route: move its orders to out-for-delivery in one action."""
    route = get_object_or_404(DeliveryRoute, pk=pk)
    now = timezone.now()
    moved = 0
    dispatchable = {DeliveryOrder.STATUS_READY, DeliveryOrder.STATUS_ASSIGNED, DeliveryOrder.STATUS_DRIVER_ACCEPTED}
    for o in route.orders.all():
        if o.status not in dispatchable:
            continue
        prev = o.status
        if not o.driver_accepted_at:
            o.driver_accepted_at = now
        o.status = DeliveryOrder.STATUS_OUT
        o.dispatched_at = now
        o.assigned_driver = o.assigned_driver or route.driver
        o.save(update_fields=['status', 'driver_accepted_at', 'dispatched_at', 'assigned_driver', 'updated_at'])
        _log_transition(o, prev, DeliveryOrder.STATUS_OUT, request.user, notes=f'انطلاق مسار ROUTE-{route.pk}')
        moved += 1
    route.status = DeliveryRoute.STATUS_DISPATCHED
    route.dispatched_at = now
    route.save(update_fields=['status', 'dispatched_at'])
    return Response({**DeliveryRouteSerializer(route).data, 'dispatched': moved})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def driver_app_my_route(request):
    """GET /api/delivery/app/my-route/ — the current driver's active route for today (sequenced)."""
    driver = getattr(getattr(request.user, 'staff_profile', None), 'driver_profile', None)
    if not driver:
        return Response({'detail': 'ليس لديك ملف سائق مرتبط.'}, status=status.HTTP_403_FORBIDDEN)
    route = (DeliveryRoute.objects
             .filter(driver=driver, route_date=timezone.localdate())
             .exclude(status=DeliveryRoute.STATUS_CANCELLED)
             .order_by('-created_at').first())
    if not route:
        return Response({'route': None, 'orders': []})
    return Response(DeliveryRouteSerializer(route).data)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Branch-user backfill — fill pickup / delivery confirmation a rider didn't log.
# No geofence (manual, occasional); flags the order as a manual estimate.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_BACKFILL_ROLES = frozenset({'admin', 'supervisor', 'call_center', 'pharmacist'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delivery_backfill(request, pk):
    """
    POST /api/delivery/{id}/backfill/   (branch users only)

    Body (all optional):
      confirm_pickup     : bool  — mark as picked up / out-for-delivery
      confirm_delivery   : bool  — mark delivered (captures POD)
      driver_id          : int   — assign a driver if none
      delivery_lat/lng   : float — APPROXIMATE drop location chosen on the map
      pod_recipient_name, pod_note, collected_amount
    """
    profile = getattr(request.user, 'staff_profile', None)
    if not (profile and profile.role in _BACKFILL_ROLES):
        return Response({'detail': 'لا تملك صلاحية الإدخال اليدوي للتوصيل'},
                        status=status.HTTP_403_FORBIDDEN)
    order = get_object_or_404(DeliveryOrder, pk=pk)
    now = timezone.now()
    changed = []

    # Optional driver assignment
    drv_id = request.data.get('driver_id')
    if drv_id and not order.assigned_driver_id:
        drv = DeliveryDriver.objects.filter(pk=drv_id).first()
        if drv:
            order.assigned_driver = drv
            order.assignments.filter(is_current=True).update(is_current=False)
            DeliveryAssignment.objects.create(order=order, driver=drv, driver_name=drv.full_name,
                                              is_current=True, assigned_by=request.user, notes='إدخال يدوي')
            changed.append('assigned_driver')

    # Pickup confirmation (no geofence)
    if request.data.get('confirm_pickup') and order.status in (
        DeliveryOrder.STATUS_READY, DeliveryOrder.STATUS_ASSIGNED, DeliveryOrder.STATUS_DRIVER_ACCEPTED):
        prev = order.status
        if not order.driver_accepted_at:
            order.driver_accepted_at = now
        order.status = DeliveryOrder.STATUS_OUT
        order.dispatched_at = order.dispatched_at or now
        order.pod_backfilled = True
        changed += ['status', 'driver_accepted_at', 'dispatched_at', 'pod_backfilled']
        _log_transition(order, prev, DeliveryOrder.STATUS_OUT, request.user,
                        notes=f'تأكيد استلام يدوي — {profile.full_name}')

    # Approximate drop location (from the map) → recompute distance
    lat = request.data.get('delivery_lat'); lng = request.data.get('delivery_lng')
    if lat not in (None, '') and lng not in (None, ''):
        try:
            order.delivery_lat = float(lat); order.delivery_lng = float(lng)
            order.pod_lat = float(lat); order.pod_lng = float(lng)
            order.pod_backfilled = True
            changed += ['delivery_lat', 'delivery_lng', 'pod_lat', 'pod_lng', 'pod_backfilled']
            b = order.branch
            if b and b.latitude is not None and b.longitude is not None:
                order.delivery_distance_km = round(
                    _haversine_m(b.latitude, b.longitude, order.delivery_lat, order.delivery_lng) / 1000.0, 2)
                changed.append('delivery_distance_km')
        except (ValueError, TypeError):
            return Response({'detail': 'إحداثيات غير صالحة'}, status=status.HTTP_400_BAD_REQUEST)

    # POD fields
    if request.data.get('pod_recipient_name'):
        order.pod_recipient_name = request.data['pod_recipient_name'][:120]; changed.append('pod_recipient_name')
    if request.data.get('pod_note'):
        order.pod_note = request.data['pod_note'][:500]; changed.append('pod_note')

    # Delivery confirmation (no geofence)
    if request.data.get('confirm_delivery') and order.status not in DeliveryOrder.TERMINAL_STATUSES:
        prev = order.status
        order.status = DeliveryOrder.STATUS_DELIVERED
        order.delivered_at = now
        order.pod_backfilled = True
        col = request.data.get('collected_amount')
        if col is not None:
            order.collected_amount = col
        changed += ['status', 'delivered_at', 'collected_amount', 'pod_backfilled']
        _log_transition(order, prev, DeliveryOrder.STATUS_DELIVERED, request.user,
                        notes=f'تأكيد تسليم يدوي — {profile.full_name}')
        if order.payment_method in (DeliveryOrder.PAY_CASH, DeliveryOrder.PAY_MIXED):
            expected = order.total_with_fees
            collected_val = order.collected_amount or expected
            variance = collected_val - expected
            CashCollection.objects.update_or_create(order=order, defaults={
                'expected_amount': expected, 'collected_amount': collected_val,
                'status': 'shortage' if variance < 0 else 'overage' if variance > 0 else 'collected',
                'collection_time': now, 'collected_by': request.user,
            })

    if not changed:
        return Response({'detail': 'لا يوجد ما يُحدَّث'}, status=status.HTTP_400_BAD_REQUEST)
    order.save()
    return Response(DeliveryOrderSerializer(order).data)
