from rest_framework import serializers
from apps.referral.models import ReferralCode, ReferralLead, ReferralEvent


class ReferralCodeSerializer(serializers.ModelSerializer):
    referral_url = serializers.CharField(read_only=True)
    qr_code      = serializers.SerializerMethodField()

    class Meta:
        model = ReferralCode
        fields = ['id', 'code', 'referral_url', 'qr_code', 'is_active',
                  'total_leads', 'validated_leads', 'total_points_earned', 'created_at']

    def get_qr_code(self, obj):
        return obj.generate_qr_svg()


class ReferralLeadSerializer(serializers.ModelSerializer):
    status_display  = serializers.CharField(source='get_status_display', read_only=True)
    referrer_name   = serializers.SerializerMethodField()

    class Meta:
        model = ReferralLead
        fields = [
            'id', 'referral_code', 'referrer', 'referrer_name',
            'lead_name', 'lead_phone', 'relationship', 'notes',
            'status', 'status_display',
            'fraud_score', 'fraud_flags',
            'otp_attempts', 'invitation_sent_at', 'invitation_expires_at',
            'created_at', 'validated_at', 'rewarded_at',
        ]
        read_only_fields = [
            'fraud_score', 'fraud_flags', 'otp_attempts',
            'invitation_sent_at', 'invitation_expires_at',
            'validated_at', 'rewarded_at',
        ]

    def get_referrer_name(self, obj):
        return obj.referrer.name if obj.referrer_id else None


class ReferralEventSerializer(serializers.ModelSerializer):
    event_type_display = serializers.CharField(source='get_event_type_display', read_only=True)

    class Meta:
        model = ReferralEvent
        fields = ['id', 'lead', 'event_type', 'event_type_display',
                  'message', 'created_at']


class SubmitLeadSerializer(serializers.Serializer):
    lead_name    = serializers.CharField(max_length=255)
    lead_phone   = serializers.CharField(max_length=30)
    relationship = serializers.ChoiceField(
        choices=ReferralLead.RELATIONSHIP_CHOICES, default='friend',
    )
    notes        = serializers.CharField(required=False, allow_blank=True, default='')
