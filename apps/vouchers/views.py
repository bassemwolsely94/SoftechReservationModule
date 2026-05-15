"""
apps/vouchers/views.py

Voucher Management — full production implementation.

Security rules enforced here:
  ① OTP plain code NEVER returned to API (only wa.me URL)
  ② Rate limits: max 3 resends per phone per 10 min, max 3 retries per OTP
  ③ Atomic transactions on all state-changing operations
  ④ select_for_update() on concurrent-sensitive paths
  ⑤ customer_phone masked for non-PII roles in document endpoints
"""
import logging

from django.db import transaction
from django.db.models import F, Sum, Count, Q
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import (
    Voucher, VoucherAssignment, VoucherOTP,
    VoucherRedemptionDocument, VoucherRedemption,
)
from .serializers import (
    VoucherListSerializer, VoucherCreateSerializer,
    VoucherAssignmentSerializer, VoucherAssignmentCreateSerializer,
    VoucherOTPSerializer,
    VoucherRedemptionDocumentSerializer,
    VoucherRedemptionSerializer,
    GenerateOTPSerializer, VerifyOTPSerializer,
    ValidateVoucherSerializer, MarkUsedSerializer,
)

logger = logging.getLogger('elrezeiky.vouchers')

# ── Constants ──────────────────────────────────────────────────────────────────
OTP_RESEND_LIMIT        = 3     # max resend per phone/voucher per OTP_RESEND_WINDOW
OTP_RESEND_WINDOW_SECS  = 600   # 10 minutes
OTP_EXPIRY_MINUTES      = 3
DOCUMENT_EXPIRY_MINUTES = 15
_PII_ROLES = ('admin', 'call_center', 'manager')


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


def _can_see_pii(request):
    p = _profile(request)
    return p and p.role in _PII_ROLES


# ── VoucherViewSet ─────────────────────────────────────────────────────────────

class VoucherViewSet(viewsets.ModelViewSet):
    """
    Full CRUD + redemption workflow:

      GET  /api/vouchers/vouchers/               — list
      POST /api/vouchers/vouchers/               — create
      GET  /api/vouchers/vouchers/{id}/          — detail
      PATCH /api/vouchers/vouchers/{id}/         — update

      POST /api/vouchers/vouchers/{id}/validate/         — check eligibility (no OTP)
      POST /api/vouchers/vouchers/{id}/generate-otp/     — send OTP via WhatsApp
      POST /api/vouchers/vouchers/{id}/verify-otp/       — verify OTP → create document
      POST /api/vouchers/vouchers/{id}/cancel/           — cancel voucher
      POST /api/vouchers/vouchers/{id}/assign/           — assign to phone
      GET  /api/vouchers/vouchers/{id}/redemptions/      — audit history
      GET  /api/vouchers/vouchers/lookup/                — lookup by code
      GET  /api/vouchers/vouchers/report/                — usage report

      GET  /api/vouchers/documents/{ref}/        — get document by reference_code
      POST /api/vouchers/documents/{ref}/mark-used/ — POS marks document as used
      GET  /api/vouchers/documents/{ref}/print/  — print receipt data
      POST /api/vouchers/documents/{ref}/whatsapp/ — WhatsApp share message
    """
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Voucher.objects.select_related(
            'customer', 'branch', 'created_by', 'free_item'
        )
        p = self.request.query_params

        status_q  = p.get('status')
        vtype     = p.get('type')
        category  = p.get('category')
        branch    = p.get('branch')
        customer  = p.get('customer')
        search    = p.get('search', '').strip()

        if status_q:
            qs = qs.filter(status=status_q)
        if vtype:
            qs = qs.filter(voucher_type=vtype)
        if category:
            qs = qs.filter(voucher_category=category)
        if branch:
            qs = qs.filter(branch_id=branch)
        if customer:
            qs = qs.filter(customer_id=customer)
        if search:
            qs = qs.filter(Q(code__icontains=search) | Q(title__icontains=search))

        return qs.order_by('-created_at')

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return VoucherCreateSerializer
        return VoucherListSerializer

    def perform_create(self, serializer):
        profile = _profile(self.request)
        code    = Voucher.generate_code()
        serializer.save(created_by=profile, code=code)

    # ── MODULE 1: Validate eligibility ─────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='validate')
    def validate_eligibility(self, request, pk=None):
        """
        POST { phone, order_amount? }
        Returns eligibility check without issuing OTP.
        Safe to call multiple times — no side effects.
        """
        voucher = self.get_object()
        ser = ValidateVoucherSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        phone        = ser.validated_data['phone']
        order_amount = float(ser.validated_data.get('order_amount') or 0)

        eligible, reason = voucher.check_customer_eligibility(phone)

        discount = 0.0
        if eligible and order_amount > 0:
            discount = voucher.calculate_discount(order_amount)
            if discount == 0.0 and voucher.min_order_value:
                eligible = False
                reason   = f'الحد الأدنى للطلب: {float(voucher.min_order_value):.2f} ج.م'

        return Response({
            'eligible':        eligible,
            'reason':          reason,
            'voucher_code':    voucher.code,
            'voucher_title':   voucher.title,
            'discount_type':   voucher.voucher_type,
            'discount_amount': discount,
            'max_discount_cap': float(voucher.max_discount_cap) if voucher.max_discount_cap else None,
            'min_order_value':  float(voucher.min_order_value)  if voucher.min_order_value  else None,
        }, status=status.HTTP_200_OK if eligible else status.HTTP_400_BAD_REQUEST)

    # ── MODULE 2: Generate OTP ─────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='generate-otp')
    def generate_otp(self, request, pk=None):
        """
        POST { phone, order_amount? }

        Security:
          ① Validates eligibility first
          ② Rate-limits resends: max 3 per phone per 10 min
          ③ Returns wa.me URL only (NOT the plain OTP)
          ④ OTP never logged in plaintext
        """
        voucher = self.get_object()
        ser = GenerateOTPSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        phone = ser.validated_data['phone']

        # Eligibility check
        eligible, reason = voucher.check_customer_eligibility(phone)
        if not eligible:
            return Response({'detail': reason}, status=status.HTTP_400_BAD_REQUEST)

        # Rate-limit: resends in last 10 min
        window_start  = timezone.now() - timezone.timedelta(seconds=OTP_RESEND_WINDOW_SECS)
        resend_count  = VoucherOTP.objects.filter(
            voucher=voucher, phone=phone,
            created_at__gte=window_start,
        ).count()
        if resend_count >= OTP_RESEND_LIMIT:
            return Response(
                {'detail': 'تجاوزت الحد المسموح به لإرسال OTP. انتظر 10 دقائق قبل المحاولة.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        # Read expiry from config (fallback 3 min)
        try:
            from apps.config.services import get_setting
            expiry = int(get_setting('voucher_otp_expiry_minutes', default=str(OTP_EXPIRY_MINUTES)))
        except Exception:
            expiry = OTP_EXPIRY_MINUTES

        # Create OTP — plain code is in the wa.me URL, never in the response
        otp, whatsapp_url = VoucherOTP.create_for_voucher(voucher, phone, expiry_minutes=expiry)

        logger.info(f'[OTP] Generated for voucher={voucher.code} phone={phone[-4:]}****')

        return Response({
            'detail':       f'تم إنشاء رمز OTP. افتح الرابط لإرساله عبر واتساب.',
            'otp_id':       otp.id,
            'expires_at':   otp.expires_at,
            'whatsapp_url': whatsapp_url,   # employee opens this → WhatsApp opens → sends to customer
            'sent_via':     'whatsapp',
        })

    # ── MODULE 3: Verify OTP → Create Document ─────────────────────────────────

    @action(detail=True, methods=['post'], url_path='verify-otp')
    @transaction.atomic
    def verify_otp(self, request, pk=None):
        """
        POST { code, phone, order_amount? }

        Security:
          ① select_for_update() prevents concurrent double-redemption
          ② Retry limit (3) enforced per OTP instance
          ③ Atomic: times_used incremented with F() — race-safe
          ④ Creates VoucherRedemptionDocument with unique reference_code

        On success returns the redemption document with reference_code for POS.
        """
        voucher = self.get_object()
        ser = VerifyOTPSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        plain        = ser.validated_data['code']
        phone        = ser.validated_data['phone']
        order_amount = float(ser.validated_data.get('order_amount') or 0)

        # Lock OTP row — prevent concurrent verification
        try:
            otp = (
                VoucherOTP.objects
                .select_for_update()
                .filter(voucher=voucher, phone=phone, is_used=False)
                .latest('created_at')
            )
        except VoucherOTP.DoesNotExist:
            return Response(
                {'detail': 'لا يوجد رمز OTP نشط لهذا الرقم'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if otp.is_expired:
            return Response(
                {'detail': 'انتهت صلاحية رمز OTP — أعد الإرسال'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if otp.retry_count >= otp.MAX_RETRIES:
            return Response(
                {'detail': 'تجاوزت الحد المسموح به للمحاولات. أعد إرسال OTP جديد.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not otp.verify(plain):
            attempts_left = otp.MAX_RETRIES - otp.retry_count
            return Response(
                {'detail': f'رمز OTP غير صحيح — تبقى {attempts_left} محاولة'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if document already exists (idempotency)
        existing = VoucherRedemptionDocument.objects.filter(
            voucher=voucher, otp=otp
        ).first()
        if existing:
            existing.refresh_document_status()
            return Response({
                'detail':   'تم التحقق مسبقاً — الوثيقة موجودة',
                'document': VoucherRedemptionDocumentSerializer(existing).data,
            })

        # Calculate discount
        discount = voucher.calculate_discount(order_amount) if order_amount > 0 else 0.0

        # Create redemption document
        profile = _profile(request)
        branch  = getattr(profile, 'branch', None)
        doc = VoucherRedemptionDocument.objects.create(
            voucher        = voucher,
            otp            = otp,
            customer_phone = phone,
            employee       = profile,
            branch         = branch,
            expires_at     = timezone.now() + timezone.timedelta(minutes=DOCUMENT_EXPIRY_MINUTES),
            reference_code = VoucherRedemptionDocument.generate_reference(),
            discount_applied = discount if discount else None,
            order_amount     = order_amount if order_amount else None,
        )

        # Atomic times_used increment — race-free
        Voucher.objects.filter(pk=voucher.pk).update(
            times_used = F('times_used') + 1,
            updated_at = timezone.now(),
        )
        voucher.refresh_from_db()
        voucher.refresh_status()

        logger.info(
            f'[OTP VERIFIED] voucher={voucher.code} ref={doc.reference_code} '
            f'employee={profile.user.username if profile else "?"}'
        )

        return Response({
            'detail':   'تم التحقق بنجاح ✓',
            'document': VoucherRedemptionDocumentSerializer(doc).data,
        })

    # ── MODULE 4: Assignment ───────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='assign')
    def assign(self, request, pk=None):
        """POST { customer_phone, customer?, expires_at? } — assign voucher to phone."""
        voucher = self.get_object()
        ser = VoucherAssignmentCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        phone = ser.validated_data['customer_phone']

        # Check if already assigned
        if VoucherAssignment.objects.filter(voucher=voucher, customer_phone=phone).exists():
            return Response(
                {'detail': 'هذا الهاتف مخصص له القسيمة بالفعل'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        assignment = VoucherAssignment.objects.create(
            voucher        = voucher,
            customer_phone = phone,
            customer       = ser.validated_data.get('customer'),
            assigned_by    = _profile(request),
            expires_at     = ser.validated_data.get('expires_at'),
        )
        return Response(
            VoucherAssignmentSerializer(assignment).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['get'], url_path='assignments')
    def assignments(self, request, pk=None):
        """List assignments for this voucher."""
        voucher     = self.get_object()
        assignments = voucher.assignments.select_related('customer', 'assigned_by').all()
        return Response(VoucherAssignmentSerializer(assignments, many=True).data)

    # ── Cancel ─────────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        voucher = self.get_object()
        if voucher.status == 'cancelled':
            return Response({'detail': 'القسيمة ملغاة بالفعل'}, status=status.HTTP_400_BAD_REQUEST)
        voucher.status = 'cancelled'
        voucher.save(update_fields=['status', 'updated_at'])
        logger.info(f'[CANCELLED] voucher={voucher.code} by={_profile(request)}')
        return Response({'detail': 'تم إلغاء القسيمة'})

    # ── Lookup by code ─────────────────────────────────────────────────────────

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

    # ── Redemption history ─────────────────────────────────────────────────────

    @action(detail=True, methods=['get'])
    def redemptions(self, request, pk=None):
        voucher = self.get_object()
        reds    = voucher.redemptions.select_related(
            'redeemed_by', 'branch', 'document'
        ).order_by('-redeemed_at')
        return Response(VoucherRedemptionSerializer(reds, many=True).data)

    # ── Report ─────────────────────────────────────────────────────────────────

    @action(detail=False, methods=['get'], url_path='report')
    def report(self, request):
        """
        GET /api/vouchers/vouchers/report/
        Params: branch, date_from, date_to

        Returns aggregate usage stats.
        """
        p          = request.query_params
        branch_id  = p.get('branch')
        date_from  = p.get('date_from')
        date_to    = p.get('date_to')

        reds = VoucherRedemption.objects.select_related('voucher', 'branch', 'redeemed_by')
        if branch_id:
            reds = reds.filter(branch_id=branch_id)
        if date_from:
            reds = reds.filter(redeemed_at__date__gte=date_from)
        if date_to:
            reds = reds.filter(redeemed_at__date__lte=date_to)

        summary = reds.aggregate(
            total_redemptions = Count('id'),
            total_discount    = Sum('discount_applied'),
            total_order_value = Sum('order_amount'),
        )

        # Top vouchers
        top_vouchers = (
            reds.values('voucher__code', 'voucher__title')
            .annotate(count=Count('id'), total=Sum('discount_applied'))
            .order_by('-count')[:10]
        )

        # By employee
        by_employee = (
            reds.values('redeemed_by__full_name')
            .annotate(count=Count('id'), total=Sum('discount_applied'))
            .order_by('-count')[:10]
        )

        # Expired / unused vouchers
        expired_unused = Voucher.objects.filter(
            status__in=['expired', 'active'],
            times_used=0,
        ).count()

        return Response({
            'summary':         summary,
            'top_vouchers':    list(top_vouchers),
            'by_employee':     list(by_employee),
            'expired_unused':  expired_unused,
        })


# ── DocumentViewSet ────────────────────────────────────────────────────────────

class DocumentViewSet(viewsets.GenericViewSet):
    """
    POS document management.
    Lookup is by reference_code (not pk).

      GET  /api/vouchers/documents/{reference_code}/
      POST /api/vouchers/documents/{reference_code}/mark-used/
      GET  /api/vouchers/documents/{reference_code}/print/
      POST /api/vouchers/documents/{reference_code}/whatsapp/
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = VoucherRedemptionDocumentSerializer
    lookup_field       = 'reference_code'
    lookup_url_kwarg   = 'reference_code'

    def get_queryset(self):
        return VoucherRedemptionDocument.objects.select_related(
            'voucher', 'employee', 'branch', 'otp'
        )

    def retrieve(self, request, reference_code=None):
        """GET /api/vouchers/documents/{reference_code}/ — get document status"""
        try:
            doc = self.get_queryset().get(reference_code=reference_code.upper())
        except VoucherRedemptionDocument.DoesNotExist:
            return Response({'detail': 'الوثيقة غير موجودة'}, status=status.HTTP_404_NOT_FOUND)
        doc.refresh_document_status()
        return Response(VoucherRedemptionDocumentSerializer(doc).data)

    @action(detail=True, methods=['post'], url_path='mark-used')
    @transaction.atomic
    def mark_used(self, request, reference_code=None):
        """
        POST /api/vouchers/documents/{ref}/mark-used/
        { order_amount?, notes? }

        POS calls this to finalize the discount.
        Creates the immutable VoucherRedemption audit record.
        """
        try:
            doc = (
                VoucherRedemptionDocument.objects
                .select_for_update()
                .select_related('voucher', 'otp')
                .get(reference_code=reference_code.upper())
            )
        except VoucherRedemptionDocument.DoesNotExist:
            return Response({'detail': 'الوثيقة غير موجودة'}, status=status.HTTP_404_NOT_FOUND)

        doc.refresh_document_status()

        if doc.status == 'used':
            return Response({'detail': 'الوثيقة مستخدمة بالفعل'}, status=status.HTTP_400_BAD_REQUEST)
        if doc.status in ('expired', 'cancelled'):
            return Response(
                {'detail': f'الوثيقة {doc.get_status_display()} — لا يمكن استخدامها'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ser = MarkUsedSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        order_amount = float(ser.validated_data.get('order_amount') or doc.order_amount or 0)
        notes        = ser.validated_data.get('notes', '')

        # Recalculate discount with actual order amount if provided
        discount = doc.voucher.calculate_discount(order_amount) if order_amount else float(doc.discount_applied or 0)

        # Mark document as used
        doc.status       = 'used'
        doc.used_at      = timezone.now()
        doc.order_amount = order_amount or doc.order_amount
        doc.discount_applied = discount
        doc.notes        = notes
        doc.save(update_fields=['status', 'used_at', 'order_amount', 'discount_applied', 'notes'])

        # Create final audit redemption record
        profile = _profile(request)
        branch  = getattr(profile, 'branch', None) if profile else doc.branch
        VoucherRedemption.objects.create(
            voucher          = doc.voucher,
            document         = doc,
            otp              = doc.otp,
            customer_phone   = doc.customer_phone,
            redeemed_by      = profile or doc.employee,
            branch           = branch or doc.branch,
            discount_applied = discount,
            order_amount     = order_amount,
            notes            = notes,
        )

        # Update assignment usage count
        VoucherAssignment.objects.filter(
            voucher=doc.voucher, customer_phone=doc.customer_phone, is_active=True
        ).update(usage_count=F('usage_count') + 1)

        logger.info(
            f'[MARK-USED] ref={doc.reference_code} voucher={doc.voucher.code} '
            f'discount={discount:.2f} by={profile.user.username if profile else "?"}'
        )

        return Response({
            'detail':          'تم تفعيل الوثيقة بنجاح ✓',
            'reference_code':  doc.reference_code,
            'discount_applied': discount,
            'voucher_code':    doc.voucher.code,
        })

    @action(detail=True, methods=['get'], url_path='print')
    def print_receipt(self, request, reference_code=None):
        """GET /api/vouchers/documents/{ref}/print/ — receipt data for UI print."""
        try:
            doc = self.get_queryset().get(reference_code=reference_code.upper())
        except VoucherRedemptionDocument.DoesNotExist:
            return Response({'detail': 'الوثيقة غير موجودة'}, status=status.HTTP_404_NOT_FOUND)

        doc.refresh_document_status()
        v = doc.voucher

        receipt = {
            'doc_type':       'voucher',
            'reference_code': doc.reference_code,
            'voucher_code':   v.code,
            'voucher_title':  v.title,
            'discount_type':  v.voucher_type,
            'discount_value': (
                f'{v.discount_pct}%'     if v.voucher_type == 'discount_pct'   else
                f'{float(v.discount_amount):.2f} ج.م' if v.voucher_type == 'discount_fixed' else
                f'{float(v.credit_amount):.2f} ج.م'  if v.voucher_type == 'credit'        else
                '—'
            ),
            'discount_applied':  float(doc.discount_applied) if doc.discount_applied else None,
            'order_amount':      float(doc.order_amount) if doc.order_amount else None,
            'status':            doc.status,
            'status_label':      doc.get_status_display(),
            'generated_at':      doc.generated_at.isoformat(),
            'expires_at':        doc.expires_at.isoformat(),
            'used_at':           doc.used_at.isoformat() if doc.used_at else None,
            'branch_name':       (doc.branch.name_ar or doc.branch.name) if doc.branch_id else '—',
            'employee_name':     doc.employee.full_name if doc.employee_id else '—',
            # Customer PII — masked for non-PII roles
            'customer_phone':    (
                doc.customer_phone if _can_see_pii(request)
                else (doc.customer_phone[:3] + '****' + doc.customer_phone[-3:]
                      if len(doc.customer_phone) >= 7 else '***')
            ),
            'printed_by':   _profile(request).full_name if _profile(request) else '—',
            'printed_at':   timezone.now().isoformat(),
        }
        return Response(receipt)

    @action(detail=True, methods=['post'], url_path='whatsapp')
    def share_whatsapp(self, request, reference_code=None):
        """POST /api/vouchers/documents/{ref}/whatsapp/ — WhatsApp approval message."""
        from urllib.parse import quote as urlquote
        try:
            doc = self.get_queryset().get(reference_code=reference_code.upper())
        except VoucherRedemptionDocument.DoesNotExist:
            return Response({'detail': 'الوثيقة غير موجودة'}, status=status.HTTP_404_NOT_FOUND)

        v = doc.voucher
        discount_str = (
            f'{float(doc.discount_applied):.2f} ج.م' if doc.discount_applied
            else (
                f'{v.discount_pct}%' if v.voucher_type == 'discount_pct'
                else f'{float(v.discount_amount):.2f} ج.م' if v.voucher_type == 'discount_fixed'
                else '—'
            )
        )

        expires_str = doc.expires_at.strftime('%H:%M')

        lines = [
            '✅ *قسيمة خصم معتمدة — صيدليات الرزيقي*',
            '',
            f'الكود: {v.code}',
            f'المرجع: {doc.reference_code}',
            f'صالح حتى: {expires_str}',
            '',
            f'*الخصم: {discount_str}*',
        ]
        if doc.order_amount:
            lines.append(f'قيمة الطلب: {float(doc.order_amount):.2f} ج.م')

        message_text = '\n'.join(lines)
        return Response({'message_text': message_text})
