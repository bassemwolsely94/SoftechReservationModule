"""
apps/followups/serializers.py

Rich serializers for the Chronic Refill & Follow-up module.

Design:
  - List/Detail serializers embed FULL customer + product (catalog) + dosing +
    transaction + channel context so the UI can show everything in one card
    without extra round-trips.
  - All nested data is read from select_related/prefetch_related fields set in
    the view's get_queryset — no per-row queries here.
"""
from rest_framework import serializers
from .models import ChronicMedicationProfile, FollowUpTask


# ── Chronic Medication Profile ──────────────────────────────────────────────────

class ChronicMedicationProfileSerializer(serializers.ModelSerializer):
    item_name       = serializers.CharField(source='item.name',       read_only=True)
    item_softech_id = serializers.CharField(source='item.softech_id', read_only=True)
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True)
    source_label    = serializers.CharField(source='get_source_display', read_only=True)

    class Meta:
        model  = ChronicMedicationProfile
        fields = [
            'id', 'item', 'item_name', 'item_softech_id',
            'is_chronic', 'avg_daily_usage', 'pack_size',
            'expected_duration_days', 'followup_before_days', 'followup_trigger_day',
            'notes', 'source', 'source_label',
            'created_by_name', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at', 'created_by', 'followup_trigger_day']


class ChronicMedicationProfileWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ChronicMedicationProfile
        fields = [
            'item', 'is_chronic', 'avg_daily_usage',
            'pack_size', 'followup_before_days', 'notes',
        ]

    def validate_avg_daily_usage(self, v):
        if v <= 0:
            raise serializers.ValidationError('الاستخدام اليومي يجب أن يكون أكبر من صفر')
        return v


# ── Shared block builders (plain functions — reused by list & detail) ────────────

_PHONE_MASKED = '●●●●●●●●●●'   # shown when user lacks can_see_phone permission


def _mask(phone: str, visible: bool) -> str:
    """Return raw phone if visible, masked placeholder otherwise."""
    if not phone:
        return ''
    return phone if visible else _PHONE_MASKED


def build_customer_block(task, can_see_phone: bool = True) -> dict:
    """
    Full customer context for the follow-up card.

    Resolution order (best available data wins):
      1. task.customer     — linked customers.Customer (full CRM data)
      2. task.local_customer — erp.LocalCustomer (PIC/delivery — has name + phone)
      3. task.phcode field — bare ERP code (last resort)

    Phone fields are masked when can_see_phone=False.
    """
    # ── Case 1: Full Customer record linked ───────────────────────────────────
    c = task.customer if task.customer_id else None
    if c:
        raw_phone     = c.phone or ''
        raw_whatsapp  = c.whatsapp_phone or c.phone or ''
        return {
            'id':                  c.id,
            'name':                c.name or '',
            'phone':               _mask(raw_phone, can_see_phone),
            'whatsapp_phone':      _mask(raw_whatsapp, can_see_phone),
            'phone_available':     bool(raw_phone),
            'phcode':              c.softech_pic or c.softech_id or task.phcode or '',
            'channel_code':        c.softech_ptclassifcode or task.sales_channel,
            'channel_label':       c.person_classif_label or task.sales_channel_label,
            'segment':             c.segment or '',
            'churn_segment':       c.churn_segment or '',
            'churn_score':         round(float(c.churn_score or 0) * 100, 1),
            'ltv':                 float(c.ltv or 0),
            'days_since_last_visit': c.days_since_last_visit,
            'can_see_phone':       can_see_phone,
            'is_linked':           True,
            'source':              'customer',
        }

    # ── Case 2: LocalCustomer (PIC / unlinked delivery customer) ─────────────
    lc = task.local_customer if task.local_customer_id else None
    if lc:
        raw_phone = lc.phone or lc.phone_alt or ''
        return {
            'id':                  None,
            'name':                lc.name or task.phcode or '—',
            'phone':               _mask(raw_phone, can_see_phone),
            'whatsapp_phone':      _mask(raw_phone, can_see_phone),   # LC has one phone field
            'phone_available':     bool(raw_phone),
            'phcode':              lc.phcode or task.phcode or '',
            'channel_code':        task.sales_channel,
            'channel_label':       task.sales_channel_label,
            'segment':             '',
            'churn_segment':       '',
            'churn_score':         0,
            'ltv':                 0,
            'days_since_last_visit': None,
            'can_see_phone':       can_see_phone,
            'is_linked':           False,
            'source':              'local_customer',
        }

    # ── Case 3: Only a phcode — bare minimum ─────────────────────────────────
    phcode = task.phcode or ''
    return {
        'id':                  None,
        'name':                phcode or '—',
        'phone':               '',
        'whatsapp_phone':      '',
        'phone_available':     False,
        'phcode':              phcode,
        'channel_code':        task.sales_channel,
        'channel_label':       task.sales_channel_label,
        'segment':             '',
        'churn_segment':       '',
        'churn_score':         0,
        'ltv':                 0,
        'days_since_last_visit': None,
        'can_see_phone':       can_see_phone,
        'is_linked':           False,
        'source':              'phcode_only',
    }


def build_product_block(task) -> dict:
    """Full catalog context: indication, dosage form, pack size, pricing, dosing."""
    item = task.item if task.item_id else None
    if not item:
        return {'id': None, 'name': '—'}

    prof = task.chronic_profile if task.chronic_profile_id else None

    # Indications (primary + secondary therapeutic effect from catalog)
    indications = [
        x for x in [item.effect_name_ar, item.effect_name2_ar] if x
    ]

    return {
        'id':                item.id,
        'softech_id':        item.softech_id,
        'name':              item.name,
        'name_scientific':   item.name_scientific or '',
        'active_ingredients': item.active_ingredients or '',
        # Therapeutic indication (the disease/use)
        'indication':        ' / '.join(indications) if indications else '',
        'indications':       indications,
        'effect_code':       item.effect_code or '',
        # Dosage form & physical size
        'dosage_form':       item.shape_name_ar or item.shape_name or '',
        'pack_qty':          item.pack_qty,
        'unit_name':         item.unit_name or '',
        'pack_size_label':   f'{item.pack_qty} {item.unit_name}'.strip() if item.pack_qty else '',
        'medicine_type':     item.medicine_type_name_ar or item.medicine_type_name or '',
        'requires_fridge':   item.requires_fridge,
        # Pricing (for upsell value)
        'pack_price':        float(item.pack_price or 0),
        'unit_price':        float(item.unit_price or 0),
        # Dosing for refill accuracy (from chronic profile if set)
        'avg_daily_usage':   float(prof.avg_daily_usage) if prof else None,
        'profile_pack_size': float(prof.pack_size) if prof else None,
        'expected_duration_days': prof.expected_duration_days if prof else None,
    }


def build_refill_block(task) -> dict:
    """
    Refill timing + full SOFTECH transaction reference for the triggering sale.

    Fields for SOFTECH ERP retrieval:
      docnumber          → search in SOFTECH by this document number
      softech_branch_code → the branch code in SOFTECH (e.g. "08")
      branch_name        → Arabic branch name (from FK)
      total_amount       → full invoice total at time of sale
      item_qty           → quantity of this specific item sold
      item_price         → unit price at time of sale
      item_line_total    → item_qty × item_price (computed)
    """
    # Branch info — prefer branch FK, fall back to raw code
    branch_name = ''
    branch_code = task.source_softech_branch_code or ''
    if task.branch_id and task.branch:
        branch_name = task.branch.name_ar or task.branch.name or ''
        if not branch_code:
            branch_code = getattr(task.branch, 'softech_branch_id', '') or ''

    # Item line total
    qty   = float(task.source_item_qty   or 0)
    price = float(task.source_item_price or 0)
    line_total = round(qty * price, 2) if qty and price else None

    return {
        # ── Timing ────────────────────────────────────────────────────────────
        'last_sale_date':   str(task.source_sale_date) if task.source_sale_date else None,
        'due_date':         str(task.due_date) if task.due_date else None,
        'days_until_due':   task.days_until_due,
        'days_overdue':     task.days_overdue,
        'is_overdue':       task.is_overdue,
        # ── SOFTECH transaction reference ──────────────────────────────────────
        'docnumber':              task.source_erp_transaction or '',
        'softech_branch_code':    branch_code,
        'branch_name':            branch_name,
        'total_amount':           float(task.source_total_amount) if task.source_total_amount is not None else None,
        'item_qty':               float(task.source_item_qty)    if task.source_item_qty    is not None else None,
        'item_price':             float(task.source_item_price)  if task.source_item_price  is not None else None,
        'item_line_total':        line_total,
        # ── Legacy field (kept for backward compat) ────────────────────────────
        'source_transaction':     task.source_erp_transaction or '',
    }


# ── Follow-up Task — LIST (rich card) ───────────────────────────────────────────

class FollowUpTaskListSerializer(serializers.ModelSerializer):
    customer         = serializers.SerializerMethodField()
    product          = serializers.SerializerMethodField()
    refill           = serializers.SerializerMethodField()
    branch_name      = serializers.CharField(source='branch.name_ar', read_only=True, default='')
    assigned_to_name = serializers.CharField(source='assigned_to.full_name', read_only=True, default='')
    status_label     = serializers.CharField(source='get_status_display', read_only=True)
    task_type_label  = serializers.CharField(source='get_task_type_display', read_only=True)
    channel_label    = serializers.CharField(source='sales_channel_label', read_only=True)
    channel_priority = serializers.IntegerField(read_only=True)
    is_overdue       = serializers.BooleanField(read_only=True)
    days_overdue     = serializers.IntegerField(read_only=True)
    days_until_due   = serializers.IntegerField(read_only=True)
    whatsapp_url     = serializers.CharField(read_only=True)
    pinned_by_name   = serializers.CharField(source='pinned_by.full_name', read_only=True, default='')
    demand_number    = serializers.CharField(source='demand_record.demand_number', read_only=True, default='')
    assignee_count   = serializers.SerializerMethodField()
    assignee_names   = serializers.SerializerMethodField()

    def get_assignee_count(self, obj):
        try:
            # Use the prefetched cache (assignments__staff__user) — len() does NOT
            # issue a fresh COUNT query the way .count() would, avoiding N+1 on the
            # grouped endpoint which serialises up to 2000 tasks.
            return len(obj.assignments.all())
        except Exception:
            return 0

    def get_assignee_names(self, obj):
        """Short list of assignee names for display on the card."""
        try:
            all_assignments = list(obj.assignments.all())   # uses prefetch cache
            names = [a.staff.full_name for a in all_assignments[:3]]
            if len(all_assignments) > 3:
                names.append(f'+{len(all_assignments) - 3}')
            return names
        except Exception:
            return []

    def _can_see_phone(self) -> bool:
        return self.context.get('can_see_phone', True)

    def get_customer(self, obj): return build_customer_block(obj, self._can_see_phone())
    def get_product(self, obj):  return build_product_block(obj)
    def get_refill(self, obj):   return build_refill_block(obj)

    class Meta:
        model  = FollowUpTask
        fields = [
            'id', 'task_type', 'task_type_label',
            'status', 'status_label',
            'sales_channel', 'channel_label', 'channel_priority',
            'branch', 'branch_name',
            'assigned_to', 'assigned_to_name',
            'is_pinned', 'pinned_by_name',
            'assignee_count', 'assignee_names',
            'priority_score', 'phone_invalid',
            'demand_number',
            'attempts', 'is_overdue', 'days_overdue', 'days_until_due',
            'whatsapp_url',
            'reminder_at', 'reminder_sent',
            'created_at',
            # Rich blocks
            'customer', 'product', 'refill',
        ]


# ── Follow-up Task — DETAIL (adds FBT + whatsapp message + call history) ─────────

class FollowUpTaskDetailSerializer(serializers.ModelSerializer):
    customer          = serializers.SerializerMethodField()
    product           = serializers.SerializerMethodField()
    refill            = serializers.SerializerMethodField()
    complementary     = serializers.SerializerMethodField()
    assignments_list  = serializers.SerializerMethodField()   # all current assignees
    chronic_profile   = serializers.SerializerMethodField()   # dosing config for product tab
    whatsapp_message  = serializers.CharField(source='render_whatsapp_message', read_only=True)
    whatsapp_url      = serializers.CharField(read_only=True)
    whatsapp_url_with_message = serializers.CharField(read_only=True)
    call_history      = serializers.SerializerMethodField()
    branch_name       = serializers.CharField(source='branch.name_ar', read_only=True, default='')
    assigned_to_name  = serializers.CharField(source='assigned_to.full_name', read_only=True, default='')
    pinned_by_name    = serializers.CharField(source='pinned_by.full_name', read_only=True, default='')
    demand_number     = serializers.CharField(source='demand_record.demand_number', read_only=True, default='')
    completed_by_name = serializers.CharField(source='completed_by.full_name', read_only=True, default='')
    status_label      = serializers.CharField(source='get_status_display', read_only=True)
    task_type_label   = serializers.CharField(source='get_task_type_display', read_only=True)
    channel_label     = serializers.CharField(source='sales_channel_label', read_only=True)
    is_overdue        = serializers.BooleanField(read_only=True)
    days_overdue      = serializers.IntegerField(read_only=True)
    days_until_due    = serializers.IntegerField(read_only=True)

    def _can_see_phone(self) -> bool:
        return self.context.get('can_see_phone', True)

    def get_customer(self, obj): return build_customer_block(obj, self._can_see_phone())
    def get_product(self, obj):  return build_product_block(obj)
    def get_refill(self, obj):   return build_refill_block(obj)

    def get_chronic_profile(self, obj):
        """Dosing config — drawer product tab reads followup_before_days."""
        prof = obj.chronic_profile if obj.chronic_profile_id else None
        if not prof:
            return None
        return {
            'followup_before_days':   prof.followup_before_days,
            'expected_duration_days': prof.expected_duration_days,
            'avg_daily_usage':        float(prof.avg_daily_usage) if prof.avg_daily_usage is not None else None,
            'pack_size':              float(prof.pack_size) if prof.pack_size is not None else None,
        }

    def get_assignments_list(self, obj):
        """All current FollowUpTaskAssignment rows — full assignee list."""
        try:
            return [
                {
                    'staff_id':   a.staff_id,
                    'name':       a.staff.full_name,
                    'role':       a.staff.role,
                    'role_label': a.staff.get_role_display(),
                    'branch_name': a.staff.branch.name_ar if a.staff.branch_id and a.staff.branch else '',
                    'reason':     a.assignment_reason,
                    'assigned_at': a.assigned_at.isoformat() if a.assigned_at else None,
                    'assigned_by': a.assigned_by.full_name if a.assigned_by_id and a.assigned_by else '',
                }
                for a in obj.assignments.all()
            ]
        except Exception:
            return []

    def get_complementary(self, obj):
        """Frequently-bought-together products → cross-sell suggestions."""
        if not obj.item_id:
            return []
        try:
            from apps.recommendations.engine import get_fbt_for_item
            return get_fbt_for_item(obj.item_id, limit=6)
        except Exception:
            return []

    def get_call_history(self, obj):
        """Recent call-center interactions with this customer (for context)."""
        if not obj.customer_id:
            return []
        try:
            from apps.callcenter.models import CallLog
            calls = (
                CallLog.objects
                .filter(customer_id=obj.customer_id)
                .order_by('-created_at')[:5]
            )
            return [{
                'id':        c.id,
                'direction': c.direction,
                'purpose':   c.purpose,
                'status':    c.status,
                'summary':   (c.summary or c.notes or '')[:120],
                'created_at': c.created_at.isoformat(),
            } for c in calls]
        except Exception:
            return []

    class Meta:
        model  = FollowUpTask
        fields = [
            'id', 'task_type', 'task_type_label',
            'status', 'status_label',
            'sales_channel', 'channel_label',
            'branch', 'branch_name',
            'assigned_to', 'assigned_to_name',
            # Pin / phone / demand / priority — read by the drawer UI
            'is_pinned', 'pinned_by_name',
            'phone_invalid', 'demand_number', 'priority_score',
            'attempts', 'notes', 'result_note',
            'is_overdue', 'days_overdue', 'days_until_due',
            'whatsapp_url', 'whatsapp_url_with_message', 'whatsapp_message',
            'reminder_at', 'reminder_sent',
            'source_erp_transaction', 'source_softech_branch_code',
            'source_total_amount', 'source_item_qty', 'source_item_price',
            'closing_erp_transaction',
            'created_at', 'updated_at', 'completed_at', 'completed_by_name',
            # Rich blocks
            'customer', 'product', 'refill', 'complementary', 'call_history',
            'assignments_list', 'chronic_profile',
        ]


class FollowUpTaskCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = FollowUpTask
        fields = [
            'customer', 'item', 'branch', 'assigned_to',
            'task_type', 'due_date', 'notes', 'reminder_at',
        ]


class FollowUpActionSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True)
