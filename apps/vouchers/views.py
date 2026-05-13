"""
apps/vouchers/views.py

Voucher management + OTP generation & verification.
OTP delivery: stub that logs to console; replace with real SMS/WhatsApp gateway.
"""
import logging

from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Voucher, VoucherOTP, VoucherRedemption
from .serializers import (
    VoucherListSerializer, VoucherCreateSerializer,
    VoucherOTPSerializer, VoucherRedemptionSerializer,
    GenerateOTPSerializer, VerifyOTPSerializer,
)

logger = logging.getLogger('elrezeiky.vouchers')


def _send_otp(phone: str, plain_code: str, voucher: Voucher):
    """
    Stub OTP delivery.
    Replace this with a real WhatsApp/SMS gateway call.
    For now: log to stdout and return True.
    """
    msg = (
        f'رمز قسيمتك لدى صيدليات الرزيقي: *{plain_code}*\n'
        f'القسيمة: {voucher.title}\n'
        f'صالح لمدة 3 دقائق.'
    )
    logger.info(f'[OTP] → {phone}: {msg}')
    # TODO: integrate WhatsApp/Twilio/local SMS gateway here
    return True


class VoucherViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Voucher.objects.select_related('customer', 'branch', 'created_by', 'free_item')
        status_q = self.request.query_params.get('status')
        vtype    = self.request.query_params.get('type')
        branch   = self.request.query_params.get('branch')
        customer = self.request.query_params.get('customer')
        search   = self.request.query_params.get('search')
        if status_q:
            qs = qs.filter(status=status_q)
        if vtype:
            qs = qs.filter(voucher_type=vtype)
        if branch:
            qs = qs.filter(branch_id=branch)
        if customer:
            qs = qs.filter(customer_id=customer)
        if search:
            qs = qs.filter(code__icontains=search) | qs.filter(title__icontains=search)
        return qs.order_by('-created_at')

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return VoucherCreateSerializer
        return VoucherListSerializer

    def perform_create(self, serializer):
        profile = getattr(self.request.user, 'staff_profile', None)
        code    = Voucher.generate_code()
        serializer.save(created_by=profile, code=code)

    # ── Generate OTP ──────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='generate-otp')
    def generate_otp(self, request, pk=None):
        """
        POST { phone: '01xxxxxxxxx' }
        Creates an OTP, "sends" it (stub), returns expiry.
        """
        voucher = self.get_object()
        voucher.refresh_status()

        if voucher.status != 'active':
            return Response(
                {'detail': f'القسيمة غير نشطة (الحالة: {voucher.get_status_display()})'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ser = GenerateOTPSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        phone = ser.validated_data['phone']

        # Read expiry from settings (default 3 min)
        try:
            from apps.config.models import SystemSetting
            expiry = int(SystemSetting.objects.get(key='voucher_otp_expiry_minutes').value)
        except Exception:
            expiry = 3

        otp, plain = VoucherOTP.create_for_voucher(voucher, phone, expiry_minutes=expiry)
        sent = _send_otp(phone, plain, voucher)

        return Response({
            'detail':     f'تم إرسال رمز OTP إلى {phone}',
            'otp_id':     otp.id,
            'expires_at': otp.expires_at,
            'sent':       sent,
            # Return plain code only in DEBUG mode
            **({'plain_code': plain} if __import__('django.conf', fromlist=['settings']).settings.DEBUG else {}),
        })

    # ── Verify OTP ────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='verify-otp')
    def verify_otp(self, request, pk=None):
        """
        POST { code: '123456', phone: '01xxxxxxxxx' }
        Verifies OTP, increments times_used, creates VoucherRedemption.
        """
        voucher = self.get_object()
        ser = VerifyOTPSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        plain = ser.validated_data['code']
        phone = ser.validated_data['phone']

        # Find latest valid OTP for this phone
        try:
            otp = (
                VoucherOTP.objects
                .filter(voucher=voucher, phone=phone, is_used=False)
                .latest('created_at')
            )
        except VoucherOTP.DoesNotExist:
            return Response({'detail': 'لا يوجد رمز OTP نشط لهذا الرقم'}, status=status.HTTP_400_BAD_REQUEST)

        if not otp.verify(plain):
            if otp.is_expired:
                return Response({'detail': 'انتهت صلاحية رمز OTP'}, status=status.HTTP_400_BAD_REQUEST)
            return Response({'detail': 'رمز OTP غير صحيح'}, status=status.HTTP_400_BAD_REQUEST)

        # Increment usage
        voucher.times_used += 1
        voucher.save(update_fields=['times_used', 'updated_at'])
        voucher.refresh_status()

        # Audit log
        profile = getattr(request.user, 'staff_profile', None)
        branch  = getattr(profile, 'branch', None)
        VoucherRedemption.objects.create(
            voucher=voucher, otp=otp,
            redeemed_by=profile, branch=branch,
        )

        return Response({
            'detail':  'تم التحقق من رمز OTP بنجاح ✓',
            'voucher': VoucherListSerializer(voucher).data,
        })

    # ── Cancel voucher ────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        voucher = self.get_object()
        voucher.status = 'cancelled'
        voucher.save(update_fields=['status', 'updated_at'])
        return Response({'detail': 'تم إلغاء القسيمة'})

    # ── Lookup by code ────────────────────────────────────────────────────────

    @action(detail=False, methods=['get'], url_path='lookup')
    def lookup(self, request):
        """GET /api/vouchers/vouchers/lookup/?code=VCH-XXXX"""
        code = request.query_params.get('code', '').strip().upper()
        if not code:
            return Response({'detail': 'code مطلوب'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            voucher = Voucher.objects.get(code=code)
        except Voucher.DoesNotExist:
            return Response({'detail': 'القسيمة غير موجودة'}, status=status.HTTP_404_NOT_FOUND)
        voucher.refresh_status()
        return Response(VoucherListSerializer(voucher).data)

    # ── Redemption history ────────────────────────────────────────────────────

    @action(detail=True, methods=['get'])
    def redemptions(self, request, pk=None):
        voucher = self.get_object()
        reds    = voucher.redemptions.select_related('redeemed_by', 'branch').order_by('-redeemed_at')
        return Response(VoucherRedemptionSerializer(reds, many=True).data)
