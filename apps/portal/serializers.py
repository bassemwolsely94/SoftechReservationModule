"""
apps/portal/serializers.py

Input validation for portal write actions. Read responses are assembled as
plain dicts in the views (they aggregate several models), mirroring the public
`delivery_public_track` style. NB: no serializer here accepts a customer id —
the customer is always taken from the authenticated session.
"""
from decimal import Decimal

from django.conf import settings
from rest_framework import serializers

# Owner 2026-11-01 (Batch 6, W-5): a reorder line is 1…20, any catalogue item.
REORDER_MAX_QTY = Decimal(str(getattr(settings, 'PORTAL_REORDER_MAX_QTY', 20)))


class RequestLinkSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=50)


class AuthExchangeSerializer(serializers.Serializer):
    token = serializers.CharField()


class ReorderSerializer(serializers.Serializer):
    # Either a catalog item id OR a free-text name (for not-yet-coded items).
    item = serializers.IntegerField(required=False)
    manual_item_name = serializers.CharField(max_length=500, required=False, allow_blank=True)
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, default=1,
                                        min_value=Decimal('1'), max_value=REORDER_MAX_QTY)
    notes = serializers.CharField(max_length=1000, required=False, allow_blank=True)

    def validate(self, attrs):
        if not attrs.get('item') and not (attrs.get('manual_item_name') or '').strip():
            raise serializers.ValidationError('حدّد الصنف المطلوب')
        return attrs
