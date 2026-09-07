"""
apps/referral/views.py
"""
import logging
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.referral.models import ReferralCode, ReferralLead, ReferralEvent
from apps.referral.serializers import (
    ReferralCodeSerializer, ReferralLeadSerializer,
    ReferralEventSerializer, SubmitLeadSerializer,
)
from apps.referral.fraud import FraudEngine, AUTO_REJECT_THRESHOLD

logger = logging.getLogger('elrezeiky.referral')


class MyReferralCodeView(APIView):
    """GET /api/referral/my-code/ — get or create the calling user's referral code."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            customer = request.user.staff_profile.customer
        except Exception:
            return Response({'detail': 'لا يوجد عميل مرتبط بهذا الحساب'}, status=400)

        code = ReferralCode.get_or_create_for(customer)
        return Response(ReferralCodeSerializer(code).data)


class CustomerReferralCodeView(generics.RetrieveAPIView):
    """GET /api/referral/customers/<customer_id>/code/"""
    serializer_class   = ReferralCodeSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        from apps.customers.models import Customer
        customer = Customer.objects.get(pk=self.kwargs['customer_id'])
        return ReferralCode.get_or_create_for(customer)


class SubmitLeadView(APIView):
    """POST /api/referral/customers/<customer_id>/leads/ — submit a referral lead."""
    permission_classes = [IsAuthenticated]

    def post(self, request, customer_id):
        from apps.customers.models import Customer

        try:
            customer = Customer.objects.get(pk=customer_id)
        except Customer.DoesNotExist:
            return Response({'detail': 'العميل غير موجود'}, status=404)

        ser = SubmitLeadSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        ref_code = ReferralCode.get_or_create_for(customer)
        if not ref_code.is_active:
            return Response({'detail': 'كود الإحالة غير نشط'}, status=400)

        lead = ReferralLead.objects.create(
            referral_code=ref_code,
            referrer=customer,
            lead_name=data['lead_name'],
            lead_phone=data['lead_phone'],
            relationship=data['relationship'],
            notes=data.get('notes', ''),
            device_fingerprint=request.META.get('HTTP_X_DEVICE_FP', ''),
        )
        ReferralEvent.log(lead, 'submitted', f'تم الإرسال بواسطة {customer.name}')

        # Update referral code total_leads counter
        from django.db.models import F
        ReferralCode.objects.filter(pk=ref_code.pk).update(total_leads=F('total_leads') + 1)

        # Run fraud engine
        result = FraudEngine(lead).evaluate()
        if result['action'] == 'reject':
            lead.reject_fraud(', '.join(result['flags']))
            return Response(
                {'detail': 'تم رفض الإحالة — شُبهة احتيال', 'fraud_flags': result['flags']},
                status=400,
            )

        return Response(ReferralLeadSerializer(lead).data, status=201)


class LeadListView(generics.ListAPIView):
    serializer_class   = ReferralLeadSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = ReferralLead.objects.select_related('referrer', 'referral_code')
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        customer_id = self.kwargs.get('customer_id')
        if customer_id:
            qs = qs.filter(referrer_id=customer_id)
        return qs.order_by('-created_at')


class LeadDetailView(generics.RetrieveAPIView):
    serializer_class   = ReferralLeadSerializer
    permission_classes = [IsAuthenticated]
    queryset           = ReferralLead.objects.select_related('referrer', 'referral_code')


class LeadEventListView(generics.ListAPIView):
    serializer_class   = ReferralEventSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ReferralEvent.objects.filter(
            lead_id=self.kwargs['lead_id']
        ).order_by('created_at')


class InviteLeadView(APIView):
    """
    POST /api/referral/leads/<pk>/invite/
    Send a WhatsApp invitation message to the lead's phone number.
    The message includes the referrer's name and a direct wa.me link to register.
    Non-blocking — if WhatsApp is not configured the endpoint still returns 200
    with sent_via='manual'.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            lead = ReferralLead.objects.select_related('referrer', 'referral_code').get(pk=pk)
        except ReferralLead.DoesNotExist:
            return Response({'detail': 'الإحالة غير موجودة'}, status=404)

        if lead.status not in ('pending', 'invited'):
            return Response(
                {'detail': f'لا يمكن إرسال دعوة بالحالة الحالية: {lead.status}'},
                status=400,
            )

        referrer_name = lead.referrer.name if lead.referrer else 'أحد عملائنا'
        ref_url = lead.referral_code.referral_url if lead.referral_code_id else ''

        message = (
            f'أهلاً {lead.lead_name}،\n'
            f'يدعوك {referrer_name} للانضمام إلى صيدلية الرزيقي والاستفادة من عروضنا الحصرية.\n'
        )
        if ref_url:
            message += f'سجّل الآن: {ref_url}'

        sent_via = 'manual'
        try:
            from django.conf import settings
            if getattr(settings, 'WHATSAPP_TOKEN', ''):
                from apps.whatsapp.sender import WhatsAppSender
                WhatsAppSender().send_text(wa_id=lead.lead_phone, body=message)
                sent_via = 'whatsapp_api'
        except Exception as wa_err:
            logger.warning('InviteLeadView: WhatsApp send failed: %s', wa_err)

        # Mark lead as invited if it was still pending
        if lead.status == 'pending':
            lead.mark_invited()

        return Response({
            'detail': 'تم إرسال الدعوة',
            'sent_via': sent_via,
            'lead': ReferralLeadSerializer(lead).data,
        })


class ValidateLeadView(APIView):
    """POST /api/referral/leads/<pk>/validate/ — staff validates a registered lead."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            lead = ReferralLead.objects.get(pk=pk, status='registered')
        except ReferralLead.DoesNotExist:
            return Response({'detail': 'الإحالة غير موجودة أو غير قابلة للتحقق'}, status=404)

        points = int(request.data.get('points_reward', 100))
        lead.validate()

        # Credit loyalty points to referrer
        try:
            from apps.loyalty.models import LoyaltyAccount
            account = LoyaltyAccount.get_or_create_for(lead.referrer)
            account.add_points(
                points,
                reason=f'مكافأة إحالة ناجحة: {lead.lead_name}',
                source_type='referral',
                source_id=lead.pk,
            )
            lead.reward(points_awarded=points)
        except Exception as exc:
            logger.warning('Loyalty credit after referral validation failed: %s', exc)

        return Response(ReferralLeadSerializer(lead).data)
