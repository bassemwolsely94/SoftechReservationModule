from rest_framework import serializers
from django.contrib.auth.models import User
from .models import StaffProfile, ERPUser, UserActivityLog


# ── ERP User (read-only) ──────────────────────────────────────────────────────

class ERPUserSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ERPUser
        fields = ['id', 'username', 'full_name', 'branch_code', 'is_active', 'synced_at']


# ── Staff Profile serializers ─────────────────────────────────────────────────

class StaffProfileSerializer(serializers.ModelSerializer):
    """Full read serializer — used by /auth/me/ and admin views."""
    username         = serializers.CharField(source='user.username',           read_only=True)
    email            = serializers.CharField(source='user.email',              read_only=True)
    first_name       = serializers.CharField(source='user.first_name',         read_only=True)
    last_name        = serializers.CharField(source='user.last_name',          read_only=True)
    full_name        = serializers.CharField(read_only=True)
    branch_name      = serializers.CharField(read_only=True)
    branch_id        = serializers.IntegerField(source='branch.id',            read_only=True)
    role_label       = serializers.CharField(source='get_role_display',        read_only=True)
    erp_username     = serializers.CharField(source='erp_user.username',       read_only=True)
    allowed_branch_ids    = serializers.SerializerMethodField()
    restricted_branch_ids = serializers.SerializerMethodField()

    def get_allowed_branch_ids(self, obj):
        return list(obj.allowed_branches.values_list('id', flat=True))

    def get_restricted_branch_ids(self, obj):
        return list(obj.restricted_branches.values_list('id', flat=True))

    class Meta:
        model  = StaffProfile
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name',
            'full_name', 'role', 'role_label',
            'branch', 'branch_id', 'branch_name',
            'access_all_branches',
            'allowed_branch_ids', 'restricted_branch_ids',
            'softech_username', 'erp_username',
            'phone', 'is_active',
            'can_see_all_customers', 'can_see_customer_phone',
            'created_at', 'updated_at',
        ]


class StaffProfileListSerializer(serializers.ModelSerializer):
    """Lightweight list serializer."""
    username    = serializers.CharField(source='user.username', read_only=True)
    full_name   = serializers.CharField(read_only=True)
    branch_name = serializers.CharField(read_only=True)
    role_label  = serializers.CharField(source='get_role_display', read_only=True)

    class Meta:
        model  = StaffProfile
        fields = [
            'id', 'username', 'full_name', 'role', 'role_label',
            'branch', 'branch_name', 'is_active',
            'access_all_branches',
        ]


class StaffProfileUpdateSerializer(serializers.ModelSerializer):
    """Used by admin to edit a user's role/access."""
    first_name = serializers.CharField(source='user.first_name', required=False)
    last_name  = serializers.CharField(source='user.last_name',  required=False)
    email      = serializers.CharField(source='user.email',      required=False)

    class Meta:
        model  = StaffProfile
        fields = [
            'role', 'branch', 'access_all_branches',
            'allowed_branches', 'restricted_branches',
            'phone', 'is_active',
            'first_name', 'last_name', 'email',
        ]

    def update(self, instance, validated_data):
        # Pop nested user fields
        user_data = validated_data.pop('user', {})
        if user_data:
            for attr, val in user_data.items():
                setattr(instance.user, attr, val)
            instance.user.save(update_fields=list(user_data.keys()))

        old_role   = instance.role
        old_branch = instance.branch_id

        # Update M2M
        allowed    = validated_data.pop('allowed_branches',    None)
        restricted = validated_data.pop('restricted_branches', None)

        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        instance.save()

        if allowed is not None:
            instance.allowed_branches.set(allowed)
        if restricted is not None:
            instance.restricted_branches.set(restricted)

        # Audit log
        _log_user_change(instance, old_role, old_branch, validated_data)
        return instance


class UserCreateSerializer(serializers.Serializer):
    """ERP-first user creation."""
    username   = serializers.CharField(max_length=50)
    password   = serializers.CharField(min_length=6, write_only=True)
    role       = serializers.ChoiceField(choices=[r[0] for r in StaffProfile._meta.get_field('role').choices])
    branch     = serializers.PrimaryKeyRelatedField(
        queryset=__import__('apps.branches.models', fromlist=['Branch']).Branch.objects.all(),
        required=False, allow_null=True,
    )
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name  = serializers.CharField(required=False, allow_blank=True)
    email      = serializers.EmailField(required=False, allow_blank=True)

    def validate_username(self, value):
        from .models import ERPUser
        if not ERPUser.objects.filter(username=value, is_active=True).exists():
            raise serializers.ValidationError(
                f'المستخدم "{value}" غير موجود في نظام الـ ERP. '
                f'يجب إنشاء المستخدم في SOFTECH أولاً.'
            )
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError(
                f'المستخدم "{value}" موجود بالفعل في النظام.'
            )
        return value

    def create(self, validated_data):
        from .models import ERPUser
        username   = validated_data['username']
        erp_user   = ERPUser.objects.get(username=username)
        user       = User.objects.create_user(
            username   = username,
            password   = validated_data['password'],
            first_name = validated_data.get('first_name', erp_user.full_name.split()[0] if erp_user.full_name else ''),
            last_name  = validated_data.get('last_name', ' '.join(erp_user.full_name.split()[1:]) if erp_user.full_name else ''),
            email      = validated_data.get('email', ''),
        )
        profile = StaffProfile.objects.create(
            user             = user,
            erp_user         = erp_user,
            role             = validated_data.get('role', 'branch'),
            branch           = validated_data.get('branch'),
            softech_username = username,
        )
        return profile


class UserActivityLogSerializer(serializers.ModelSerializer):
    target_name    = serializers.CharField(source='target_user.full_name', read_only=True)
    changed_by_name = serializers.CharField(source='changed_by.full_name', read_only=True)
    action_label   = serializers.CharField(source='get_action_display',    read_only=True)

    class Meta:
        model  = UserActivityLog
        fields = [
            'id', 'target_user', 'target_name',
            'changed_by', 'changed_by_name',
            'action', 'action_label',
            'old_value', 'new_value', 'note', 'created_at',
        ]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log_user_change(profile, old_role, old_branch_id, changes):
    try:
        from apps.users.middleware import get_current_user_profile
        changed_by = get_current_user_profile()

        if changes.get('role') and changes['role'] != old_role:
            UserActivityLog.objects.create(
                target_user=profile,
                changed_by=changed_by,
                action='role_changed',
                old_value={'role': old_role},
                new_value={'role': changes['role']},
            )
        if 'branch' in changes:
            UserActivityLog.objects.create(
                target_user=profile,
                changed_by=changed_by,
                action='branch_changed',
                old_value={'branch_id': old_branch_id},
                new_value={'branch_id': profile.branch_id},
            )
    except Exception:
        pass
