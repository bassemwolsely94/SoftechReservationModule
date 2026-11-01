import ipaddress

from rest_framework import serializers

from datetime import timedelta

from django.utils import timezone

from .models import Device, TrustedNetwork

CIDR_BAD = 'نطاق الشبكة غير صحيح (مثال: 192.168.3.0/24)'


class TrustedNetworkSerializer(serializers.ModelSerializer):
    branch_label = serializers.SerializerMethodField()

    class Meta:
        model = TrustedNetwork
        fields = ['id', 'name', 'cidr', 'kind', 'branch', 'branch_label', 'is_active', 'notes', 'updated_at']
        read_only_fields = ['id', 'updated_at']
        extra_kwargs = {'cidr': {'validators': [], 'error_messages': {'blank': CIDR_BAD, 'required': CIDR_BAD, 'null': CIDR_BAD}}}

    def get_branch_label(self, obj):
        b = obj.branch
        return (b.name_ar or b.name) if b else None

    def validate_cidr(self, value):
        try:
            cidr = str(ipaddress.ip_network((value or '').strip(), strict=False))
        except ValueError:
            raise serializers.ValidationError(CIDR_BAD)
        dup = TrustedNetwork.objects.filter(cidr=cidr)
        if self.instance is not None:
            dup = dup.exclude(pk=self.instance.pk)
        existing = dup.first()
        if existing:
            raise serializers.ValidationError(f'هذا النطاق ({cidr}) مسجّل بالفعل باسم «{existing.name}»')
        return cidr


class DeviceSerializer(serializers.ModelSerializer):
    """Admin view of a device. Writable: name, kind, branch, owner, allowed_roles; the status
    only changes through the approve / block / retire actions."""
    branch_label = serializers.SerializerMethodField()
    owner_name = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()
    kind_label = serializers.SerializerMethodField()
    last_network_label = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()
    users = serializers.SerializerMethodField()

    class Meta:
        model = Device
        fields = ['id', 'public_id', 'name', 'kind', 'kind_label', 'status', 'status_label', 'status_note',
                  'branch', 'branch_label', 'owner', 'owner_name', 'allowed_roles',
                  'first_ip', 'last_ip', 'first_network', 'last_network', 'last_network_label', 'last_site',
                  'user_agent', 'first_seen', 'last_seen', 'approved_by_name', 'approved_at', 'users']
        read_only_fields = [f for f in fields if f not in ('name', 'kind', 'branch', 'owner', 'allowed_roles')]

    def get_branch_label(self, obj):
        b = obj.branch
        return (b.name_ar or b.name) if b else None

    def get_owner_name(self, obj):
        return obj.owner.full_name if obj.owner_id else None

    def get_approved_by_name(self, obj):
        return obj.approved_by.full_name if obj.approved_by_id else None

    def get_status_label(self, obj):
        return dict(Device.STATUS_CHOICES).get(obj.status, obj.status)

    def get_kind_label(self, obj):
        return dict(Device.KIND_CHOICES).get(obj.kind, obj.kind)

    def get_last_network_label(self, obj):
        if obj.last_network == 'internal':
            return f'داخل الشبكة — {obj.last_site}' if obj.last_site else 'داخل الشبكة'
        return 'خارج الشبكة' if obj.last_network else ''

    def get_users(self, obj):
        from .devices import MFA_REMEMBER_DAYS
        limit = timezone.now() - timedelta(days=MFA_REMEMBER_DAYS)
        links = sorted(obj.device_users.all(),
                       key=lambda link: link.last_seen.timestamp() if link.last_seen else 0, reverse=True)
        return [{'id': link.user_id, 'name': link.user.full_name, 'role': link.user.role,
                 'last_seen': link.last_seen,
                 'mfa_remembered': bool(link.mfa_remembered_at and link.mfa_remembered_at >= limit)}
                for link in links]
