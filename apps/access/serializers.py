import ipaddress

from rest_framework import serializers

from .models import TrustedNetwork

CIDR_BAD = 'نطاق الشبكة غير صحيح (مثال: 192.168.3.0/24)'


class TrustedNetworkSerializer(serializers.ModelSerializer):
    branch_label = serializers.SerializerMethodField()

    class Meta:
        model = TrustedNetwork
        fields = ['id', 'name', 'cidr', 'kind', 'branch', 'branch_label', 'is_active', 'notes', 'updated_at']
        read_only_fields = ['id', 'updated_at']
        extra_kwargs = {'cidr': {'error_messages': {'blank': CIDR_BAD, 'required': CIDR_BAD, 'null': CIDR_BAD}}}

    def get_branch_label(self, obj):
        b = obj.branch
        return (b.name_ar or b.name) if b else None

    def validate_cidr(self, value):
        try:
            return str(ipaddress.ip_network((value or '').strip(), strict=False))
        except ValueError:
            raise serializers.ValidationError(CIDR_BAD)
