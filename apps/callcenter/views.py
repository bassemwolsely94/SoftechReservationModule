"""
apps/callcenter/views.py — v2

ViewSets:
  CallLogViewSet        — CRUD + lookup, dashboard, attachments, AI summarize,
                          create-case, create-followup, quality scoring
  CustomerCaseViewSet   — CRUD + state machine (assign, escalate, resolve, close,
                          csat, add-note, add-event)
  AddressUpdateViewSet  — Read-only list + apply action
"""
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.db.models import Count, Q, Avg

from .models import CallLog, AddressUpdate, CallLogAttachment, CustomerCase, CaseEvent, CallQualityScore, CallItem
from .serializers import (
    CallLogListSerializer, CallLogDetailSerializer, CallLogCreateSerializer,
    AddressUpdateSerializer, AddressUpdateWriteSerializer,
    CallLogAttachmentSerializer,
    CustomerCaseListSerializer, CustomerCaseDetailSerializer,
    CustomerCaseCreateSerializer, CustomerCaseUpdateSerializer,
    CaseEventSerializer,
    CallQualityScoreSerializer,
    CallItemSerializer,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _profile(request):
    return getattr(request.user, 'staff_profile', None)


def _is_supervisor_or_admin(profile):
    return profile and profile.role in ('admin', 'supervisor', 'quality_manager', 'call_center')


# ─────────────────────────────────────────────────────────────────────────────
# CallLogViewSet
# ─────────────────────────────────────────────────────────────────────────────

class CallLogViewSet(viewsets.ModelViewSet):
    """
    Full CRUD for call logs.
    Permissions:
      - call_center / supervisor / admin: full access to all logs
      - branch staff: own logs only
    """
    permission_classes = [IsAuthenticated]
    filter_backends    = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields   = ['direction', 'status', 'purpose', 'handled_by', 'branch', 'ai_sentiment']
    search_fields      = [
        'phone_number', 'caller_name', 'notes', 'summary',
        'customer__name', 'customer__phone',
    ]
    ordering_fields    = ['called_at', 'duration_seconds', 'quality_score']
    ordering           = ['-called_at']

    def get_queryset(self):
        qs = CallLog.objects.select_related(
            'customer', 'handled_by__user', 'branch',
            'reservation', 'followup_task', 'case',
        ).prefetch_related('address_updates', 'attachments', 'items__item')

        profile = _profile(self.request)
        if not profile:
            return qs.none()

        # Call center / supervisor / admin see all
        if profile.role in ('admin', 'call_center', 'supervisor', 'quality_manager'):
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

        # Audit log (non-blocking)
        try:
            from apps.audit.models import AuditLog
            AuditLog.log(
                'call_log_created',
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
        GET /api/callcenter/calls/lookup/?phone=01012345678[&customer_id=42]

        Always returns:
          customers  — list of ALL customers matching that phone (for picker)
          customer   — full 360 context for the selected/auto-selected customer
          recent_calls — last 5 calls for the number

        When multiple matches exist and no customer_id is provided, `customer`
        is None and the frontend shows the picker panel. Once the agent picks
        one, re-query with &customer_id=<id> to load the full context.
        """
        phone       = request.query_params.get('phone', '').strip()
        customer_id = request.query_params.get('customer_id', '').strip()
        if not phone:
            return Response({'detail': 'phone مطلوب'}, status=400)

        tail = phone.replace(' ', '')[-9:]
        result = {
            'phone':             phone,
            'customers':         [],   # summary list — always populated
            'customer':          None, # full 360 — populated only for selected customer
            'recent_calls':      [],
            'open_followups':    [],
            'open_reservations': [],
            'active_demands':    [],
            'open_cases':        [],
            'purchase_history':  None,
        }

        try:
            from apps.customers.models import Customer

            # All customers sharing this phone (up to 10)
            customers_qs = Customer.objects.filter(
                Q(phone__endswith=tail) | Q(phone_alt__endswith=tail)
            ).select_related('preferred_branch').order_by('-created_at')[:10]
            customers_qs = list(customers_qs)

            # ── Build summary list (always returned — used by picker) ──────────
            result['customers'] = [
                {
                    'id':                   c.id,
                    'name':                 c.name,
                    'phone':                c.phone,
                    'phone_alt':            c.phone_alt,
                    'softech_id':           c.softech_id,
                    'softech_pic':          c.softech_pic,
                    'type_label':           c.customer_type_label,
                    'branch':               c.preferred_branch.name_ar if c.preferred_branch else None,
                    'branch_id':            c.preferred_branch_id,
                    'segment':              c.segment or None,
                    'ltv':                  float(c.ltv) if c.ltv else None,
                    'days_since_last_visit': c.days_since_last_visit,
                    'complaint_risk_score':  c.complaint_risk_score,
                }
                for c in customers_qs
            ]

            # ── Determine which customer to load full 360 context for ─────────
            # Priority: explicit customer_id param → auto-select when only one match
            selected = None
            if customer_id:
                selected = next((c for c in customers_qs if str(c.id) == customer_id), None)
            elif len(customers_qs) == 1:
                selected = customers_qs[0]

            if selected:
                result['customer'] = {
                    'id':                selected.id,
                    'name':              selected.name,
                    'phone':             selected.phone,
                    'phone_alt':         selected.phone_alt,
                    'softech_id':        selected.softech_id,
                    'softech_pic':       selected.softech_pic,
                    'type_label':        selected.customer_type_label,
                    'branch':            selected.preferred_branch.name_ar if selected.preferred_branch else None,
                    'branch_id':         selected.preferred_branch_id,
                    'discount':          float(selected.discount_percent),
                    'chronic_conditions': selected.chronic_conditions,
                    'segment':           selected.segment or None,
                    'ltv':               float(selected.ltv) if selected.ltv else None,
                    'days_since_last_visit': selected.days_since_last_visit,
                    'complaint_risk_score':  selected.complaint_risk_score,
                    'default_location':  None,
                }

                # Default delivery location
                try:
                    loc = selected.default_location
                    if loc:
                        result['customer']['default_location'] = {
                            'address':      loc.address_text,
                            'area':         loc.area,
                            'maps_url':     loc.maps_url,
                            'whatsapp_url': loc.whatsapp_url,
                        }
                except Exception:
                    pass

                # Open follow-up tasks
                try:
                    from apps.followups.models import FollowUpTask
                    followups = FollowUpTask.objects.filter(
                        customer=selected, status__in=('pending', 'called')
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
                except Exception:
                    pass

                # Open reservations
                try:
                    from apps.reservations.models import Reservation
                    reservations = Reservation.objects.filter(
                        customer=selected,
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
                except Exception:
                    pass

                # Active demand requests
                try:
                    from apps.demand.models import DemandRecord
                    demands = DemandRecord.objects.filter(
                        customer=selected,
                        status__in=('new', 'assigned', 'follow_up', 'waiting'),
                    ).select_related('branch').order_by('-created_at')[:5]
                    result['active_demands'] = [
                        {
                            'id':     d.id,
                            'number': getattr(d, 'demand_number', d.id),
                            'branch': d.branch.name_ar if d.branch else '—',
                            'status': d.status,
                        }
                        for d in demands
                    ]
                except Exception:
                    pass

                # Open / active cases
                try:
                    open_cases = CustomerCase.objects.filter(
                        customer=selected,
                        status__in=('open', 'working', 'waiting', 'escalated'),
                    ).select_related('assigned_to__user').order_by('-created_at')[:5]
                    result['open_cases'] = [
                        {
                            'id':          c.id,
                            'case_number': c.case_number,
                            'category':    c.get_category_display(),
                            'status':      c.get_status_display(),
                            'title':       c.title,
                            'assigned_to': c.assigned_to.full_name if c.assigned_to else None,
                        }
                        for c in open_cases
                    ]
                except Exception:
                    pass

                # Purchase history — last 365 days (sales only, doc_code='115')
                try:
                    from datetime import date as _date, timedelta as _td
                    from apps.customers.models import PurchaseHistory
                    from collections import defaultdict as _dd
                    cutoff  = _date.today() - _td(days=365)
                    ph_qs   = list(
                        PurchaseHistory.objects.filter(
                            customer=selected,
                            doc_code='115',
                            invoice_date__date__gte=cutoff,
                        ).select_related('branch').order_by('-invoice_date')[:60]
                    )
                    total_spend  = sum(float(p.total_amount) for p in ph_qs)
                    visit_count  = len(ph_qs)
                    monthly = _dd(lambda: {'count': 0, 'total': 0.0})
                    for p in ph_qs:
                        if p.invoice_date:
                            key = f"{p.invoice_date.year}-{p.invoice_date.month:02d}"
                            monthly[key]['count'] += 1
                            monthly[key]['total'] += float(p.total_amount)
                    result['purchase_history'] = {
                        'total_365d':   round(total_spend, 2),
                        'visit_count':  visit_count,
                        'avg_basket':   round(total_spend / visit_count, 2) if visit_count else 0,
                        'months': [
                            {'month': k, 'count': v['count'], 'total': round(v['total'], 2)}
                            for k, v in sorted(monthly.items(), reverse=True)[:12]
                        ],
                        'recent': [
                            {
                                'date':   p.invoice_date.strftime('%Y-%m-%d') if p.invoice_date else None,
                                'amount': float(p.total_amount),
                                'branch': p.branch.name_ar if p.branch_id else '—',
                            }
                            for p in ph_qs[:10]
                        ],
                    }
                except Exception:
                    result['purchase_history'] = None

        except Exception:
            pass

        # Recent calls for this number (regardless of which customer is selected)
        recent = CallLog.objects.filter(
            phone_number__endswith=tail
        ).select_related('handled_by__user').order_by('-called_at')[:5]
        result['recent_calls'] = CallLogListSerializer(recent, many=True).data

        return Response(result)

    # ── Attachments ───────────────────────────────────────────────────────────

    @action(detail=True, methods=['get', 'post'], url_path='attachments')
    def attachments(self, request, pk=None):
        """GET/POST /api/callcenter/calls/{id}/attachments/"""
        call = self.get_object()

        if request.method == 'GET':
            return Response(
                CallLogAttachmentSerializer(
                    call.attachments.all(), many=True, context={'request': request}
                ).data
            )

        # POST — upload attachment
        serializer = CallLogAttachmentSerializer(
            data=request.data, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(call_log=call, uploaded_by=_profile(request))
        return Response(serializer.data, status=201)

    @action(detail=True, methods=['delete'], url_path=r'attachments/(?P<att_id>[0-9]+)')
    def delete_attachment(self, request, pk=None, att_id=None):
        """DELETE /api/callcenter/calls/{id}/attachments/{att_id}/"""
        call = self.get_object()
        try:
            att = call.attachments.get(pk=att_id)
        except CallLogAttachment.DoesNotExist:
            return Response(status=404)

        profile = _profile(request)
        if not _is_supervisor_or_admin(profile) and att.uploaded_by != profile:
            return Response({'detail': 'غير مسموح'}, status=403)

        att.file.delete(save=False)
        att.delete()
        return Response(status=204)

    # ── AI Summarize ──────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='summarize')
    def summarize(self, request, pk=None):
        """
        POST /api/callcenter/calls/{id}/summarize/
        Triggers Gemini AI summarization asynchronously.
        Returns immediately; the call log fields are updated in the background.
        """
        call = self.get_object()

        if not call.notes and not call.voice_transcript:
            return Response(
                {'detail': 'لا يوجد محتوى للتلخيص (notes أو voice_transcript مطلوب)'},
                status=400,
            )

        # Non-blocking: fire in thread
        try:
            from threading import Thread
            from apps.callcenter.ai import summarize_call_async
            Thread(target=summarize_call_async, args=(call.pk,), daemon=True).start()
        except Exception as e:
            return Response({'detail': f'فشل تشغيل التلخيص: {e}'}, status=500)

        return Response({'queued': True, 'call_id': call.pk})

    # ── Case management from call ─────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='create-case')
    def create_case(self, request, pk=None):
        """
        POST /api/callcenter/calls/{id}/create-case/
        Body: { category, priority, title, description, sla_due (opt) }
        Creates a new CustomerCase and links it to this call.
        """
        call = self.get_object()

        if not call.customer:
            return Response({'detail': 'لا يمكن فتح حالة بدون عميل مرتبط'}, status=400)

        serializer = CustomerCaseCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        profile = _profile(request)
        case = serializer.save(
            customer=call.customer,
            branch=call.branch,
            opened_by=profile,
        )

        # Link call to the new case
        call.case = case
        call.save(update_fields=['case'])

        # Log opening event
        case._log_event(f'حالة مفتوحة من مكالمة #{call.pk}', profile)

        return Response(CustomerCaseDetailSerializer(case).data, status=201)

    @action(detail=True, methods=['patch'], url_path='link-case')
    def link_case(self, request, pk=None):
        """
        PATCH /api/callcenter/calls/{id}/link-case/
        Body: { case_id: 42 }
        Links an existing case to this call.
        """
        call = self.get_object()
        case_id = request.data.get('case_id')
        if not case_id:
            return Response({'detail': 'case_id مطلوب'}, status=400)

        try:
            case = CustomerCase.objects.get(pk=case_id)
        except CustomerCase.DoesNotExist:
            return Response({'detail': 'الحالة غير موجودة'}, status=404)

        call.case = case
        call.save(update_fields=['case'])
        return Response({'linked': True, 'case_id': case.pk, 'case_number': case.case_number})

    # ── Follow-up creation from call ──────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='create-followup')
    def create_followup(self, request, pk=None):
        """
        POST /api/callcenter/calls/{id}/create-followup/
        Body: { due_date, notes, item_id (opt) }
        Creates a FollowUpTask linked to the call's customer.
        """
        call = self.get_object()
        if not call.customer:
            return Response({'detail': 'لا يمكن إنشاء متابعة بدون عميل مرتبط'}, status=400)

        due_date = request.data.get('due_date')
        notes    = request.data.get('notes', '')
        item_id  = request.data.get('item_id')

        if not due_date:
            return Response({'detail': 'due_date مطلوب'}, status=400)

        profile = _profile(request)
        try:
            from apps.followups.models import FollowUpTask
            kwargs = {
                'customer':    call.customer,
                'due_date':    due_date,
                'notes':       notes,
                'assigned_to': profile,
                'branch':      call.branch,
                'status':      'pending',
            }
            if item_id:
                from apps.catalog.models import Item
                kwargs['item'] = Item.objects.filter(pk=item_id).first()
            task = FollowUpTask.objects.create(**kwargs)

            # Link call to this follow-up
            call.followup_task = task
            call.save(update_fields=['followup_task'])

            return Response({'created': True, 'task_id': task.pk, 'due_date': str(task.due_date)}, status=201)
        except Exception as e:
            return Response({'detail': f'فشل إنشاء المتابعة: {e}'}, status=500)

    # ── Quality scoring ────────────────────────────────────────────────────────

    @action(detail=True, methods=['get', 'post', 'patch'], url_path='quality')
    def quality(self, request, pk=None):
        """
        GET  /api/callcenter/calls/{id}/quality/      — fetch quality score
        POST /api/callcenter/calls/{id}/quality/      — create quality score
        PATCH /api/callcenter/calls/{id}/quality/     — update quality score
        """
        call = self.get_object()
        profile = _profile(request)

        if request.method == 'GET':
            try:
                return Response(CallQualityScoreSerializer(call.quality).data)
            except CallQualityScore.DoesNotExist:
                return Response({'detail': 'لا يوجد تقييم لهذه المكالمة'}, status=404)

        # POST / PATCH — requires supervisor or quality_manager
        if not _is_supervisor_or_admin(profile):
            return Response({'detail': 'يُسمح فقط للمشرفين ومدراء الجودة'}, status=403)

        if request.method == 'POST':
            if hasattr(call, 'quality'):
                return Response({'detail': 'تم تقييم هذه المكالمة بالفعل — استخدم PATCH للتعديل'}, status=400)
            serializer = CallQualityScoreSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save(call_log=call, scored_by=profile)
            return Response(serializer.data, status=201)

        # PATCH
        try:
            score = call.quality
        except CallQualityScore.DoesNotExist:
            return Response({'detail': 'لا يوجد تقييم بعد — استخدم POST'}, status=404)
        serializer = CallQualityScoreSerializer(score, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save(scored_by=profile)
        return Response(serializer.data)

    # ── Address updates ───────────────────────────────────────────────────────

    @action(detail=True, methods=['get', 'post'], url_path='address-updates')
    def address_updates(self, request, pk=None):
        call = self.get_object()

        if request.method == 'GET':
            return Response(
                AddressUpdateSerializer(call.address_updates.all(), many=True).data
            )

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
        call = self.get_object()
        try:
            update = call.address_updates.get(pk=update_id, status='pending')
        except AddressUpdate.DoesNotExist:
            return Response(status=404)

        result = update.apply(applied_by=_profile(request))
        if result:
            return Response({'applied': True})
        return Response({'applied': False, 'detail': 'فشل تطبيق العنوان'}, status=400)

    # ── Pending callbacks ─────────────────────────────────────────────────────

    @action(detail=False, methods=['get'], url_path='pending-callbacks')
    def pending_callbacks(self, request):
        qs = CallLog.objects.filter(
            status='callback',
            callback_due__lte=timezone.now(),
        ).select_related('customer', 'handled_by__user').order_by('callback_due')

        profile = _profile(request)
        if profile and profile.role not in ('admin', 'call_center', 'supervisor'):
            qs = qs.filter(handled_by=profile)

        return Response(CallLogListSerializer(qs, many=True).data)

    @action(detail=False, methods=['get'], url_path='agents')
    def agents(self, request):
        """
        GET /api/callcenter/calls/agents/
        Returns list of call center staff for @mention autocomplete.
        """
        from apps.users.models import StaffProfile
        agents = StaffProfile.objects.filter(
            role__in=('call_center', 'supervisor', 'admin', 'quality_manager'),
            user__is_active=True,
        ).select_related('user').order_by('user__first_name')
        return Response([
            {
                'id':       a.id,
                'username': a.user.username,
                'name':     a.full_name,
                'role':     a.role,
            }
            for a in agents
        ])

    # ── Call Items ────────────────────────────────────────────────────────────

    @action(detail=True, methods=['get', 'post'], url_path='items')
    def items(self, request, pk=None):
        """
        GET  /api/callcenter/calls/{id}/items/  — list items on this call
        POST /api/callcenter/calls/{id}/items/  — add an item
        Body: { item (id, optional), manual_item_name, manual_item_code, quantity, notes }
        """
        call = self.get_object()

        if request.method == 'GET':
            return Response(
                CallItemSerializer(call.items.all(), many=True).data
            )

        serializer = CallItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(call_log=call)
        return Response(serializer.data, status=201)

    @action(detail=True, methods=['delete'], url_path=r'items/(?P<item_id>[0-9]+)')
    def remove_item(self, request, pk=None, item_id=None):
        """DELETE /api/callcenter/calls/{id}/items/{item_id}/"""
        call = self.get_object()
        try:
            ci = call.items.get(pk=item_id)
        except CallItem.DoesNotExist:
            return Response(status=404)

        if ci.converted_to != 'none':
            return Response(
                {'detail': f'هذا الصنف تم تحويله بالفعل ({ci.get_converted_to_display()}) ولا يمكن حذفه'},
                status=400,
            )

        ci.delete()
        return Response(status=204)

    @action(detail=True, methods=['post'], url_path='convert-to-reservation')
    def convert_to_reservation(self, request, pk=None):
        """
        POST /api/callcenter/calls/{id}/convert-to-reservation/
        Body: { branch_id (required), notes (opt), priority (opt: normal|urgent|chronic),
                channel (opt: pickup|home_delivery), item_ids (opt: list — limits which items) }

        Creates one Reservation per unconverted CallItem.
        Returns list of created reservation IDs.
        """
        call = self.get_object()

        if not call.customer:
            return Response({'detail': 'لا يمكن تحويل بدون عميل مرتبط'}, status=400)

        branch_id = request.data.get('branch_id') or (call.branch_id)
        if not branch_id:
            return Response({'detail': 'branch_id مطلوب'}, status=400)

        try:
            from apps.branches.models import Branch
            branch = Branch.objects.get(pk=branch_id)
        except Exception:
            return Response({'detail': 'الفرع غير موجود'}, status=404)

        notes    = request.data.get('notes', '')
        priority = request.data.get('priority', 'normal')
        channel  = request.data.get('channel', 'pickup')
        item_ids = request.data.get('item_ids')  # optional filter

        qs = call.items.filter(converted_to='none')
        if item_ids:
            qs = qs.filter(pk__in=item_ids)

        if not qs.exists():
            return Response({'detail': 'لا توجد أصناف للتحويل'}, status=400)

        profile    = _profile(request)
        customer   = call.customer
        created    = []

        try:
            from apps.reservations.models import Reservation
            for ci in qs:
                combined_notes = '\n'.join(filter(None, [ci.notes, notes])).strip()
                res = Reservation.objects.create(
                    customer            = customer,
                    item                = ci.item,
                    manual_item_name    = ci.manual_item_name if not ci.item else '',
                    branch              = branch,
                    quantity_requested  = ci.quantity,
                    contact_phone       = customer.phone or call.phone_number,
                    contact_name        = customer.name,
                    notes               = combined_notes,
                    priority            = priority,
                    channel             = channel,
                    order_source        = 'cc_call',
                    status              = 'pending',
                    created_by          = profile,
                )
                ci.converted_to          = 'reservation'
                ci.converted_reservation = res
                ci.save(update_fields=['converted_to', 'converted_reservation'])

                created.append({'call_item_id': ci.pk, 'reservation_id': res.pk})

        except Exception as e:
            return Response({'detail': f'فشل إنشاء الحجز: {e}'}, status=500)

        return Response({'created': created, 'count': len(created)}, status=201)

    @action(detail=True, methods=['post'], url_path='convert-to-transfer')
    def convert_to_transfer(self, request, pk=None):
        """
        POST /api/callcenter/calls/{id}/convert-to-transfer/
        Body: { requesting_branch_id (required), supplying_branch_id (opt), notes (opt),
                item_ids (opt: list) }

        Creates a single TransferRequest with one TransferRequestItem per CallItem.
        Only CallItems with a catalog item FK can be transferred (catalog ID required).
        Returns: { transfer_request_id, request_number, items_converted, items_skipped }
        """
        call = self.get_object()

        requesting_branch_id = request.data.get('requesting_branch_id') or (
            call.branch_id
        )
        if not requesting_branch_id:
            return Response({'detail': 'requesting_branch_id مطلوب'}, status=400)

        try:
            from apps.branches.models import Branch
            req_branch = Branch.objects.get(pk=requesting_branch_id)
        except Exception:
            return Response({'detail': 'الفرع الطالب غير موجود'}, status=404)

        supplying_branch_id = request.data.get('supplying_branch_id')
        sup_branch = None
        if supplying_branch_id:
            try:
                sup_branch = Branch.objects.get(pk=supplying_branch_id)
            except Exception:
                return Response({'detail': 'الفرع المصدر غير موجود'}, status=404)

        notes    = request.data.get('notes', '')
        item_ids = request.data.get('item_ids')

        qs = call.items.filter(converted_to='none', item__isnull=False)
        if item_ids:
            qs = qs.filter(pk__in=item_ids)

        skipped = call.items.filter(converted_to='none', item__isnull=True).count()
        if item_ids:
            skipped += call.items.filter(
                converted_to='none', item__isnull=True, pk__in=item_ids
            ).count()

        if not qs.exists():
            return Response(
                {'detail': 'لا توجد أصناف صالحة للتحويل (الأصناف اليدوية لا يمكن إضافتها لطلب نقل)'},
                status=400,
            )

        profile = _profile(request)

        try:
            from apps.transfers.models import TransferRequest, TransferRequestItem
            tr = TransferRequest.objects.create(
                requesting_branch = req_branch,
                supplying_branch  = sup_branch,
                notes             = notes,
                created_by        = profile,
                status            = 'draft',
            )

            converted = []
            for ci in qs:
                TransferRequestItem.objects.create(
                    request  = tr,
                    item     = ci.item,
                    quantity = ci.quantity,
                    notes    = ci.notes,
                )
                ci.converted_to      = 'transfer'
                ci.converted_transfer = tr
                ci.save(update_fields=['converted_to', 'converted_transfer'])
                converted.append(ci.pk)

        except Exception as e:
            return Response({'detail': f'فشل إنشاء طلب النقل: {e}'}, status=500)

        return Response({
            'transfer_request_id': tr.pk,
            'request_number':      tr.request_number,
            'items_converted':     len(converted),
            'items_skipped':       skipped,
        }, status=201)

    # ── Dashboard ─────────────────────────────────────────────────────────────

    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        """GET /api/callcenter/calls/dashboard/ — call center KPIs."""
        from datetime import date, timedelta

        today  = date.today()
        cutoff = timezone.now() - timedelta(days=30)
        qs     = CallLog.objects.filter(called_at__gte=cutoff)

        profile = _profile(request)
        if profile and profile.role not in ('admin', 'call_center', 'supervisor', 'quality_manager'):
            if profile.branch:
                qs = qs.filter(branch=profile.branch)

        answered_qs = qs.filter(status='answered')
        stats = {
            'total_calls':       qs.count(),
            'today':             qs.filter(called_at__date=today).count(),
            'answered':          answered_qs.count(),
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
            'avg_duration_seconds': answered_qs.filter(
                duration_seconds__gt=0
            ).aggregate(avg=Avg('duration_seconds'))['avg'] or 0,
            # Quality metrics (30 days)
            'avg_quality_score': answered_qs.filter(
                quality_score__isnull=False
            ).aggregate(avg=Avg('quality_score'))['avg'],
            'scored_calls_pct': round(
                answered_qs.filter(quality_score__isnull=False).count() /
                max(answered_qs.count(), 1) * 100, 1
            ),
            # Case metrics
            'open_cases':      CustomerCase.objects.filter(status__in=('open', 'working', 'waiting')).count(),
            'escalated_cases': CustomerCase.objects.filter(status='escalated').count(),
            'resolved_today':  CustomerCase.objects.filter(resolved_at__date=today).count(),
            # Sentiment breakdown (AI)
            'sentiment': {
                s: qs.filter(ai_sentiment=s).count()
                for s in ('positive', 'neutral', 'negative')
            },
        }
        return Response(stats)


# ─────────────────────────────────────────────────────────────────────────────
# CustomerCaseViewSet
# ─────────────────────────────────────────────────────────────────────────────

class CustomerCaseViewSet(viewsets.ModelViewSet):
    """
    CRUD for CustomerCase with state-machine actions.
    """
    permission_classes = [IsAuthenticated]
    filter_backends    = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields   = ['status', 'category', 'priority', 'branch', 'assigned_to']
    search_fields      = ['case_number', 'title', 'description', 'customer__name', 'customer__phone']
    ordering_fields    = ['created_at', 'updated_at', 'sla_due', 'priority']
    ordering           = ['-created_at']

    def get_queryset(self):
        qs = CustomerCase.objects.select_related(
            'customer', 'branch',
            'opened_by__user', 'assigned_to__user', 'escalated_to__user',
            'demand', 'reservation', 'delivery',
        ).prefetch_related('events__created_by__user')

        profile = _profile(self.request)
        if not profile:
            return qs.none()

        if profile.role in ('admin', 'call_center', 'supervisor', 'quality_manager'):
            return qs

        # Regular staff see cases for their branch or assigned to them
        if profile.branch:
            return qs.filter(
                Q(branch=profile.branch) | Q(assigned_to=profile)
            )
        return qs.filter(assigned_to=profile)

    def get_serializer_class(self):
        if self.action == 'list':
            return CustomerCaseListSerializer
        if self.action == 'create':
            return CustomerCaseCreateSerializer
        if self.action in ('update', 'partial_update'):
            return CustomerCaseUpdateSerializer
        return CustomerCaseDetailSerializer

    def perform_create(self, serializer):
        profile = _profile(self.request)
        case = serializer.save(opened_by=profile)
        case._log_event('حالة جديدة مفتوحة', profile)

    # ── State machine actions ─────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def assign(self, request, pk=None):
        """POST /api/callcenter/cases/{id}/assign/  body: { staff_id, note }"""
        case = self.get_object()
        profile = _profile(request)
        staff_id = request.data.get('staff_id')
        note     = request.data.get('note', '')

        if not staff_id:
            return Response({'detail': 'staff_id مطلوب'}, status=400)

        try:
            from apps.users.models import StaffProfile
            staff = StaffProfile.objects.get(pk=staff_id)
        except Exception:
            return Response({'detail': 'الموظف غير موجود'}, status=404)

        case.assign(staff=staff, note=note)
        return Response(CustomerCaseDetailSerializer(case).data)

    @action(detail=True, methods=['post'])
    def escalate(self, request, pk=None):
        """POST /api/callcenter/cases/{id}/escalate/  body: { to_staff_id, reason }"""
        case    = self.get_object()
        profile = _profile(request)

        to_id  = request.data.get('to_staff_id')
        reason = request.data.get('reason', '')
        if not to_id or not reason:
            return Response({'detail': 'to_staff_id و reason مطلوبان'}, status=400)

        try:
            from apps.users.models import StaffProfile
            to_staff = StaffProfile.objects.get(pk=to_id)
        except Exception:
            return Response({'detail': 'الموظف غير موجود'}, status=404)

        case.escalate(to_staff=to_staff, reason=reason, by_staff=profile)
        return Response(CustomerCaseDetailSerializer(case).data)

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        """POST /api/callcenter/cases/{id}/resolve/  body: { resolution, root_cause }"""
        case       = self.get_object()
        profile    = _profile(request)
        resolution = request.data.get('resolution', '').strip()
        root_cause = request.data.get('root_cause', '').strip()

        if not resolution:
            return Response({'detail': 'resolution مطلوب'}, status=400)

        case.resolve(resolution=resolution, root_cause=root_cause, by_staff=profile)
        return Response(CustomerCaseDetailSerializer(case).data)

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        """POST /api/callcenter/cases/{id}/close/"""
        case = self.get_object()
        if case.status not in ('resolved', 'closed'):
            return Response(
                {'detail': 'يجب حل الحالة قبل إغلاقها'},
                status=400,
            )
        case.close(by_staff=_profile(request))
        return Response(CustomerCaseDetailSerializer(case).data)

    @action(detail=True, methods=['post'])
    def csat(self, request, pk=None):
        """POST /api/callcenter/cases/{id}/csat/  body: { score (1-5), note }"""
        case  = self.get_object()
        score = request.data.get('score')
        note  = request.data.get('note', '')

        if not score:
            return Response({'detail': 'score مطلوب (1-5)'}, status=400)
        try:
            score = int(score)
            if not 1 <= score <= 5:
                raise ValueError
        except (ValueError, TypeError):
            return Response({'detail': 'score يجب أن يكون بين 1 و 5'}, status=400)

        case.set_csat(score=score, note=note)
        return Response({'csat_score': case.csat_score, 'csat_note': case.csat_note})

    @action(detail=True, methods=['post'], url_path='add-note', parser_classes=None)
    def add_note(self, request, pk=None):
        """
        POST /api/callcenter/cases/{id}/add-note/
        Accepts: JSON { message } OR multipart { message, attachment, attachment_type }
        Parses @username mentions and sends notifications to mentioned agents.
        """
        case    = self.get_object()
        profile = _profile(request)
        message = (request.data.get('message') or '').strip()

        if not message and not request.FILES.get('attachment'):
            return Response({'detail': 'message أو مرفق مطلوب'}, status=400)

        # Save the event
        event = CaseEvent.objects.create(
            case=case,
            event_type='note',
            message=message,
            created_by=profile,
            attachment=request.FILES.get('attachment') or None,
            attachment_type=request.data.get('attachment_type', ''),
        )

        # Parse @username mentions → send notifications
        import re as _re
        handles = set(_re.findall(r'@(\w+)', message))
        if handles:
            try:
                from apps.users.models import StaffProfile
                from apps.notifications.models import Notification
                for handle in handles:
                    try:
                        mentioned = StaffProfile.objects.select_related('user').get(
                            user__username__iexact=handle
                        )
                        if mentioned != profile:
                            Notification.send_to_user(
                                staff             = mentioned,
                                notification_type = 'chatter_mention',
                                title             = f'ذكرك {profile.full_name} في حالة {case.case_number}',
                                body              = message[:200],
                                dedup_key         = f'case_mention_{event.pk}_{mentioned.pk}',
                            )
                    except Exception:
                        pass
            except Exception:
                pass

        return Response(CaseEventSerializer(event, context={'request': request}).data, status=201)

    @action(detail=True, methods=['get'], url_path='events')
    def events(self, request, pk=None):
        """GET /api/callcenter/cases/{id}/events/"""
        case = self.get_object()
        return Response(
            CaseEventSerializer(case.events.select_related('created_by__user'), many=True).data
        )

    @action(detail=False, methods=['get'], url_path='my-queue')
    def my_queue(self, request):
        """GET /api/callcenter/cases/my-queue/ — cases assigned to current user."""
        profile = _profile(request)
        if not profile:
            return Response([], status=200)

        qs = CustomerCase.objects.filter(
            assigned_to=profile,
            status__in=('open', 'working', 'waiting', 'escalated'),
        ).select_related('customer', 'branch').order_by('-created_at')

        return Response(CustomerCaseListSerializer(qs, many=True).data)

    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        """GET /api/callcenter/cases/dashboard/ — case KPIs."""
        from datetime import date, timedelta
        today   = date.today()
        qs      = CustomerCase.objects.all()

        profile = _profile(request)
        if profile and profile.role not in ('admin', 'call_center', 'supervisor', 'quality_manager'):
            if profile.branch:
                qs = qs.filter(branch=profile.branch)

        total = qs.count()
        stats = {
            'total':           total,
            'open':            qs.filter(status='open').count(),
            'working':         qs.filter(status='working').count(),
            'waiting':         qs.filter(status='waiting').count(),
            'escalated':       qs.filter(status='escalated').count(),
            'resolved':        qs.filter(status='resolved').count(),
            'closed':          qs.filter(status='closed').count(),
            'resolved_today':  qs.filter(resolved_at__date=today).count(),
            'opened_today':    qs.filter(created_at__date=today).count(),
            'sla_breached':    qs.filter(
                sla_due__lt=timezone.now()
            ).exclude(status__in=('resolved', 'closed')).count(),
            'avg_resolution_hours': qs.filter(
                resolved_at__isnull=False
            ).aggregate(
                avg=Avg(
                    (timezone.now() - timezone.now()).total_seconds()  # placeholder
                )
            )['avg'],  # computed below
            'by_category': list(
                qs.values('category').annotate(count=Count('id')).order_by('-count')
            ),
            'avg_csat': qs.filter(csat_score__isnull=False).aggregate(
                avg=Avg('csat_score')
            )['avg'],
        }

        # Fix avg_resolution_hours: compute via Python (Django ORM doesn't support
        # DateTimeField subtraction → DurationField on all DB backends easily)
        try:
            from django.db.models import ExpressionWrapper, DurationField, F
            resolved_qs = qs.filter(resolved_at__isnull=False).annotate(
                duration=ExpressionWrapper(
                    F('resolved_at') - F('created_at'),
                    output_field=DurationField(),
                )
            )
            total_secs = sum(
                r.duration.total_seconds() for r in resolved_qs if r.duration
            )
            count = resolved_qs.count()
            stats['avg_resolution_hours'] = round(total_secs / max(count, 1) / 3600, 1)
        except Exception:
            stats['avg_resolution_hours'] = None

        return Response(stats)


# ─────────────────────────────────────────────────────────────────────────────
# AddressUpdateViewSet
# ─────────────────────────────────────────────────────────────────────────────

class AddressUpdateViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only global list of address updates — admin / call_center only."""
    permission_classes = [IsAuthenticated]
    serializer_class   = AddressUpdateSerializer
    filter_backends    = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields   = ['status', 'customer']
    ordering           = ['-collected_at']

    def get_queryset(self):
        profile = _profile(self.request)
        if not profile or profile.role not in ('admin', 'call_center', 'supervisor'):
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

        result = update.apply(applied_by=_profile(request))
        if result:
            return Response({'applied': True})
        return Response({'applied': False}, status=400)
