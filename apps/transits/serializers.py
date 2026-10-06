"""
apps/transits/serializers.py

Serializers for the Transfers In Transit module.
Field-level security: sensitive ERP codes are read-only; local actions
are write-only inputs that never expose internal IDs.
"""
from rest_framework import serializers
from apps.branches.models import Branch
from .models import (InTransitTransfer, InTransitNote, InTransitAuditEvent,
                     PickZone, PickZoneRule, ItemPickOverride)


# ── Note ─────────────────────────────────────────────────────────────────────

class InTransitNoteSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()
    type_icon       = serializers.SerializerMethodField()

    def get_created_by_name(self, obj):
        return obj.created_by.full_name if obj.created_by_id else 'النظام'

    def get_type_icon(self, obj):
        return {'note': '📝', 'system': '⚙️', 'alert': '🔔'}.get(obj.note_type, '📝')

    class Meta:
        model  = InTransitNote
        fields = ['id', 'note_type', 'type_icon', 'body',
                  'created_by_name', 'created_at']


class InTransitNoteCreateSerializer(serializers.Serializer):
    body = serializers.CharField(min_length=1, max_length=2000)


# ── Audit ─────────────────────────────────────────────────────────────────────

class InTransitAuditSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    def get_actor_name(self, obj):
        return obj.actor.full_name if obj.actor_id else 'النظام'

    class Meta:
        model  = InTransitAuditEvent
        fields = ['id', 'action', 'actor_name', 'detail', 'created_at']


# ── List serializer (lightweight — for grid rows) ─────────────────────────────

class InTransitTransferListSerializer(serializers.ModelSerializer):
    supplying_branch_name  = serializers.SerializerMethodField()
    receiving_branch_name  = serializers.SerializerMethodField()
    priority_color         = serializers.CharField(read_only=True)
    priority_label         = serializers.CharField(source='priority_label_ar', read_only=True)
    has_near_expiry        = serializers.BooleanField(read_only=True)
    transit_status_display = serializers.CharField(
        source='get_transit_status_display', read_only=True
    )
    linked_request_number  = serializers.SerializerMethodField()

    def get_supplying_branch_name(self, obj):
        if obj.supplying_branch_id:
            return obj.supplying_branch.name_ar or obj.supplying_branch.name
        return obj.erp_supplying_branch_code

    def get_receiving_branch_name(self, obj):
        if obj.receiving_branch_id:
            return obj.receiving_branch.name_ar or obj.receiving_branch.name
        return obj.erp_receiving_branch_code or '—'

    def get_linked_request_number(self, obj):
        return obj.linked_request.request_number if obj.linked_request_id else None

    class Meta:
        model  = InTransitTransfer
        fields = [
            'id',
            'erp_doc_number',
            'erp_supplying_branch_code',
            'erp_receiving_branch_code',
            'supplying_branch',
            'supplying_branch_name',
            'receiving_branch',
            'receiving_branch_name',
            'issue_date',
            'days_in_transit',
            'transit_status',
            'transit_status_display',
            'priority',
            'priority_color',
            'priority_label',
            'cancellation_available',
            'doc_value',
            'item_count',
            'total_quantity',
            'has_near_expiry',
            'has_discrepancy',
            'linked_request_number',
            'last_synced_at',
        ]


# ── Detail serializer (full — for detail panel / modal) ──────────────────────

class InTransitTransferDetailSerializer(InTransitTransferListSerializer):
    notes        = InTransitNoteSerializer(many=True, read_only=True)
    audit_events = InTransitAuditSerializer(many=True, read_only=True)
    linked_request_detail = serializers.SerializerMethodField()
    fefo_warning  = serializers.SerializerMethodField()
    # items_snapshot enriched with a spelled-out partial-pack breakdown so the
    # UI can show a fractional quantity BOTH as the exact number (2.25) and as
    # packs + sub-units (٢ علبة + ١ شريط). Raw values are never rounded.
    items_snapshot = serializers.SerializerMethodField()

    def get_items_snapshot(self, obj):
        from apps.catalog.models import Item
        from apps.transits.export import _qty_parts

        snapshot = obj.items_snapshot or []
        codes = [str(e.get('itemcode') or '').strip() for e in snapshot]
        pack_map = dict(
            Item.objects.filter(softech_id__in=[c for c in codes if c])
            .values_list('softech_id', 'pack_qty')
        )
        out = []
        for e in snapshot:
            item = dict(e)   # copy — never mutate the stored JSON
            code = str(e.get('itemcode') or '').strip()
            name = e.get('itemname', '')
            pack = pack_map.get(code, 1)
            qty_text, is_partial = _qty_parts(e.get('qty'), pack, name)
            item['qty_text'] = qty_text
            item['is_partial'] = is_partial
            # Per-batch breakdown (SOFTECH-style separate lines), each with its
            # own spelled-out partial-pack quantity.
            batches = []
            for b in (e.get('batches') or []):
                b2 = dict(b)
                bt, bp = _qty_parts(b.get('qty'), pack, name)
                b2['qty_text'] = bt
                b2['is_partial'] = bp
                batches.append(b2)
            item['batches'] = batches
            item['batch_count'] = len(batches)
            out.append(item)
        return out

    def get_linked_request_detail(self, obj):
        if not obj.linked_request_id:
            return None
        tr = obj.linked_request
        return {
            'id':             tr.id,
            'request_number': tr.request_number,
            'status':         tr.status,
            'submitted_at':   tr.submitted_at,
            'created_by':     tr.created_by.full_name if tr.created_by_id else None,
        }

    def get_fefo_warning(self, obj):
        """Return list of near-expiry items (≤45 days) from snapshot."""
        import datetime
        today = datetime.date.today()
        cutoff = today + datetime.timedelta(days=45)
        near = []
        for item in (obj.items_snapshot or []):
            exp = item.get('expiry')
            if exp:
                try:
                    if isinstance(exp, str):
                        exp_date = datetime.date.fromisoformat(exp)
                    else:
                        exp_date = exp
                    if exp_date <= cutoff:
                        days_left = (exp_date - today).days
                        near.append({
                            'itemcode':   item.get('itemcode', ''),
                            'itemname':   item.get('itemname', ''),
                            'expiry':     exp,
                            'days_left':  days_left,
                        })
                except (ValueError, TypeError):
                    pass
        return near

    class Meta(InTransitTransferListSerializer.Meta):
        fields = InTransitTransferListSerializer.Meta.fields + [
            'erp_user_code',
            'erp_store_code',
            'erp_received_date',
            'cancellation_expires_at',
            'items_snapshot',
            'received_items_snapshot',
            'reconciliation',
            'internal_notes',
            'manually_received_at',
            'manually_received_by',
            'force_close_reason',
            'alert_notification_count',
            'last_alert_sent_at',
            'first_seen_at',
            'notes',
            'audit_events',
            'linked_request_detail',
            'fefo_warning',
        ]


# ── Write serializers ─────────────────────────────────────────────────────────

class MarkReceivedSerializer(serializers.Serializer):
    note = serializers.CharField(
        required=False, allow_blank=True, max_length=1000,
        help_text='اختياري — ملاحظة اليد الاستلام',
    )


class ForceCloseSerializer(serializers.Serializer):
    reason = serializers.CharField(
        min_length=10, max_length=1000,
        help_text='يجب تحديد سبب الإغلاق القسري (10 أحرف على الأقل)',
    )


# ── Dashboard ─────────────────────────────────────────────────────────────────

class TransitDashboardSerializer(serializers.Serializer):
    total_in_transit       = serializers.IntegerField()
    total_value            = serializers.DecimalField(max_digits=18, decimal_places=2, allow_null=True)
    avg_days_in_transit    = serializers.FloatField(allow_null=True)
    critical_count         = serializers.IntegerField()
    red_count              = serializers.IntegerField()
    orange_count           = serializers.IntegerField()
    received_today         = serializers.IntegerField()
    issued_today           = serializers.IntegerField()
    cancellation_expiring  = serializers.IntegerField(
        help_text='قيد النقل وتنتهي مهلة الإلغاء خلال 24 ساعة'
    )
    by_supplying_branch    = serializers.ListField(child=serializers.DictField())
    by_receiving_branch    = serializers.ListField(child=serializers.DictField())


# ── Pick zones (replenishment picking-sheet classification) ──────────────────

class PickZoneSerializer(serializers.ModelSerializer):
    # explicit so the (branch, purpose, name) unique validator accepts absences
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.all(), required=False, allow_null=True, default=None)
    purpose = serializers.ChoiceField(
        choices=PickZone.PURPOSE_CHOICES, required=False, default='picking')
    rule_count     = serializers.IntegerField(read_only=True)
    override_count = serializers.IntegerField(read_only=True)

    class Meta:
        model  = PickZone
        fields = ['id', 'branch', 'purpose', 'name', 'sort_key', 'location', 'color', 'is_active',
                  'is_price_zone', 'is_fridge_zone', 'is_fallback',
                  'rule_count', 'override_count', 'updated_at']
        read_only_fields = ['updated_at']


class PickZoneRuleSerializer(serializers.ModelSerializer):
    zone_name = serializers.CharField(source='zone.name', read_only=True)

    class Meta:
        model  = PickZoneRule
        fields = ['id', 'zone', 'zone_name', 'match_field', 'keywords', 'priority',
                  'is_active', 'note', 'updated_at']
        read_only_fields = ['updated_at']

    def validate_keywords(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('يجب أن تكون الكلمات قائمة')
        cleaned = [str(k).strip() for k in value if str(k).strip()]
        if not cleaned:
            raise serializers.ValidationError('أدخل كلمة مفتاحية واحدة على الأقل')
        return cleaned


class ItemPickOverrideSerializer(serializers.ModelSerializer):
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.all(), required=False, allow_null=True, default=None)
    purpose = serializers.ChoiceField(
        choices=PickZone.PURPOSE_CHOICES, required=False, default='picking')
    item_code  = serializers.CharField(write_only=True)
    item_softech_id = serializers.CharField(source='item.softech_id', read_only=True)
    item_name  = serializers.CharField(source='item.name', read_only=True)
    item_price = serializers.DecimalField(source='item.pack_price', max_digits=10,
                                          decimal_places=3, read_only=True)
    zone_name  = serializers.CharField(source='zone.name', read_only=True)
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model  = ItemPickOverride
        fields = ['id', 'branch', 'purpose', 'item_code', 'item_softech_id', 'item_name', 'item_price',
                  'zone', 'zone_name', 'tag', 'created_by_name', 'updated_at']
        read_only_fields = ['updated_at']

    def get_created_by_name(self, obj):
        return obj.created_by.full_name if obj.created_by_id else '—'

    def validate_item_code(self, value):
        from apps.catalog.models import Item
        item = Item.objects.filter(softech_id=str(value).strip()).first()
        if item is None:
            raise serializers.ValidationError('كود الصنف غير موجود في الكتالوج')
        return item

    def create(self, validated_data):
        from .models import ItemPickOverride
        item = validated_data.pop('item_code')
        # upsert — one override per (item, location config, purpose)
        obj, _ = ItemPickOverride.objects.update_or_create(
            item=item,
            branch=validated_data.get('branch'),
            purpose=validated_data.get('purpose', 'picking'),
            defaults={
                'zone': validated_data['zone'],
                'tag': validated_data.get('tag', ''),
                'created_by': validated_data.get('created_by'),
            },
        )
        return obj

    def update(self, instance, validated_data):
        validated_data.pop('item_code', None)
        return super().update(instance, validated_data)

