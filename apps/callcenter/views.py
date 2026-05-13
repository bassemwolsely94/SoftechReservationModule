from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.db.models import Count, Q

from .models import CallLog, AddressUpdate
from .serializers import (
    CallLogListSerializer, CallLogDetailSerializer, CallLogCreateSerializer,
    AddressUpdateSerializer, AddressUpdateWriteSerializer,
)


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


class CallLogViewSet(viewsets.ModelViewSet):
    """
    Full CRUD for call logs.
    Permissions:
      - call_center + admin: full access to all logs
      - branch staff: own logs only
    """
    permission_classes = [IsAuthenticated]
    filter_backends    = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields   = ['direction', 'status', 'purpose', 'handled_by', 'branch']
    search_fields      = [
        'phone_number', 'caller_name', 'notes', 'summary',
        'customer__name', 'customer__phone',
    ]
    ordering_fields    = ['called_at', 'duration_seconds']
    ordering           = ['-called_at']

    def get_queryset(self):
        qs = CallLog.objects.select_related(
            'customer', 'local_customer',
            'handled_by__user', 'branch',
            'reservation', 'followup_task',
        ).prefetch_related('address_updates')

        profile = _profile(self.request)
        if not profile:
            return qs.none()

        # Call center + admin see all
        if profile.role in ('admin', 'call_center'):
            return qs

        # Branch staff see only their branch
        if profile.branch:
            return qs.filter(branch=profile.branch)

        return qs.none()

    def get_serializer_class(self):
        if self.action == 'list':
            return CallLogListSerializer
        if self.action == 'create':
            return CallLogCreateSerializer
        return CallLogDetailSerializer

    def perform_create(self, serializer):
        profile = _profile(self.request)
        call = serializer.save(
            handled_by=profile,
            branch=profile.branch if profile else None,
        )

        # Audit log (Phase 7 — non-blocking)
        try:
            from apps.audit.models import AuditLog
            AuditLog.log(
                'reservation_created',
                user=profile,
                note=f'Call log created: {call.phone_number}',
            )
        except Exception:
            pass

        # If linked to a follow-up, mark it as called
        if call.followup_task and call.followup_task.status == 'pending':
            try:
                from apps.followups.services import mark_task_called
                mark_task_called(call.followup_task, note=call.summary, staff=profile)
            except Exception:
                pass

    # ── Phone lookup ──────────────────────────────────────────────────────────

    @action(detail=False, methods=['get'], url_path='lookup')
    def lookup(self, request):
        """
        GET /api/callcenter/calls/lookup/?phone=01012345678
        Returns customer info + last 5 calls for the phone number.
        Used by call center staff when a call comes in.
        """
        phone = request.query_params.get('phone', '').strip()
        if not phone:
            return Response({'detail': 'phone مطلوب'}, status=400)

        tail = phone.replace(' ', '')[-9:]
        result = {
            'phone':          phone,
            'customer':       None,
            'local_customer': None,
            'recent_calls':   [],
            'open_followups': [],
            'open_reservations': [],
            'active_demands': [],
        }

        # Match Customer
        try:
            from apps.customers.models import Customer
            customer = Customer.objects.filter(
                Q(phone__endswith=tail) | Q(phone_alt__endswith=tail)
            ).select_related('preferred_branch').first()

            if customer:
                result['customer'] = {
                    'id':            customer.id,
                    'name':          customer.name,
                    'phone':         customer.phone,
                    'phone_alt':     customer.phone_alt,
                    'softech_id':    customer.softech_id,
                    'type_label':    customer.customer_type_label,
                    'branch':        customer.preferred_branch.name_ar if customer.preferred_branch else None,
                    'discount':      float(customer.discount_percent),
                    'chronic_conditions': customer.chronic_conditions,
                    'default_location': None,
                }

                # Default delivery location
                loc = customer.default_location
                if loc:
                    result['customer']['default_location'] = {
                        'address': loc.address_text,
                        'area':    loc.area,
                        'maps_url': loc.maps_url,
                        'whatsapp_url': loc.whatsapp_url,
                    }

                # Open follow-up tasks
                from apps.followups.models import FollowUpTask
                followups = FollowUpTask.objects.filter(
                    customer=customer, status__in=('pending', 'called')
                ).select_related('item').order_by('due_date')[:5]
                result['open_followups'] = [
                    {
                        'id':       ft.id,
                        'item':     ft.item.name if ft.item else '—',
                        'due_date': str(ft.due_date),
                        'status':   ft.status,
                    }
                    for ft in followups
                ]

                # Open reservations
                from apps.reservations.models import Reservation
                reservations = Reservation.objects.filter(
                    customer=customer,
                    status__in=('pending', 'available', 'contacted', 'confirmed'),
                ).select_related('item', 'branch').order_by('-created_at')[:5]
                result['open_reservations'] = [
                    {
                        'id':     r.id,
                        'item':   r.item.name,
                        'branch': r.branch.name_ar,
                        'status': r.status,
                    }
                    for r in reservations
                ]

                # Active demand requests
                try:
                    from apps.demand.models import DemandRequest
                    demands = DemandRequest.objects.filter(
                        customer=customer,
                        status__in=('new', 'assigned', 'follow_up', 'waiting'),
                    ).select_related('branch').order_by('-created_at')[:5]
                    result['active_demands'] = [
                        {
                            'id':     d.id,
                            'number': d.demand_number,
                            'branch': d.branch.name_ar,
                            'status': d.status,
                        }
                        for d in demands
                    ]
                except Exception:
                    pass

        except Exception:
            pass

        # Match LocalCustomer (PIC)
        try:
            from apps.erp.models import LocalCustomer
            lc = LocalCustomer.objects.filter(
                phone__endswith=tail
            ).select_related('branch').first()
            if lc:
                result['local_customer'] = {
                    'phcode':   lc.phcode,
                    'name':     lc.name,
                    'phone':    lc.phone,
                    'branch':   lc.branch.name_ar if lc.branch else lc.erp_branch_code,
                    'type':     lc.customer_type,
                    'address':  lc.address,
                    'whatsapp': lc.whatsapp_url,
                }
        except Exception:
            pass

        # Recent calls for this number
        recent = CallLog.objects.filter(
            phone_number__endswith=tail
        ).select_related('handled_by__user').order_by('-called_at')[:5]
        result['recent_calls'] = CallLogListSerializer(recent, many=True).data

        return Response(result)

    # ── Address updates ───────────────────────────────────────────────────────

    @action(detail=True, methods=['get', 'post'], url_path='address-updates')
    def address_updates(self, request, pk=None):
        call = self.get_object()

        if request.method == 'GET':
            return Response(
                AddressUpdateSerializer(call.address_updates.all(), many=True).data
            )

        # POST — collect new address update
        if not call.customer:
            return Response(
                {'detail': 'لا يمكن إضافة عنوان بدون عميل مرتبط بالمكالمة'},
                status=400,
            )

        serializer = AddressUpdateWriteSerializer(data={
            **request.data,
            'customer': call.customer.id,
        })
        serializer.is_valid(raise_exception=True)
        update = serializer.save(
            call_log=call,
            collected_by=_profile(request),
        )
        return Response(AddressUpdateSerializer(update).data, status=201)

    @action(detail=True, methods=['post'], url_path=r'address-updates/(?P<update_id>[0-9]+)/apply')
    def apply_address_update(self, request, pk=None, update_id=None):
        """Apply a pending address update → creates CustomerLocation."""
        call = self.get_object()
        try:
            update = call.address_updates.get(pk=update_id, status='pending')
        except AddressUpdate.DoesNotExist:
            return Response(status=404)

        location = update.apply(applied_by=_profile(request))
        if location:
            return Response({
                'applied': True,
                'location_id': location.id,
                'address': location.address_text,
                'whatsapp_url': location.whatsapp_url,
            })
        return Response({'applied': False, 'detail': 'فشل تطبيق العنوان'}, status=400)

    # ── Callbacks ─────────────────────────────────────────────────────────────

    @action(detail=False, methods=['get'], url_path='pending-callbacks')
    def pending_callbacks(self, request):
        """GET /api/callcenter/calls/pending-callbacks/ — due callbacks."""
        qs = CallLog.objects.filter(
            status='callback',
            callback_due__lte=timezone.now(),
        ).select_related('customer', 'handled_by__user').order_by('callback_due')

        profile = _profile(request)
        if profile and profile.role not in ('admin', 'call_center'):
            qs = qs.filter(handled_by=profile)

        return Response(CallLogListSerializer(qs, many=True).data)

    # ── Dashboard ─────────────────────────────────────────────────────────────

    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        """GET /api/callcenter/calls/dashboard/ — call center KPIs."""
        from datetime import date, timedelta
        from django.db.models import Avg

        today  = date.today()
        cutoff = timezone.now() - timedelta(days=30)
        qs     = CallLog.objects.filter(called_at__gte=cutoff)

        profile = _profile(request)
        if profile and profile.role == 'call_center' and profile.branch:
            qs = qs.filter(branch=profile.branch)

        stats = {
            'total_calls':       qs.count(),
            'today':             qs.filter(called_at__date=today).count(),
            'answered':          qs.filter(status='answered').count(),
            'no_answer':         qs.filter(status='no_answer').count(),
            'pending_callbacks': CallLog.objects.filter(
                status='callback', callback_due__lte=timezone.now()
            ).count(),
            'by_purpose': list(
                qs.values('purpose').annotate(count=Count('id')).order_by('-count')
            ),
            'by_staff': list(
                qs.values('handled_by__user__first_name', 'handled_by__user__last_name')
                .annotate(count=Count('id'))
                .order_by('-count')[:10]
            ),
            'address_updates_pending': AddressUpdate.objects.filter(status='pending').count(),
            'avg_duration_seconds': qs.filter(
                status='answered', duration_seconds__gt=0
            ).aggregate(avg=Avg('duration_seconds'))['avg'] or 0,
        }
        return Response(stats)


class AddressUpdateViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only global list of address updates — admin only."""
    permission_classes = [IsAuthenticated]
    serializer_class   = AddressUpdateSerializer
    filter_backends    = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields   = ['status', 'customer']
    ordering           = ['-collected_at']

    def get_queryset(self):
        profile = _profile(self.request)
        if not profile or profile.role not in ('admin', 'call_center'):
            return AddressUpdate.objects.none()
        return AddressUpdate.objects.select_related(
            'customer', 'call_log', 'applied_by__user'
        )

    @action(detail=True, methods=['post'])
    def apply(self, request, pk=None):
        """POST /api/callcenter/address-updates/{id}/apply/"""
        update = self.get_object()
        if update.status != 'pending':
            return Response({'detail': 'تم تطبيق هذا التحديث بالفعل'}, status=400)

        location = update.apply(applied_by=_profile(request))
        if location:
            return Response({
                'applied':     True,
                'location_id': location.id,
                'address':     location.address_text,
            })
        return Response({'applied': False}, status=400)
