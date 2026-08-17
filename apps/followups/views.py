"""
apps/followups/views.py

Chronic Refill & Follow-up module API.

FollowUpTaskViewSet exposes rich, fully-filterable follow-up tasks that connect:
  - Catalog (full product: indication, dosage form, pack size, dosing)
  - Customers (channel, segment, churn, LTV)
  - Recommendations (FBT complementary cross-sell)
  - WhatsApp (pre-rendered message + wa.me link)
  - Call Center (log_call creates a CallLog linked to the customer + item)

Advanced filters (query params on the list endpoint):
  status, task_type, sales_channel (csv), favoured_only, branch, assigned_to,
  indication (effect text), effect_code, medicine_type, item_search,
  customer_search, segment, churn_segment, due_after, due_before, overdue_only,
  active_ingredient, ordering
"""
from collections import defaultdict
from datetime import date

from django.db.models import Q, Sum, Count
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import ChronicMedicationProfile, FollowUpTask
from .serializers import (
    ChronicMedicationProfileSerializer, ChronicMedicationProfileWriteSerializer,
    FollowUpTaskListSerializer, FollowUpTaskDetailSerializer,
    FollowUpTaskCreateSerializer, FollowUpActionSerializer,
)
from . import services


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


class ChronicMedicationProfileViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends    = [filters.SearchFilter]
    search_fields      = ['item__name', 'item__softech_id']

    def get_queryset(self):
        return ChronicMedicationProfile.objects.select_related('item', 'created_by__user')

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return ChronicMedicationProfileWriteSerializer
        return ChronicMedicationProfileSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=_profile(self.request))

    @action(detail=False, methods=['post'], url_path='infer-from-erp')
    def infer_from_erp(self, request):
        min_purchases = int(request.data.get('min_purchase_count', 3))
        min_months    = int(request.data.get('min_months', 2))
        count = services.infer_chronic_profiles_from_erp(
            min_purchase_count=min_purchases, min_months=min_months,
        )
        return Response({'profiles_created_or_updated': count})


class FollowUpTaskViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    ordering           = ['due_date', '-created_at']

    # ── Queryset with full select/prefetch + advanced filtering ───────────────
    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        profile = _profile(self.request)
        # Roles that may always see customer contact data
        privileged_roles = ('admin', 'call_center', 'supervisor')
        if profile:
            ctx['can_see_phone'] = (
                profile.role in privileged_roles
                or getattr(profile, 'can_see_customer_phone', True)
            )
        else:
            ctx['can_see_phone'] = False
        return ctx

    def _detail(self, task):
        """
        Build a detail-serialised task response using the FULL serializer context
        (so can_see_phone is honoured). Action endpoints MUST use this instead of
        constructing the serializer with a bare {'request': request} context, which
        would default can_see_phone to True and leak phone numbers.
        """
        return FollowUpTaskDetailSerializer(task, context=self.get_serializer_context()).data

    def get_queryset(self):
        qs = FollowUpTask.objects.select_related(
            'customer',
            'local_customer',
            'item', 'branch',
            'assigned_to__user', 'created_by__user', 'pinned_by__user',
            'chronic_profile',
        ).prefetch_related('assignments__staff__user')
        profile = _profile(self.request)
        if not profile:
            return qs.none()

        # Branch staff see only their branch tasks
        if profile.role not in ('admin', 'call_center', 'purchasing'):
            if profile.branch:
                qs = qs.filter(branch=profile.branch)
            else:
                return qs.none()

        return self._apply_filters(qs, self.request.query_params)

    def _apply_filters(self, qs, p):
        # ── Status / type ────────────────────────────────────────────────────
        if p.get('status'):
            qs = qs.filter(status=p['status'])
        if p.get('task_type'):
            qs = qs.filter(task_type=p['task_type'])

        # ── Branch / assignee ────────────────────────────────────────────────
        if p.get('branch'):
            qs = qs.filter(branch_id=p['branch'])
        if p.get('assigned_to'):
            qs = qs.filter(assigned_to_id=p['assigned_to'])

        # ── Pin / personal tracking filters ─────────────────────────────────
        # assigned_to_me=1  → tasks where I am in FollowUpTaskAssignment
        if p.get('assigned_to_me') in ('1', 'true', 'True'):
            profile = _profile(self.request)
            if profile:
                qs = qs.filter(assignments__staff=profile).distinct()
        # pinned_only=1     → tasks this user has pinned
        if p.get('pinned_only') in ('1', 'true', 'True'):
            profile = _profile(self.request)
            if profile:
                qs = qs.filter(is_pinned=True, pinned_by=profile)
        # my_tasks=1  → in my FollowUpTaskAssignment list OR pinned by me
        if p.get('my_tasks') in ('1', 'true', 'True'):
            profile = _profile(self.request)
            if profile:
                qs = qs.filter(
                    Q(assignments__staff=profile) |
                    Q(pinned_by=profile, is_pinned=True)
                ).distinct()
        # untracked=1       → auto-generated tasks nobody has touched yet
        if p.get('untracked') in ('1', 'true', 'True'):
            qs = qs.filter(is_pinned=False, assigned_to__isnull=True)

        # ── Sales channel targeting (csv) ────────────────────────────────────
        channels = p.get('sales_channel')
        if channels:
            codes = [c.strip() for c in channels.split(',') if c.strip()]
            if codes:
                qs = qs.filter(sales_channel__in=codes)

        # Favoured channels only — use the model's constant so it stays in sync
        if p.get('favoured_only') in ('1', 'true', 'True'):
            from .models import FollowUpTask as FUT
            qs = qs.filter(sales_channel__in=list(FUT.FAVOURED_CHANNEL_CODES))

        # ── Item / catalog filters ───────────────────────────────────────────
        if p.get('item'):
            qs = qs.filter(item_id=p['item'])
        item_search = (p.get('item_search') or '').strip()
        if item_search:
            qs = qs.filter(
                Q(item__name__icontains=item_search) |
                Q(item__name_scientific__icontains=item_search) |
                Q(item__softech_id__icontains=item_search) |
                Q(item__active_ingredients__icontains=item_search)
            )
        if p.get('medicine_type'):
            qs = qs.filter(item__medicine_type=p['medicine_type'])
        if p.get('effect_code'):
            qs = qs.filter(item__effect_code=p['effect_code'])
        indication = (p.get('indication') or '').strip()
        if indication:
            qs = qs.filter(
                Q(item__effect_name_ar__icontains=indication) |
                Q(item__effect_name2_ar__icontains=indication) |
                Q(item__effect_name__icontains=indication)
            )
        active_ing = (p.get('active_ingredient') or '').strip()
        if active_ing:
            qs = qs.filter(item__active_ingredients__icontains=active_ing)

        # ── Customer filters ─────────────────────────────────────────────────
        cust_search = (p.get('customer_search') or '').strip()
        if cust_search:
            qs = qs.filter(
                # Full Customer record (linked)
                Q(customer__name__icontains=cust_search) |
                Q(customer__phone__icontains=cust_search) |
                Q(customer__whatsapp_phone__icontains=cust_search) |
                Q(customer__softech_pic__icontains=cust_search) |
                # LocalCustomer (PIC / delivery — most tasks link here, not Customer)
                Q(local_customer__name__icontains=cust_search) |
                Q(local_customer__phone__icontains=cust_search) |
                Q(local_customer__phone_alt__icontains=cust_search) |
                Q(local_customer__phcode__icontains=cust_search) |
                # phcode stored directly on the task for fast lookup
                Q(phcode__icontains=cust_search)
            )
        if p.get('segment'):
            qs = qs.filter(customer__segment=p['segment'])
        if p.get('churn_segment'):
            qs = qs.filter(customer__churn_segment=p['churn_segment'])

        # ── Date / overdue filters ───────────────────────────────────────────
        if p.get('due_after'):
            qs = qs.filter(due_date__gte=p['due_after'])
        if p.get('due_before'):
            qs = qs.filter(due_date__lte=p['due_before'])
        if p.get('overdue_only') in ('1', 'true', 'True'):
            qs = qs.filter(status__in=('pending', 'called'), due_date__lt=date.today())

        # ── Invalid phone filter ─────────────────────────────────────────────
        if p.get('hide_invalid') in ('1', 'true', 'True'):
            qs = qs.filter(phone_invalid=False)
        if p.get('invalid_only') in ('1', 'true', 'True'):
            qs = qs.filter(phone_invalid=True)

        # ── Has demand record filter ──────────────────────────────────────────
        if p.get('has_demand') in ('1', 'true', 'True'):
            qs = qs.filter(demand_record__isnull=False)

        # ── Ordering ─────────────────────────────────────────────────────────
        ordering = p.get('ordering')
        allowed = {
            'due_date', '-due_date', 'created_at', '-created_at',
            'sales_channel', '-sales_channel',
            'priority_score', '-priority_score',
        }
        if ordering in allowed:
            qs = qs.order_by(ordering)
        elif p.get('by_score') in ('1', 'true', 'True'):
            qs = qs.order_by('-priority_score', 'due_date')
        elif p.get('by_priority') in ('1', 'true', 'True'):
            # Favoured channels first, then soonest due
            from django.db.models import Case, When, IntegerField, Value
            qs = qs.annotate(
                _chan_rank=Case(
                    When(sales_channel='91', then=Value(1)),
                    When(sales_channel='90', then=Value(1)),
                    When(sales_channel='13', then=Value(2)),
                    When(sales_channel='15', then=Value(4)),
                    default=Value(3), output_field=IntegerField(),
                )
            ).order_by('_chan_rank', 'due_date')
        else:
            qs = qs.order_by('due_date', '-created_at')

        return qs

    def get_serializer_class(self):
        if self.action == 'list':
            return FollowUpTaskListSerializer
        if self.action == 'create':
            return FollowUpTaskCreateSerializer
        return FollowUpTaskDetailSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=_profile(self.request))

    # ── Pin / Assign actions ──────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def pin(self, request, pk=None):
        """
        POST /api/followups/tasks/{id}/pin/
        Staff manually pins a task to track it. Sends a quiet confirmation
        notification to the pinner only. Does NOT broadcast to all admins.
        """
        task  = self.get_object()
        staff = _profile(request)
        if not staff:
            return Response({'detail': 'غير مصرّح'}, status=403)
        services.pin_task(task, staff)
        return Response(self._detail(task))

    @action(detail=True, methods=['post'])
    def unpin(self, request, pk=None):
        """POST /api/followups/tasks/{id}/unpin/ — remove pin."""
        task  = self.get_object()
        staff = _profile(request)
        if not staff:
            return Response({'detail': 'غير مصرّح'}, status=403)
        services.unpin_task(task, staff)
        return Response(self._detail(task))

    @action(detail=True, methods=['post'])
    def assign(self, request, pk=None):
        """
        POST /api/followups/tasks/{id}/assign/

        Assigns a task to one or more staff members. Criteria are combined (union):

          assignee_ids   [int]   — specific StaffProfile PKs
          role           str     — all active staff with this role
          branch_id      int     — all active staff at this branch
          use_task_branch bool   — use the task's own branch (overrides branch_id)
          replace        bool    — clear existing assignments first (default true)

        Examples:
          { "assignee_ids": [3, 7] }                    → two specific users
          { "role": "call_center" }                      → all call-center staff
          { "role": "pharmacist", "branch_id": 5 }      → pharmacists at branch 5
          { "branch_id": 5 }                             → everyone at branch 5
          { "use_task_branch": true }                    → everyone at the task's branch
          { "assignee_ids": [3], "replace": false }      → add user 3 without removing others
        """
        task  = self.get_object()
        actor = _profile(request)
        data  = request.data

        assignee_ids    = data.get('assignee_ids') or []
        role            = data.get('role') or ''
        branch_id       = data.get('branch_id')
        use_task_branch = bool(data.get('use_task_branch', False))
        replace         = bool(data.get('replace', True))

        if not assignee_ids and not role and not branch_id and not use_task_branch:
            return Response(
                {'detail': 'يجب تحديد معيار واحد على الأقل: assignee_ids أو role أو branch_id أو use_task_branch'},
                status=400,
            )

        resolved = services.assign_task(
            task,
            actor           = actor,
            assignee_ids    = assignee_ids,
            role            = role,
            branch_id       = branch_id,
            use_task_branch = use_task_branch,
            replace         = replace,
        )
        if not resolved:
            return Response({'detail': 'لم يُعثر على موظفين نشطين بهذه المعايير'}, status=400)

        # Refresh from DB so serializer sees updated FK + assignments
        task.refresh_from_db()
        return Response({
            'assigned_count': len(resolved),
            'assigned_staff': [
                {'id': s.pk, 'name': s.full_name, 'role': s.role}
                for s in resolved
            ],
            'task': self._detail(task),
        })

    @action(detail=True, methods=['post'], url_path='clear-assignments')
    def clear_assignments(self, request, pk=None):
        """POST /api/followups/tasks/{id}/clear-assignments/ — remove all assignees."""
        from .models import FollowUpTaskAssignment
        task  = self.get_object()
        count = FollowUpTaskAssignment.objects.filter(task=task).delete()[0]
        task.assigned_to = None
        task.save(update_fields=['assigned_to', 'updated_at'])
        return Response({'removed': count})

    # ── State machine actions ─────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def call(self, request, pk=None):
        task = self.get_object()
        s = FollowUpActionSerializer(data=request.data); s.is_valid(raise_exception=True)
        services.mark_task_called(task, note=s.validated_data.get('note', ''), staff=_profile(request))
        return Response(self._detail(task))

    @action(detail=True, methods=['post'])
    def done(self, request, pk=None):
        task = self.get_object()
        s = FollowUpActionSerializer(data=request.data); s.is_valid(raise_exception=True)
        services.mark_task_done(task, note=s.validated_data.get('note', ''), staff=_profile(request))
        return Response(self._detail(task))

    @action(detail=True, methods=['post'])
    def missed(self, request, pk=None):
        task = self.get_object()
        s = FollowUpActionSerializer(data=request.data); s.is_valid(raise_exception=True)
        services.mark_task_missed(task, note=s.validated_data.get('note', ''), staff=_profile(request))
        return Response(self._detail(task))

    # ── WhatsApp: record outreach + return wa.me link with prefilled message ──
    @action(detail=True, methods=['post'])
    def whatsapp(self, request, pk=None):
        """
        POST /api/followups/tasks/{id}/whatsapp/
        Marks the task as 'called' (outreach attempted) and returns the wa.me
        URL with the pre-rendered Arabic refill message.
        """
        task = self.get_object()
        services.mark_task_called(
            task, note='تم التواصل عبر واتساب', staff=_profile(request),
        )
        return Response({
            'whatsapp_url':         task.whatsapp_url_with_message,
            'whatsapp_url_plain':   task.whatsapp_url,
            'message':              task.render_whatsapp_message(),
            'task': self._detail(task),
        })

    # ── Call Center connection: create a CallLog from the follow-up ───────────
    @action(detail=True, methods=['post'], url_path='log-call')
    def log_call(self, request, pk=None):
        """
        POST /api/followups/tasks/{id}/log-call/
        Creates a CallLog (purpose=refill) linked to the customer + item, then
        marks the follow-up as 'called'. Returns the new call_log id.
        Body: { status: 'answered'|'no_answer'|..., notes: '...', mark_done: bool }
        """
        task = self.get_object()
        call_id = None
        try:
            from apps.callcenter.models import CallLog
            phone = task.best_phone or task.customer_phone
            call = CallLog.objects.create(
                phone_number = phone,
                customer_id  = task.customer_id,
                direction    = 'outbound',
                status       = request.data.get('status', 'answered'),
                purpose      = 'refill',
                notes        = request.data.get('notes', '') or
                               f'متابعة إعادة صرف: {task.item.name if task.item_id else ""}',
                handled_by   = _profile(request),
            )
            # Link the related item if the CallLog model supports it
            if hasattr(call, 'related_item_id'):
                call.related_item_id = task.item_id
                call.save(update_fields=['related_item'])
            call_id = call.id
        except Exception as exc:
            return Response({'detail': f'تعذّر إنشاء سجل المكالمة: {exc}'}, status=500)

        # Update task state
        if request.data.get('mark_done'):
            services.mark_task_done(task, note=request.data.get('notes', ''), staff=_profile(request))
        else:
            services.mark_task_called(task, note=request.data.get('notes', ''), staff=_profile(request))

        return Response({
            'call_log_id': call_id,
            'task': self._detail(task),
        })

    # ── Dashboard stats ───────────────────────────────────────────────────────
    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        profile   = _profile(request)
        branch_id = request.query_params.get('branch')
        days      = int(request.query_params.get('days', 30))
        branch = None
        if branch_id:
            from apps.branches.models import Branch
            branch = Branch.objects.filter(pk=branch_id).first()
        elif profile and profile.branch and profile.role not in ('admin', 'call_center'):
            branch = profile.branch
        return Response(services.get_dashboard_stats(branch=branch, days=days))

    # ── Filter metadata for the advanced-filter UI dropdowns ──────────────────
    @action(detail=False, methods=['get'], url_path='filter-meta')
    def filter_meta(self, request):
        """
        Returns dropdown options for the advanced filter panel:
          channels, indications (effect list), medicine_types, segments, statuses.
        """
        from apps.catalog.models import Item

        # Distinct indications present among items that have follow-up tasks
        task_item_ids = (
            FollowUpTask.objects.exclude(item__isnull=True)
            .values_list('item_id', flat=True).distinct()
        )
        indications = list(
            Item.objects.filter(id__in=task_item_ids)
            .exclude(effect_name_ar='')
            .values_list('effect_code', 'effect_name_ar')
            .distinct().order_by('effect_name_ar')[:200]
        )
        medicine_types = list(
            Item.objects.filter(id__in=task_item_ids)
            .exclude(medicine_type_name_ar='')
            .values_list('medicine_type', 'medicine_type_name_ar')
            .distinct().order_by('medicine_type_name_ar')[:100]
        )

        # ── Dynamic channels: from actual task data, labelled from model map ───
        # Do NOT hard-code — codes differ per branch/dataset.
        # Guaranteed codes from the model map + whatever actually appears in tasks.
        actual_codes = list(
            FollowUpTask.objects
            .exclude(sales_channel='')
            .values_list('sales_channel', flat=True)
            .distinct()
            .order_by('sales_channel')[:50]
        )
        # Merge with all known codes from _CHANNEL_MAP so all known channels appear
        all_known_codes = set(FollowUpTask._CHANNEL_MAP.keys()) | set(actual_codes)
        channels_list = []
        for code in sorted(all_known_codes, key=lambda c: FollowUpTask._CHANNEL_MAP.get(c, ('', False, 9))[2]):
            entry = FollowUpTask._CHANNEL_MAP.get(code)
            label    = entry[0] if entry else f'قناة {code}'
            favoured = entry[1] if entry else False
            # Only include the code if it actually exists in tasks OR is a key known channel
            if code in actual_codes or code in ('91', '90'):
                channels_list.append({'code': code, 'label': label, 'favoured': favoured})

        return Response({
            'channels': channels_list,
            'indications': [
                {'code': c, 'label': l} for c, l in indications if l
            ],
            'medicine_types': [
                {'code': c, 'label': l} for c, l in medicine_types if l
            ],
            'segments': [
                {'code': 'vip', 'label': 'VIP'}, {'code': 'loyal', 'label': 'وفي'},
                {'code': 'regular', 'label': 'عادي'}, {'code': 'at_risk', 'label': 'في خطر'},
                {'code': 'dormant', 'label': 'خامل'}, {'code': 'churned', 'label': 'مفقود'},
            ],
            'churn_segments': [
                {'code': 'low', 'label': 'مستقر'}, {'code': 'medium', 'label': 'مراقبة'},
                {'code': 'high', 'label': 'خطر مرتفع'}, {'code': 'critical', 'label': 'حرج'},
            ],
            'statuses': [
                {'code': 'pending', 'label': 'معلق'}, {'code': 'called', 'label': 'تم الاتصال'},
                {'code': 'done', 'label': 'مكتمل'}, {'code': 'missed', 'label': 'فائت'},
                {'code': 'auto_closed', 'label': 'أُغلق تلقائياً'},
            ],
        })

    # ── Generation pipeline ───────────────────────────────────────────────────
    @action(detail=False, methods=['post'], url_path='generate')
    def generate(self, request):
        dry_run      = bool(request.data.get('dry_run', False))
        branch_id    = request.data.get('branch_id')
        overdue_days = int(request.data.get('overdue_days', 3))
        branch       = None
        if branch_id:
            from apps.branches.models import Branch
            branch = Branch.objects.filter(pk=branch_id).first()

        created = services.generate_followup_tasks_bulk(branch=branch, dry_run=dry_run)

        auto_closed = 0
        if not dry_run:
            try:
                auto_closed = services.auto_close_followup_tasks_from_erp(since_minutes=60 * 24)
            except Exception:
                pass

        escalated = 0
        try:
            escalated = services.escalate_overdue_tasks(overdue_days=overdue_days, dry_run=dry_run)['escalated']
        except Exception:
            pass

        # Backfill channels for any tasks missing them
        if not dry_run:
            try:
                services.backfill_sales_channels()
            except Exception:
                pass

        return Response({
            'tasks_created': created, 'tasks_auto_closed': auto_closed,
            'tasks_escalated': escalated, 'dry_run': dry_run,
        })

    @action(detail=False, methods=['post'], url_path='auto-close')
    def auto_close(self, request):
        minutes = int(request.data.get('minutes', 12))
        count   = services.auto_close_followup_tasks_from_erp(since_minutes=minutes)
        return Response({'tasks_auto_closed': count})

    @action(detail=False, methods=['post'], url_path='escalate')
    def escalate(self, request):
        overdue_days = int(request.data.get('overdue_days', 3))
        dry_run      = bool(request.data.get('dry_run', False))
        result = services.escalate_overdue_tasks(overdue_days=overdue_days, dry_run=dry_run)
        return Response({**result, 'dry_run': dry_run})

    @action(detail=False, methods=['post'], url_path='backfill-channels')
    def backfill_channels(self, request):
        count = services.backfill_sales_channels()
        return Response({'tasks_updated': count})

    # ── Feature 6: Grouped by customer ───────────────────────────────────────
    @action(detail=False, methods=['get'])
    def grouped(self, request):
        """
        GET /api/followups/tasks/grouped/
        Returns tasks grouped by customer (phcode).
        Supports the same filter params as the list endpoint.
        Each group: { phcode, customer, tasks[], stats: {total, pending, overdue, at_risk_value} }
        Groups sorted by sum of priority_score DESC (highest-value customers first).
        Optional: ?limit_per_group=N (default 20 tasks shown per customer)
        """
        qs = self.get_queryset()
        can_see_phone = self.get_serializer_context().get('can_see_phone', True)

        # Serialise the filtered flat list first
        serialized_tasks = FollowUpTaskListSerializer(
            qs.select_related(
                'customer', 'local_customer', 'item', 'branch',
                'assigned_to__user', 'pinned_by__user', 'chronic_profile',
            ).prefetch_related('assignments__staff__user')[:2000],
            many=True,
            context=self.get_serializer_context(),
        ).data

        # Group in Python — avoids complex DB GROUP BY with JSONField
        groups = defaultdict(lambda: {
            'phcode': '',
            'customer': None,
            'tasks': [],
            'priority_sum': 0.0,
        })

        for task in serialized_tasks:
            c      = task.get('customer') or {}
            phcode = c.get('phcode') or task.get('phcode', '') or str(task['id'])
            g = groups[phcode]
            g['phcode']   = phcode
            g['customer'] = c
            g['tasks'].append(task)
            g['priority_sum'] += float(task.get('priority_score') or 0)

        # Compute per-group stats and sort
        result = []
        for phcode, g in groups.items():
            tasks       = g['tasks']
            overdue     = sum(1 for t in tasks if (t.get('refill') or {}).get('is_overdue'))
            pending     = sum(1 for t in tasks if t.get('status') in ('pending', 'called'))
            at_risk     = sum(
                float((t.get('product') or {}).get('pack_price') or 0) *
                float((t.get('refill')  or {}).get('item_qty')   or 1)
                for t in tasks
                if t.get('status') in ('pending', 'called')
            )
            result.append({
                'phcode':         phcode,
                'customer':       g['customer'],
                'tasks':          tasks,
                'priority_sum':   round(g['priority_sum'], 4),
                'stats': {
                    'total':         len(tasks),
                    'pending':       pending,
                    'overdue':       overdue,
                    'at_risk_value': round(at_risk, 2),
                },
            })

        result.sort(key=lambda x: -x['priority_sum'])
        return Response(result)

    # ── Feature 6: Multi-item WhatsApp message ────────────────────────────────
    @action(detail=False, methods=['post'], url_path='multi-whatsapp')
    def multi_whatsapp(self, request):
        """
        POST /api/followups/tasks/multi-whatsapp/
        Build a combined WhatsApp message for a customer covering multiple tasks.
        Body: { task_ids: [int], include_upsell?: bool }
        Returns { message, whatsapp_url, character_count }
        """
        task_ids      = request.data.get('task_ids', [])
        include_upsell = bool(request.data.get('include_upsell', False))

        if not task_ids:
            return Response({'detail': 'task_ids مطلوبة'}, status=400)

        # Block users without phone permission from harvesting numbers via wa.me
        if not self.get_serializer_context().get('can_see_phone', False):
            return Response({'detail': 'ليس لديك صلاحية الوصول لبيانات الاتصال'}, status=403)

        # Scope to tasks the user is allowed to see (branch restrictions, etc.)
        tasks = list(
            self.get_queryset()
            .filter(id__in=task_ids)
            .select_related('customer', 'local_customer', 'item', 'chronic_profile')
        )
        if not tasks:
            return Response({'detail': 'لا توجد مهام'}, status=404)

        msg = services.build_multi_item_whatsapp_message(
            tasks, include_upsell=include_upsell,
        )
        phone     = tasks[0].best_phone or tasks[0].customer_phone
        wa_url    = None
        if phone:
            import urllib.parse
            clean  = tasks[0]._normalise_phone(phone)
            wa_url = f'https://wa.me/{clean}?text={urllib.parse.quote(msg)}'

        # Mark all included tasks as called (outreach attempted)
        for task in tasks:
            if task.status in ('pending', 'called'):
                services.mark_task_called(
                    task, note='تم التواصل عبر واتساب (رسالة متعددة الأصناف)',
                    staff=_profile(request),
                )

        return Response({
            'message':         msg,
            'whatsapp_url':    wa_url,
            'character_count': len(msg),
            'tasks_count':     len(tasks),
        })

    # ── Feature 9: Outcome preset (per task) ──────────────────────────────────
    @action(detail=True, methods=['post'], url_path='outcome')
    def outcome(self, request, pk=None):
        """
        POST /api/followups/tasks/{id}/outcome/
        Apply a one-tap outcome preset.
        Body: { preset_id: str, note?: str }
        """
        task      = self.get_object()
        actor     = _profile(request)
        preset_id = request.data.get('preset_id', '')
        note      = request.data.get('note', '')
        if not preset_id:
            return Response({'detail': 'preset_id مطلوب'}, status=400)
        try:
            result = services.apply_outcome_preset(task, preset_id, extra_note=note, actor=actor)
        except ValueError as e:
            return Response({'detail': str(e)}, status=400)
        task.refresh_from_db()
        return Response({
            'side_result': result['side_result'],
            'task': self._detail(task),
        })

    # ── Feature 9: List outcome presets ───────────────────────────────────────
    @action(detail=False, methods=['get'], url_path='outcome-presets')
    def outcome_presets(self, request):
        """GET /api/followups/tasks/outcome-presets/ — return all preset options."""
        from .models import OUTCOME_PRESETS
        return Response([
            {'id': p[0], 'label': p[1], 'result_status': p[2],
             'side_action': p[3] or ''}
            for p in OUTCOME_PRESETS
        ])

    # ── Feature 12: Phone flag / unflag ───────────────────────────────────────
    @action(detail=True, methods=['post'], url_path='flag-phone')
    def flag_phone(self, request, pk=None):
        """POST /api/followups/tasks/{id}/flag-phone/ — mark customer phone as invalid."""
        task = self.get_object()
        services.flag_invalid_phone(task, actor=_profile(request))
        return Response({'phone_invalid': True})

    @action(detail=True, methods=['post'], url_path='unflag-phone')
    def unflag_phone(self, request, pk=None):
        """POST /api/followups/tasks/{id}/unflag-phone/ — re-enable invalid-phone task."""
        task = self.get_object()
        services.unflag_invalid_phone(task, actor=_profile(request))
        return Response({'phone_invalid': False})

    # ── Feature 23: Create demand record ──────────────────────────────────────
    @action(detail=True, methods=['post'], url_path='create-demand')
    def create_demand(self, request, pk=None):
        """
        POST /api/followups/tasks/{id}/create-demand/
        Body: { demand_type?: 'out_of_stock'|'new_item', source?: str }
        Creates a DemandRecord from this task's customer + item + branch.
        """
        task        = self.get_object()
        actor       = _profile(request)
        demand_type = request.data.get('demand_type', 'out_of_stock')
        source      = request.data.get('source', 'call_center')
        try:
            demand = services.create_demand_from_task(
                task, actor=actor, demand_type=demand_type, source=source,
            )
        except ValueError as e:
            return Response({'detail': str(e)}, status=400)
        task.refresh_from_db()
        return Response({
            'demand_number': demand.demand_number,
            'demand_id':     demand.id,
            'task': self._detail(task),
        })

    # ── Feature 24: Assign voucher on conversion ───────────────────────────────
    @action(detail=True, methods=['post'], url_path='assign-voucher')
    def assign_voucher(self, request, pk=None):
        """
        POST /api/followups/tasks/{id}/assign-voucher/
        Body: { voucher_code: str }
        Assigns a voucher to the task's customer phone to reward loyalty.
        """
        task         = self.get_object()
        actor        = _profile(request)
        voucher_code = request.data.get('voucher_code', '').strip()
        if not voucher_code:
            return Response({'detail': 'voucher_code مطلوب'}, status=400)
        try:
            assignment = services.assign_voucher_on_conversion(
                task, voucher_code=voucher_code, actor=actor,
            )
        except ValueError as e:
            return Response({'detail': str(e)}, status=400)
        return Response({
            'voucher_code':    voucher_code,
            'customer_phone':  assignment.customer_phone,
            'assigned':        True,
        })

    # ── Feature 4: Upsell WhatsApp message ────────────────────────────────────
    @action(detail=True, methods=['get'], url_path='upsell-message')
    def upsell_message(self, request, pk=None):
        """GET /api/followups/tasks/{id}/upsell-message/ — refill + FBT upsell combined."""
        task = self.get_object()
        msg  = services.build_upsell_whatsapp_message(task)
        import urllib.parse
        phone = task.best_phone or task.customer_phone
        wa_url = (
            f'https://wa.me/{task._normalise_phone(phone)}?text={urllib.parse.quote(msg)}'
            if phone else None
        )
        return Response({'message': msg, 'whatsapp_url': wa_url})

    # ── Feature 10: Bulk actions ───────────────────────────────────────────────
    @action(detail=False, methods=['post'], url_path='bulk-action')
    def bulk_action(self, request):
        """
        POST /api/followups/tasks/bulk-action/
        Apply an action to multiple tasks at once.

        Body:
          task_ids   [int]   — required: list of task PKs
          action     str     — required: mark_called|mark_done|mark_missed|
                                         apply_preset|assign|pin|unpin|cancel
          note       str     — optional result note
          preset_id  str     — required for apply_preset
          assign     dict    — required for assign (same shape as /assign/)
        """
        actor    = _profile(request)
        task_ids = request.data.get('task_ids', [])
        action   = request.data.get('action', '')
        note     = request.data.get('note', '')
        preset   = request.data.get('preset_id', '')
        assign_kw = request.data.get('assign', {})

        if not task_ids:
            return Response({'detail': 'task_ids مطلوبة'}, status=400)
        if not action:
            return Response({'detail': 'action مطلوب'}, status=400)

        # Scope to tasks the user may access (branch restrictions etc.)
        allowed_ids = set(
            self.get_queryset().filter(id__in=task_ids).values_list('id', flat=True)
        )
        scoped_ids = [tid for tid in task_ids if tid in allowed_ids]
        if not scoped_ids:
            return Response({'detail': 'لا توجد مهام مسموح بها ضمن المحدد'}, status=400)

        result = services.bulk_task_action(
            task_ids=scoped_ids, action=action, actor=actor,
            note=note, preset_id=preset,
            assign_kwargs=assign_kw or None,
        )
        return Response(result)

    # ── Feature 3: Create campaign from current filter ─────────────────────────
    @action(detail=False, methods=['post'], url_path='create-campaign')
    def create_campaign(self, request):
        """
        POST /api/followups/tasks/create-campaign/
        Create a WhatsAppCampaign from a filtered set of tasks.
        Body: { task_ids: [int], name: str, message_template: str,
                featured_item_id?: int }
        """
        actor            = _profile(request)
        task_ids         = request.data.get('task_ids', [])
        name             = request.data.get('name', '').strip()
        template         = request.data.get('message_template', '').strip()
        featured_item_id = request.data.get('featured_item_id')

        if not task_ids:
            return Response({'detail': 'task_ids مطلوبة'}, status=400)
        if not name:
            return Response({'detail': 'name مطلوب'}, status=400)
        if not template:
            return Response({'detail': 'message_template مطلوب'}, status=400)

        # Scope to tasks the user may access (branch restrictions etc.)
        scoped_ids = list(
            self.get_queryset().filter(id__in=task_ids).values_list('id', flat=True)
        )
        if not scoped_ids:
            return Response({'detail': 'لا توجد مهام مسموح بها ضمن المحدد'}, status=400)

        try:
            campaign = services.create_campaign_from_tasks(
                task_ids=scoped_ids, name=name,
                message_template=template, actor=actor,
                featured_item_id=featured_item_id,
            )
        except Exception as e:
            return Response({'detail': str(e)}, status=400)

        return Response({
            'campaign_id':       campaign.id,
            'campaign_name':     campaign.name,
            'estimated_reach':   campaign.estimated_reach,
            'messages_queued':   campaign.messages_queued,
            'status':            campaign.status,
        })

    # ── Feature 1: Update priority scores (admin trigger) ─────────────────────
    @action(detail=False, methods=['post'], url_path='update-priority-scores')
    def update_priority_scores(self, request):
        """POST /api/followups/tasks/update-priority-scores/ — admin only."""
        if _profile(request) and _profile(request).role != 'admin':
            return Response({'detail': 'للمدير فقط'}, status=403)
        count = services.update_priority_scores()
        return Response({'tasks_updated': count})

    # ── Feature 7: My personal queue ──────────────────────────────────────────
    @action(detail=False, methods=['get'], url_path='my-queue')
    def my_queue(self, request):
        """
        GET /api/followups/tasks/my-queue/
        Returns the requesting user's personal prioritised work queue:
          tasks assigned to them (via FollowUpTaskAssignment) that are still active,
          sorted by priority_score DESC then due_date ASC.
        Also returns daily completion stats.
        """
        from datetime import date
        from django.db.models import Count
        from .models import FollowUpTaskAssignment

        profile = _profile(request)
        if not profile:
            return Response({'detail': 'غير مصرّح'}, status=403)

        today = date.today()

        # Active assigned tasks
        qs = (
            FollowUpTask.objects
            .filter(
                assignments__staff=profile,
                status__in=('pending', 'called'),
            )
            .distinct()
            .select_related(
                'customer', 'local_customer', 'item', 'branch',
                'assigned_to__user', 'pinned_by__user', 'chronic_profile',
            )
            .prefetch_related('assignments__staff__user')
            .order_by('-priority_score', 'due_date')
        )

        # Stats for today
        total_assigned = FollowUpTaskAssignment.objects.filter(staff=profile).count()
        done_today     = FollowUpTask.objects.filter(
            assignments__staff=profile,
            status__in=('done', 'auto_closed'),
            completed_at__date=today,
        ).distinct().count()
        overdue_count  = qs.filter(due_date__lt=today).count()
        due_today      = qs.filter(due_date=today).count()

        tasks = list(qs[:50])   # cap at 50 for the daily queue
        serialized = FollowUpTaskListSerializer(
            tasks, many=True, context=self.get_serializer_context(),
        ).data

        return Response({
            'queue':          serialized,
            'stats': {
                'total_assigned':  total_assigned,
                'active_queue':    qs.count(),
                'done_today':      done_today,
                'overdue':         overdue_count,
                'due_today':       due_today,
                'completion_pct':  round(
                    done_today / max(total_assigned, 1) * 100, 1
                ),
            },
        })

    # ── Feature 22: Dead account cleanup ──────────────────────────────────────
    @action(detail=False, methods=['post'], url_path='cleanup-dead')
    def cleanup_dead(self, request):
        """POST /api/followups/tasks/cleanup-dead/ — admin only."""
        if _profile(request) and _profile(request).role != 'admin':
            return Response({'detail': 'للمدير فقط'}, status=403)
        min_attempts  = int(request.data.get('min_attempts', 5))
        min_days      = int(request.data.get('min_stale_days', 30))
        dry_run       = bool(request.data.get('dry_run', False))
        count = services.cleanup_dead_accounts(
            min_attempts=min_attempts, min_stale_days=min_days, dry_run=dry_run,
        )
        return Response({'cancelled': count, 'dry_run': dry_run})

    # ── Feature 21: Extended auto-close with substitute detection ──────────────
    @action(detail=False, methods=['post'], url_path='auto-close-extended')
    def auto_close_extended(self, request):
        """POST /api/followups/tasks/auto-close-extended/ — exact + substitute detection."""
        minutes = int(request.data.get('minutes', 60 * 24))
        result  = services.auto_close_with_substitute_detection(since_minutes=minutes)
        return Response(result)

    @action(detail=False, methods=['post'], url_path='deduplicate')
    def deduplicate(self, request):
        """
        POST /api/followups/tasks/deduplicate/
        Remove duplicate open tasks (same phcode + item_id).
        Body: { dry_run?: bool }
        Admin only.
        """
        profile = _profile(request)
        if not profile or profile.role != 'admin':
            return Response({'detail': 'للمدير فقط'}, status=403)
        dry_run = bool(request.data.get('dry_run', False))
        result  = services.deduplicate_open_tasks(dry_run=dry_run)
        return Response({**result, 'dry_run': dry_run})

    @action(detail=False, methods=['post'], url_path='backfill-tx-detail')
    def backfill_tx_detail(self, request):
        """
        POST /api/followups/tasks/backfill-tx-detail/
        Fills source_erp_transaction (docnumber), source_softech_branch_code,
        source_total_amount, source_item_qty, source_item_price for existing tasks
        that were created before migration 0011.
        Admin only.
        """
        profile = _profile(request)
        if not profile or profile.role != 'admin':
            return Response({'detail': 'للمدير فقط'}, status=403)
        count = services.backfill_transaction_details()
        return Response({'tasks_updated': count})
