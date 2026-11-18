"""
apps/marketplace/serializers.py — API shapes for /api/marketplace/ (doc 38).

Never serialized: MarketplaceChannel.credentials (write-only) and ExternalOrder.raw_payload. Customer
phones go out through apps/customers/access.py masking (lists always masked; the detail shows the number
only to staff who may see record phones).
"""
from django.conf import settings
from rest_framework import serializers

from apps.branches.models import Branch
from apps.catalog.safety import item_safety_flags

from apps.customers.access import mask, record_phone

from .availability import platform_price, sellable_qty
from .eligibility import listing_problem
from .models import (SettlementBatch, SettlementLine, ChannelListing, ChannelStore, ExternalOrder, ExternalOrderEvent, ExternalOrderLine,
                     MarketplaceChannel, PushLog)


def _staff_name(profile):
    return profile.full_name if profile is not None else ''


class ChannelSerializer(serializers.ModelSerializer):
    credentials = serializers.JSONField(write_only=True, required=False)
    has_credentials = serializers.SerializerMethodField()

    class Meta:
        model = MarketplaceChannel
        fields = ['id', 'code', 'name', 'adapter', 'scope', 'softech_personcode', 'price_rule', 'price_pct',
                  'stock_buffer', 'max_qty_per_item', 'is_active', 'credentials', 'has_credentials',
                  'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']

    def get_has_credentials(self, obj):
        return bool(obj.credentials)

    def validate_adapter(self, value):
        # the test adapter has a shared-secret webhook and no real platform behind it
        if value == MarketplaceChannel.ADAPTER_FAKE and not getattr(settings, 'MARKETPLACE_ALLOW_FAKE_ADAPTER', False):
            raise serializers.ValidationError('المحوّل التجريبي غير متاح على هذا السيرفر.')
        return value

    def validate_code(self, value):
        # orders, webhook URLs and POS draft tokens are keyed on the code: frozen once an order exists
        if self.instance is not None and value != self.instance.code and self.instance.orders.exists():
            raise serializers.ValidationError('لا يمكن تغيير كود المنصة بعد وصول طلبات عليها.')
        return value

    def validate_credentials(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('بيانات الاعتماد يجب أن تكون كائنًا.')
        return value


CLOSED_BRANCH_CODES = frozenset({'110'})


class StoreSerializer(serializers.ModelSerializer):
    channel_name = serializers.CharField(source='channel.name', read_only=True)
    branch_name = serializers.SerializerMethodField()
    branch_code = serializers.CharField(source='branch.softech_branch_id', read_only=True)

    class Meta:
        model = ChannelStore
        fields = ['id', 'channel', 'channel_name', 'branch', 'branch_name', 'branch_code', 'external_store_id',
                  'delivery_mode', 'is_active']

    def get_branch_name(self, obj):
        return str(obj.branch.name_ar or obj.branch.name)

    def validate_branch(self, branch):
        if (not branch.is_active or branch.kind == Branch.KIND_CLOSED
                or (branch.softech_branch_id or '').strip() in CLOSED_BRANCH_CODES):
            raise serializers.ValidationError('هذا الفرع مغلق أو غير نشط — لا يُربط بمنصة.')
        return branch


class ListingSerializer(serializers.ModelSerializer):
    """`approved` / `approved_by` / `approved_at` change only through the approve / unapprove actions.
    `allow_fridge` is set only through the approve action (approve permission, audited).
    `problem`, `qty` and `price` are computed for the branch in context['branch'] (None → qty null);
    `fridge` = the item needs the fridge."""
    item_name = serializers.CharField(source='item.name', read_only=True)
    item_code = serializers.CharField(source='item.softech_id', read_only=True)
    channel_name = serializers.CharField(source='channel.name', read_only=True)
    approved_by_name = serializers.SerializerMethodField()
    problem = serializers.SerializerMethodField()
    qty = serializers.SerializerMethodField()
    price = serializers.SerializerMethodField()
    fridge = serializers.SerializerMethodField()

    class Meta:
        model = ChannelListing
        fields = ['id', 'channel', 'channel_name', 'item', 'item_name', 'item_code', 'external_sku', 'approved',
                  'approved_by', 'approved_by_name', 'approved_at', 'allow_fridge', 'note', 'problem', 'qty', 'price', 'fridge']
        read_only_fields = ['approved', 'approved_by', 'approved_at', 'allow_fridge']

    def get_approved_by_name(self, obj):
        return _staff_name(obj.approved_by)

    def get_problem(self, obj):
        return listing_problem(obj)

    def get_qty(self, obj):
        branch = self.context.get('branch')
        return None if branch is None else str(sellable_qty(obj, branch))

    def get_price(self, obj):
        return str(platform_price(obj))

    def get_fridge(self, obj):
        return any(f['code'] == 'fridge' for f in item_safety_flags(obj.item))


class OrderListSerializer(serializers.ModelSerializer):
    channel_name = serializers.CharField(source='channel.name', read_only=True)
    branch_name = serializers.SerializerMethodField()
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    customer_phone = serializers.SerializerMethodField()
    pos_order = serializers.SerializerMethodField()
    line_count = serializers.SerializerMethodField()

    class Meta:
        model = ExternalOrder
        fields = ['id', 'channel', 'channel_name', 'store', 'branch', 'branch_name', 'external_id', 'source',
                  'status', 'status_label', 'customer_name', 'customer_phone', 'payment_mode', 'platform_total',
                  'reject_reason', 'needs_review', 'pos_order', 'line_count', 'created_at', 'updated_at']

    def get_branch_name(self, obj):
        return str(obj.branch.name_ar or obj.branch.name)

    def get_customer_phone(self, obj):
        return mask(obj.customer_phone) if obj.customer_phone else ''

    def get_pos_order(self, obj):
        p = obj.pos_order
        return {'id': p.pk, 'status': p.status, 'status_label': p.get_status_display()} if p is not None else None

    def get_line_count(self, obj):
        n = getattr(obj, 'n_lines', None)
        return n if n is not None else obj.lines.count()


class OrderLineSerializer(serializers.ModelSerializer):
    problem_label = serializers.CharField(source='get_problem_display', read_only=True)
    item_code = serializers.CharField(source='item.softech_id', read_only=True, default='')

    class Meta:
        model = ExternalOrderLine
        fields = ['id', 'listing', 'item', 'item_code', 'external_sku', 'name', 'qty', 'platform_unit_price',
                  'problem', 'problem_label']


class OrderEventSerializer(serializers.ModelSerializer):
    by_name = serializers.SerializerMethodField()

    class Meta:
        model = ExternalOrderEvent
        fields = ['id', 'from_status', 'to_status', 'by_name', 'note', 'at']

    def get_by_name(self, obj):
        return _staff_name(obj.by)


class OrderDetailSerializer(OrderListSerializer):
    lines = OrderLineSerializer(many=True, read_only=True)
    events = OrderEventSerializer(many=True, read_only=True)
    problems = serializers.SerializerMethodField()

    class Meta(OrderListSerializer.Meta):
        fields = OrderListSerializer.Meta.fields + ['delivery_address', 'lines', 'events', 'problems']

    def get_customer_phone(self, obj):
        request = self.context.get('request')
        return record_phone(request.user, obj.customer_phone) if obj.customer_phone else ''

    def get_problems(self, obj):
        return [{'line': l.id, 'name': l.name or l.external_sku, 'problem': l.problem,
                 'label': l.get_problem_display()} for l in obj.lines.all() if l.problem]


class PushLogSerializer(serializers.ModelSerializer):
    channel_name = serializers.CharField(source='channel.name', read_only=True)
    branch = serializers.IntegerField(source='store.branch_id', read_only=True, default=None)
    kind_label = serializers.CharField(source='get_kind_display', read_only=True)

    class Meta:
        model = PushLog
        fields = ['id', 'channel', 'channel_name', 'store', 'branch', 'kind', 'kind_label', 'dry_run', 'payload',
                  'response', 'ok', 'at']


class SettlementLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = SettlementLine
        fields = ['id', 'external_id', 'gross', 'commission', 'delivery_fee', 'net', 'order', 'match_status', 'note']


class SettlementBatchSerializer(serializers.ModelSerializer):
    channel_name = serializers.CharField(source='channel.name', read_only=True)
    uploaded_by_name = serializers.SerializerMethodField()
    counts = serializers.SerializerMethodField()

    class Meta:
        model = SettlementBatch
        fields = ['id', 'channel', 'channel_name', 'period_from', 'period_to', 'file_name', 'uploaded_by_name',
                  'uploaded_at', 'column_map', 'counts']

    def get_uploaded_by_name(self, obj):
        return getattr(obj.uploaded_by, 'full_name', '') if obj.uploaded_by_id else ''

    def get_counts(self, obj):
        from django.db.models import Count
        rows = obj.lines.values('match_status').annotate(n=Count('id'))
        out = {k: 0 for k, _ in SettlementLine.MATCH_CHOICES}
        out.update({r['match_status']: r['n'] for r in rows})
        return out
